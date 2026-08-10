import { ref } from 'vue'

const STORAGE_HAPTICS = 'un1ca:haptics'

const PATTERNS = {
  tap: 12,
  toggle: [10, 30, 10],
  select: 8,
  success: [14, 60, 22],
  warning: [22, 70, 22],
  error: [26, 60, 26, 60, 40]
}

export const hapticsEnabled = ref(localStorage.getItem(STORAGE_HAPTICS) !== '0')

// A pointer device has no motor to answer with
export const hapticsSupported =
  typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function' && matchMedia('(hover: none)').matches

export function setHapticsEnabled(value) {
  hapticsEnabled.value = Boolean(value)
  localStorage.setItem(STORAGE_HAPTICS, hapticsEnabled.value ? '1' : '0')
  if (hapticsEnabled.value) haptic('toggle')
}

export function haptic(kind = 'tap') {
  if (!hapticsSupported || !hapticsEnabled.value) return
  const pattern = PATTERNS[kind] ?? PATTERNS.tap
  try {
    navigator.vibrate(pattern)
  } catch {
    // Never break a click over feedback
  }
}
