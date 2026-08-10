import { ref } from 'vue'

export const toasts = ref([])

let seq = 0

// The countdown lives in the host component, which pauses it while the pointer
// is over the toast; the store only owns the list
export function showToast(message, type = 'info', duration = 4500, options = {}) {
  const text = String(message ?? '').trim()
  if (!text) return ''
  const id = options.id || `${Date.now()}-${++seq}`
  const entry = { id, message: text, type, duration, title: options.title || '', actions: options.actions || [] }
  // A repeat of the same id replaces the toast instead of stacking a twin
  toasts.value = [...toasts.value.filter((x) => x.id !== id), entry]
  return id
}

export function dismissToast(id) {
  toasts.value = toasts.value.filter((x) => x.id !== id)
}
