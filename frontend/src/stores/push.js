import { ref } from 'vue'
import { apiFetch } from './api.js'
import { showToast } from './toast.js'
import { language, t } from '../lang/index.js'

export const pushSupported = ref(false)
export const pushPermission = ref('default')
export const pushSubscribed = ref(false)
export const pushBusy = ref(false)

// Safari only exposes the Push API to an installed app, so a browser tab there
// needs an explanation rather than a dead button
export const isStandalone = () =>
  typeof window !== 'undefined' &&
  (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true)

export const isIos = () => typeof navigator !== 'undefined' && /iphone|ipad|ipod/i.test(navigator.userAgent)

function supported() {
  return (
    typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  )
}

// The VAPID key arrives base64url encoded, pushManager wants bytes
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)))
}

async function currentSubscription() {
  if (!supported()) return null
  const registration = await navigator.serviceWorker.ready
  return registration.pushManager.getSubscription()
}

export async function refreshPushState() {
  pushSupported.value = supported()
  if (!pushSupported.value) return
  pushPermission.value = Notification.permission
  try {
    pushSubscribed.value = Boolean(await currentSubscription())
  } catch {
    pushSubscribed.value = false
  }
}

async function announce(subscription) {
  const payload = subscription.toJSON()
  await apiFetch('/push/subscriptions', {
    method: 'POST',
    skipWorkspace: true,
    json: { endpoint: payload.endpoint, keys: payload.keys, language: language.value }
  })
}

export async function enablePush() {
  if (!supported()) return
  pushBusy.value = true
  try {
    // Permission is only ever asked from a click: browsers treat an unprompted
    // request as spam and Safari rejects it outright
    const result = await Notification.requestPermission()
    pushPermission.value = result
    if (result !== 'granted') {
      showToast(t('pushDenied'), 'warning')
      return
    }
    const { public_key: publicKey } = await apiFetch('/push/config', { skipWorkspace: true })
    if (!publicKey) {
      showToast(t('pushUnavailable'), 'error')
      return
    }
    const registration = await navigator.serviceWorker.ready
    const subscription =
      (await registration.pushManager.getSubscription()) ||
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey)
      }))
    await announce(subscription)
    pushSubscribed.value = true
    showToast(t('pushEnabled'), 'success')
  } catch (e) {
    showToast(`${t('pushFailed')}: ${e?.message || e}`, 'error')
  } finally {
    pushBusy.value = false
  }
}

export async function disablePush() {
  pushBusy.value = true
  try {
    const subscription = await currentSubscription()
    if (!subscription) {
      pushSubscribed.value = false
      return
    }
    const { endpoint } = subscription.toJSON()
    await subscription.unsubscribe()
    await apiFetch('/push/subscriptions', { method: 'DELETE', skipWorkspace: true, json: { endpoint } })
    pushSubscribed.value = false
    showToast(t('pushDisabled'), 'warning')
  } catch (e) {
    showToast(`${t('pushFailed')}: ${e?.message || e}`, 'error')
  } finally {
    pushBusy.value = false
  }
}

// Keeps the stored language in step with the app, so notifications keep
// arriving in the language currently selected
export async function syncPushLanguage() {
  if (!pushSubscribed.value) return
  const subscription = await currentSubscription()
  if (!subscription) return
  try {
    await announce(subscription)
  } catch {
    // Retried on the next load
  }
}

export async function sendTestPush() {
  await apiFetch('/push/test', { method: 'POST', skipWorkspace: true })
}
