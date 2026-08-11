import { ref } from 'vue'

export const API_BASE = import.meta.env.VITE_API_BASE || ''
export const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api/v1'

const STORAGE_AUTH_TOKEN = 'un1ca:authToken'
const STORAGE_WORKSPACE = 'un1ca:workspaceId'

export const authEnabled = ref(false)
export const authToken = ref(localStorage.getItem(STORAGE_AUTH_TOKEN) || '')
export const unauthorizedOpen = ref(false)

// Every workspace-scoped request carries this id; the server falls back to the
// first workspace when it is empty
export const activeWorkspaceId = ref(localStorage.getItem(STORAGE_WORKSPACE) || '')

export function setAuthToken(token) {
  authToken.value = token || ''
  if (token) localStorage.setItem(STORAGE_AUTH_TOKEN, token)
  else localStorage.removeItem(STORAGE_AUTH_TOKEN)
}

export function setActiveWorkspaceId(id) {
  activeWorkspaceId.value = id || ''
  if (id) localStorage.setItem(STORAGE_WORKSPACE, id)
  else localStorage.removeItem(STORAGE_WORKSPACE)
}

function buildUrl(path, params = {}, { skipWorkspace = false } = {}) {
  const search = new URLSearchParams()
  if (!skipWorkspace && activeWorkspaceId.value) search.set('workspace', activeWorkspaceId.value)
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return `${API_BASE}${API_PREFIX}${path}${qs ? `?${qs}` : ''}`
}

export function apiUrl(path, params = {}, options = {}) {
  return buildUrl(path, params, options)
}

// Same as apiUrl but usable from an <a href>: the token has to ride in the
// query string because the browser will not send our Authorization header
export function downloadUrl(path, params = {}, options = {}) {
  const url = buildUrl(path, params, options)
  if (!authToken.value) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(authToken.value)}`
}

// A proxy in front of the api answers with these while it has nothing to talk
// to, which is a state of the whole backend rather than of one request
const UNAVAILABLE_STATUSES = new Set([502, 503, 504])

// The server pings every 20s on every stream
const SOCKET_STALE_AFTER_MS = 60000
const SOCKET_WATCHDOG_MS = 10000

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
    this.unavailable = UNAVAILABLE_STATUSES.has(status)
    // status 0 means the request never reached the server: offline, DNS, a
    // dropped connection. Those are a connectivity state, not a failure worth
    // reporting once per request
    this.offline = status === 0
  }
}

async function readError(response) {
  const raw = await response.text()
  try {
    const parsed = JSON.parse(raw)
    return String(parsed.detail || parsed.message || `HTTP ${response.status}`)
  } catch {
    // Anything the api did not write is a proxy error page: it is html, it is
    // long, and it says nothing a status code does not
    return `HTTP ${response.status}`
  }
}

export async function apiFetch(path, options = {}) {
  const { params, json, skipWorkspace, raw, ...rest } = options
  const headers = { ...(rest.headers || {}) }
  if (authToken.value) headers.Authorization = `Bearer ${authToken.value}`
  let body = rest.body
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }

  let response
  try {
    response = await fetch(buildUrl(path, params, { skipWorkspace }), { ...rest, headers, body })
  } catch (error) {
    throw new ApiError(String(error?.message || 'network error'), 0)
  }
  if (response.status === 401) {
    authEnabled.value = true
    unauthorizedOpen.value = true
    throw new ApiError('Unauthorized', 401)
  }
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status)
  }
  if (raw) return response
  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export function buildWsUrl(path, params = {}) {
  // Build ws url from API_BASE and the current browser protocol
  let origin
  if (!API_BASE) {
    origin = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  } else if (API_BASE.startsWith('http://') || API_BASE.startsWith('https://')) {
    const url = new URL(API_BASE)
    origin = `${url.protocol === 'https:' ? 'wss:' : 'ws:'}//${url.host}`
  } else {
    origin = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${API_BASE}`
  }
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  if (authToken.value) search.set('token', authToken.value)
  const qs = search.toString()
  return `${origin}${API_PREFIX}${path}${qs ? `?${qs}` : ''}`
}

// Reconnecting websocket with capped exponential backoff. The old fixed 1.5s
// retry hammered the server for as long as auth was rejected
export function createReconnectingSocket({ path, params, onMessage, onOpen, onClose }) {
  let socket = null
  let timer = null
  let watchdog = null
  let attempt = 0
  let stopped = false
  let lastSeenAt = 0

  // Anything between the browser and the server can drop a connection without
  // sending a close frame, and the socket then stays OPEN forever with nothing
  // arriving on it. The server pings, so silence past this long means dead
  function isStale() {
    return lastSeenAt > 0 && Date.now() - lastSeenAt > SOCKET_STALE_AFTER_MS
  }

  function reopen() {
    if (stopped || !socket) return
    socket.onclose = null
    socket.close()
    socket = null
    // The fresh attempt gets a full window of its own before it counts as stale
    lastSeenAt = Date.now()
    if (onClose) onClose()
    connect()
  }

  function onWake() {
    if (document.visibilityState !== 'visible') return
    if (isStale()) reopen()
  }

  function connect() {
    if (stopped) return
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return
    socket = new WebSocket(buildWsUrl(path, params))
    socket.onopen = () => {
      attempt = 0
      lastSeenAt = Date.now()
      if (onOpen) onOpen()
    }
    socket.onmessage = (event) => {
      lastSeenAt = Date.now()
      let payload = null
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      if (!payload || payload.type === 'ping') return
      onMessage(payload)
    }
    socket.onclose = (event) => {
      socket = null
      // A deliberate close is not a connection loss, so it must not arm the
      // caller's polling fallback
      if (stopped) return
      if (onClose) onClose()
      // 4401 is our auth rejection: retrying on a loop would just spin
      const delay = event?.code === 4401 ? 15000 : Math.min(15000, 1000 * 2 ** attempt)
      attempt += 1
      timer = setTimeout(connect, delay)
    }
  }

  connect()
  watchdog = setInterval(() => {
    if (!stopped && isStale()) reopen()
  }, SOCKET_WATCHDOG_MS)
  document.addEventListener('visibilitychange', onWake)
  window.addEventListener('online', onWake)

  return {
    isOpen() {
      return Boolean(socket && socket.readyState === WebSocket.OPEN)
    },
    send(payload) {
      if (!socket || socket.readyState !== WebSocket.OPEN) return false
      socket.send(JSON.stringify(payload))
      return true
    },
    close() {
      stopped = true
      if (timer) clearTimeout(timer)
      timer = null
      if (watchdog) clearInterval(watchdog)
      watchdog = null
      document.removeEventListener('visibilitychange', onWake)
      window.removeEventListener('online', onWake)
      if (socket && typeof socket.close === 'function') socket.close()
      socket = null
    },
    restart() {
      attempt = 0
      if (timer) clearTimeout(timer)
      timer = null
      if (socket && typeof socket.close === 'function') socket.close()
      socket = null
      stopped = false
      lastSeenAt = Date.now()
      if (!watchdog) {
        watchdog = setInterval(() => {
          if (!stopped && isStale()) reopen()
        }, SOCKET_WATCHDOG_MS)
        document.addEventListener('visibilitychange', onWake)
        window.addEventListener('online', onWake)
      }
      connect()
    }
  }
}
