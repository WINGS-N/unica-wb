import { ref } from 'vue'
import { t } from '../lang/index.js'

export const confirmState = ref(null)

let resolver = null

// Destructive actions ask first. Resolves true only when the user confirms
export function confirm({ title, message, confirmText, cancelText, danger = false }) {
  return new Promise((resolve) => {
    if (resolver) resolver(false)
    resolver = resolve
    confirmState.value = {
      title: title || t('confirmTitle'),
      message: message || '',
      confirmText: confirmText || t('confirm'),
      cancelText: cancelText || t('cancel'),
      danger
    }
  })
}

export function resolveConfirm(value) {
  confirmState.value = null
  if (resolver) {
    const fn = resolver
    resolver = null
    fn(Boolean(value))
  }
}
