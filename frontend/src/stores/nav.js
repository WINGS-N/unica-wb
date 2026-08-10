import { computed } from 'vue'
import { router } from '../router/index.js'

// Thin wrapper over the router so views keep speaking in tabs and overlays
export const activeTab = computed(() => router.currentRoute.value.meta?.tab || 'build')
export const overlay = computed(() => (router.currentRoute.value.meta?.overlay ? router.currentRoute.value.name : ''))

export function goTab(name) {
  return router.push({ name })
}

export function openOverlay(name, params) {
  return router.push(params ? { name, params } : { name })
}

export function closeOverlay() {
  // Prefer real history so the back gesture and this button agree; fall back to
  // the owning tab when the overlay was opened directly by URL
  if (window.history.state?.back) return router.back()
  return router.push({ name: router.currentRoute.value.meta?.tab || 'build' })
}
