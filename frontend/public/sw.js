/**
 * Service worker for the build interface.
 *
 * The cache is scoped to the build that registered this worker: the page asks for
 * /sw.js?v=<build>, so activating a worker always means aligning it with a build
 * that is already loaded. Caches of other builds are dropped on activate
 */

const params = new URL(self.location.href).searchParams

const VERSION = params.get('v') || 'dev'
const SHELL_CACHE = `shell-${VERSION}`
const DATA_CACHE = 'api-data'
const FLAGS_CACHE = 'sw-flags'

const OFFLINE_FALLBACK = '/offline.html'
const SHELL_URLS = [OFFLINE_FALLBACK, '/', '/index.html', '/manifest.webmanifest', '/appicon.svg']

// Read-only endpoints worth keeping for an offline open. Anything else is
// network-only: a build controller must not act on stale state
const CACHEABLE_API = [/\/api\/v1\/workspaces$/, /\/api\/v1\/jobs(\?|$)/, /\/api\/v1\/avatars\//]

const NAVIGATION_TIMEOUT = 6000

const FORCE_OFFLINE_KEY = 'https://sw.internal/force-offline'
let forcedOffline = false

const readFlag = async (key) => {
  try {
    const cache = await caches.open(FLAGS_CACHE)
    const stored = await cache.match(key)
    return stored ? (await stored.text()) === '1' : false
  } catch {
    return false
  }
}

const writeFlag = async (key, value) => {
  try {
    const cache = await caches.open(FLAGS_CACHE)
    await cache.put(key, new Response(value ? '1' : '0'))
  } catch {
    // Private mode without Cache Storage: the flag simply does not persist
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE)
      // One failed asset must not fail the whole install
      await Promise.all(
        SHELL_URLS.map((url) =>
          fetch(url, { cache: 'reload' })
            .then((response) => (response.ok ? cache.put(url, response) : null))
            .catch(() => null)
        )
      )
    })()
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      forcedOffline = await readFlag(FORCE_OFFLINE_KEY)
      const names = await caches.keys()
      await Promise.all(
        names.filter((name) => name.startsWith('shell-') && name !== SHELL_CACHE).map((name) => caches.delete(name))
      )
      await self.clients.claim()
    })()
  )
})

self.addEventListener('message', (event) => {
  const data = event.data || {}
  if (data.type === 'skip-waiting') {
    self.skipWaiting()
    return
  }
  if (data.type === 'force-offline') {
    forcedOffline = Boolean(data.value)
    writeFlag(FORCE_OFFLINE_KEY, forcedOffline)
    return
  }
  if (data.type === 'purge-data') {
    caches.delete(DATA_CACHE)
  }
})

const isCacheableApi = (url) => CACHEABLE_API.some((pattern) => pattern.test(url.pathname + url.search))

const withTimeout = (promise, ms) =>
  Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), ms))])

async function handleNavigation(request) {
  const cache = await caches.open(SHELL_CACHE)
  if (!forcedOffline) {
    try {
      const response = await withTimeout(fetch(request), NAVIGATION_TIMEOUT)
      if (response.ok) {
        // The SPA is one document, so every route is served by the same shell
        cache.put('/index.html', response.clone())
        return response
      }
    } catch {
      // fall through to the cache
    }
  }
  const cached = (await cache.match('/index.html')) || (await cache.match('/'))
  return cached || cache.match(OFFLINE_FALLBACK) || Response.error()
}

async function handleAsset(request) {
  const cache = await caches.open(SHELL_CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  if (forcedOffline) return Response.error()
  const response = await fetch(request)
  // Vite fingerprints asset names, so a hit is always the right build
  if (response.ok) cache.put(request, response.clone())
  return response
}

async function handleApi(request) {
  const cache = await caches.open(DATA_CACHE)
  if (!forcedOffline) {
    try {
      const response = await fetch(request)
      if (response.ok) cache.put(request, response.clone())
      return response
    } catch {
      // fall through to the cache
    }
  }
  const cached = await cache.match(request)
  if (cached) {
    // Marked so the app can tell the user it is looking at stale data
    const headers = new Headers(cached.headers)
    headers.set('x-offline-cached', '1')
    return new Response(await cached.blob(), { status: cached.status, headers })
  }
  return Response.error()
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request))
    return
  }
  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/fonts/')) {
    event.respondWith(handleAsset(request))
    return
  }
  if (url.pathname.startsWith('/api/')) {
    if (isCacheableApi(url)) event.respondWith(handleApi(request))
    return
  }
  if (SHELL_URLS.includes(url.pathname) || url.pathname.startsWith('/devices/')) {
    event.respondWith(handleAsset(request))
  }
})

/**
 * A push is only turned into a system notification when nobody is looking at the
 * app. With a visible window the event is handed to the page, which shows it as
 * a toast instead, so the same event never arrives twice
 */
self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { body: event.data ? event.data.text() : '' }
  }

  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const visible = clientList.find((client) => client.visibilityState === 'visible')
      if (visible) {
        visible.postMessage({ type: 'notification', payload })
        return
      }
      await self.registration.showNotification(payload.title || 'UN1CA Builder', {
        body: payload.body || '',
        icon: '/icon-192.png',
        badge: '/icon-192.png',
        tag: payload.tag || 'unica-wb',
        renotify: Boolean(payload.tag),
        data: { url: payload.url || '/jobs' }
      })
    })()
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = event.notification.data?.url || '/jobs'
  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of clientList) {
        if ('focus' in client) {
          client.navigate?.(target)
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    })()
  )
})
