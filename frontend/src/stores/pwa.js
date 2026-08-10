import { ref } from 'vue'
import { showToast } from './toast.js'
import { t } from '../lang/index.js'

// Build stamp of THIS document. The worker is registered with it, so activating
// a waiting worker always means aligning it with a build that is already loaded
const BUILD = typeof __APP_BUILD__ === 'string' ? __APP_BUILD__ : 'dev'

const SW_URL = `/sw.js?v=${encodeURIComponent(BUILD)}`
const RELOAD_AT_KEY = 'pwa:reload-at'
const RELOAD_COUNT_KEY = 'pwa:reload-count'
const MAX_RELOADS = 2

export const updateReady = ref(false)
export const offlineReady = ref(false)

const isSupported = () => typeof navigator !== 'undefined' && 'serviceWorker' in navigator

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

function promptUpdate(worker) {
  updateReady.value = true
  showToast(t('updateReadyText'), 'info', 0, {
    id: 'pwa-update',
    title: t('updateReadyTitle'),
    actions: [
      {
        label: t('updateReadyAction'),
        primary: true,
        onClick() {
          worker.postMessage({ type: 'skip-waiting' })
        }
      }
    ]
  })
}

function watchRegistration(registration) {
  if (registration.waiting && navigator.serviceWorker.controller) {
    promptUpdate(registration.waiting)
  }
  registration.addEventListener('updatefound', () => {
    const installing = registration.installing
    installing?.addEventListener('statechange', () => {
      if (installing.state !== 'installed') return
      if (navigator.serviceWorker.controller) {
        promptUpdate(installing)
        return
      }
      // First install with no controller: the app is now available offline
      offlineReady.value = true
    })
  })
}

export function bootServiceWorker({ enabled = true } = {}) {
  if (!isSupported()) return
  if (!enabled) {
    unregisterAll()
    return
  }

  const register = () => {
    navigator.serviceWorker
      .register(SW_URL)
      .then(watchRegistration)
      .catch(() => {
        // Without a worker the app behaves exactly as before
      })
  }

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading || !canReload()) return
    reloading = true
    window.location.reload()
  })

  // The worker relays a push here when a window is visible, so the same event
  // shows up as a toast instead of a system notification
  navigator.serviceWorker.addEventListener('message', (event) => {
    const data = event.data || {}
    if (data.type !== 'notification') return
    const payload = data.payload || {}
    showToast(payload.body || '', payload.level || 'info', 6000, { title: payload.title || '' })
  })

  if (document.readyState === 'complete') {
    register()
    return
  }
  window.addEventListener('load', register, { once: true })
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

/** Manual escape hatch from a wedged worker: drop it, wipe caches, reload */
export async function resetPwa() {
  await unregisterAll()
  window.location.reload()
}
