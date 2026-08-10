import { showToast } from './toast.js'
import { t } from '../lang/index.js'

// Build stamp of THIS document. The worker is registered with it, so promoting a
// waiting worker always means aligning it with a build that is already loaded
const BUILD = typeof __APP_BUILD__ === 'string' ? __APP_BUILD__ : 'dev'
const VERSION = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : '0.0.0'

const BUILD_KEY = 'pwa:build'
const UPDATE_TOAST_KEY = 'pwa:update-toast'
const RELOAD_AT_KEY = 'pwa:reload-at'
const RELOAD_COUNT_KEY = 'pwa:reload-count'
const MAX_RELOADS = 2

/** Digest tail of a build stamp, the part short enough to show */
const buildId = (build) => String(build).split('-').slice(1).join('-') || String(build).slice(0, 7)

const isSupported = () => typeof navigator !== 'undefined' && 'serviceWorker' in navigator

const workerUrl = (build) => `/sw.js?v=${encodeURIComponent(build)}`

/** Build a worker was registered for, taken from its own script address */
function versionOfWorker(worker) {
  if (!worker?.scriptURL) return null
  try {
    return new URL(worker.scriptURL, window.location.origin).searchParams.get('v')
  } catch {
    return null
  }
}

async function unregisterAll() {
  try {
    const registrations = await navigator.serviceWorker.getRegistrations()
    await Promise.all(registrations.map((registration) => registration.unregister()))
    if (!('caches' in window)) return
    // Everything, not just our prefixes: a kill switch has to leave a clean disk
    const names = await caches.keys()
    await Promise.all(names.map((name) => caches.delete(name)))
  } catch {
    // The switch must never take the app down with it
  }
}

/**
 * Whether another alignment reload is still allowed.
 *
 * A module flag is not enough, it dies with the reload it is meant to survive.
 * When page and worker disagree on the build the controller keeps changing, and
 * without a counter the client reloads forever and never paints
 */
function canReload() {
  try {
    const now = Date.now()
    const last = Number(sessionStorage.getItem(RELOAD_AT_KEY) || 0)
    const count = Number(sessionStorage.getItem(RELOAD_COUNT_KEY) || 0)
    if (now - last <= 10000 || count >= MAX_RELOADS) return false
    sessionStorage.setItem(RELOAD_AT_KEY, String(now))
    sessionStorage.setItem(RELOAD_COUNT_KEY, String(count + 1))
    return true
  } catch {
    return true
  }
}

let reloading = false
// Set when this load already showed the update toast, so the reload below can
// carry it over instead of wiping it off the screen
let pendingToast = null

/**
 * Raise the worker to the build of THIS page.
 *
 * skipWaiting is deliberately not called inside the worker: an open tab has to
 * keep living on its own build so a lazily loaded chunk does not disappear under
 * it. The page that registered /sw.js?v=X is itself build X, so promoting worker
 * X here only aligns the worker with what is already loaded
 */
function alignWorkerToPage(registration) {
  if (!registration) return

  const promote = (worker) => {
    // installed plus a controller means the new worker is ready and waiting
    // while the old one still drives the page
    if (!worker || worker.state !== 'installed' || !navigator.serviceWorker.controller) return
    // Activation drops the caches of other builds, and an open tab lives on
    // those, so a worker from a foreign build must never be promoted here
    const build = versionOfWorker(worker)
    if (build && build !== BUILD) return
    worker.postMessage({ type: 'skip-waiting' })
  }

  promote(registration.waiting)

  registration.addEventListener('updatefound', () => {
    const installing = registration.installing
    installing?.addEventListener('statechange', () => promote(installing))
  })

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading || !canReload()) return
    reloading = true
    if (pendingToast) {
      try {
        sessionStorage.setItem(UPDATE_TOAST_KEY, pendingToast)
      } catch {
        // No sessionStorage, the toast simply does not survive the reload
      }
    }
    window.location.reload()
  })
}

/**
 * Report a finished update, comparing the build of this document with the last
 * one seen. Driven by that diff rather than by the worker lifecycle, so a first
 * visit stays silent
 */
export function notifyIfUpdated() {
  if (BUILD === 'dev') return
  try {
    const previous = localStorage.getItem(BUILD_KEY)
    localStorage.setItem(BUILD_KEY, BUILD)

    let carried = null
    try {
      carried = sessionStorage.getItem(UPDATE_TOAST_KEY)
      sessionStorage.removeItem(UPDATE_TOAST_KEY)
    } catch {
      // No sessionStorage, only a fresh change can be reported
    }

    if (!previous || previous === BUILD) {
      if (!carried) return
      pendingToast = carried
      showToast(`${t('updateDone')} ${carried}`, 'success', 10000)
      return
    }

    // The tag is the readable part, but a rebuild of the same tag keeps it while
    // the code changes, so the digest is appended only when it is the only thing
    // that moved
    const wasVersion = previous.split('-')[0]
    const label = wasVersion === VERSION ? `v.${VERSION} (v.${buildId(BUILD)})` : `v.${VERSION}`
    pendingToast = label
    showToast(`${t('updateDone')} ${label}`, 'success', 10000)
  } catch {
    // Private mode without localStorage, the toast is not worth failing over
  }
}

let lastUpdateCheck = 0
const UPDATE_CHECK_INTERVAL_MS = 60000

export function checkForUpdate() {
  if (!isSupported() || BUILD === 'dev') return
  const now = Date.now()
  if (now - lastUpdateCheck < UPDATE_CHECK_INTERVAL_MS) return
  lastUpdateCheck = now
  navigator.serviceWorker
    .getRegistration()
    .then((registration) => registration?.update())
    .catch(() => {
      // The next switch tries again
    })
}

export function bootServiceWorker({ enabled = true } = {}) {
  if (!isSupported()) return
  if (!enabled || BUILD === 'dev') {
    unregisterAll()
    return
  }

  // The worker relays a push here when a window is visible, so the same event
  // shows up as a toast instead of a system notification
  navigator.serviceWorker.addEventListener('message', (event) => {
    const data = event.data || {}
    if (data.type !== 'notification') return
    const payload = data.payload || {}
    showToast(payload.body || '', payload.level || 'info', 6000, { title: payload.title || '' })
  })

  notifyIfUpdated()

  const register = () => {
    navigator.serviceWorker
      .register(workerUrl(BUILD))
      .then(alignWorkerToPage)
      .catch(() => {
        // Without a worker the app behaves exactly as before
      })
  }

  // Waiting for load keeps the cache warm-up from stealing bandwidth from a
  // page that is still loading. The readyState check is required, not defensive:
  // this module can run after load has already fired
  if (document.readyState === 'complete') {
    register()
    return
  }
  window.addEventListener('load', register, { once: true })
}

/** Manual escape hatch from a wedged worker: drop it, wipe caches, reload */
export async function resetPwa() {
  await unregisterAll()
  window.location.reload()
}
