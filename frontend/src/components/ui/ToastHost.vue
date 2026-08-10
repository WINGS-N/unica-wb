<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { dismissToast, toasts } from '../../stores/toast.js'

const SWIPE_THRESHOLD = 70
const SWIPE_FADE_OVER = 220

// Per-toast countdown, paused while the pointer rests on the toast so a message
// cannot slip away from under the cursor
const timers = new Map()
const drag = ref({})

function clearTimer(id) {
  const timer = timers.get(id)
  if (!timer) return
  clearTimeout(timer.handle)
  timers.delete(id)
}

function startTimer(toast) {
  if (!toast.duration) return
  const existing = timers.get(toast.id)
  const remaining = existing ? existing.remaining : toast.duration
  if (remaining <= 0) return
  timers.set(toast.id, {
    remaining,
    startedAt: Date.now(),
    handle: setTimeout(() => close(toast.id), remaining)
  })
}

function pauseTimer(id) {
  const timer = timers.get(id)
  if (!timer) return
  clearTimeout(timer.handle)
  timers.set(id, { ...timer, remaining: timer.remaining - (Date.now() - timer.startedAt) })
}

function resumeTimer(toast) {
  const timer = timers.get(toast.id)
  if (!timer) return
  startTimer(toast)
}

function close(id) {
  clearTimer(id)
  const next = { ...drag.value }
  delete next[id]
  drag.value = next
  dismissToast(id)
}

watch(
  toasts,
  (list) => {
    const alive = new Set(list.map((x) => x.id))
    for (const id of [...timers.keys()]) if (!alive.has(id)) clearTimer(id)
    for (const toast of list) if (!timers.has(toast.id)) startTimer(toast)
  },
  { immediate: true, deep: false }
)

onBeforeUnmount(() => {
  for (const id of [...timers.keys()]) clearTimer(id)
})

// One code path for finger and mouse; touch-action keeps the page scrollable
function onPointerDown(event, toast) {
  event.currentTarget.setPointerCapture?.(event.pointerId)
  pauseTimer(toast.id)
  drag.value = { ...drag.value, [toast.id]: { startX: event.clientX, shift: 0, active: true } }
}

function onPointerMove(event, toast) {
  const state = drag.value[toast.id]
  if (!state?.active) return
  drag.value = { ...drag.value, [toast.id]: { ...state, shift: event.clientX - state.startX } }
}

function onPointerUp(toast) {
  const state = drag.value[toast.id]
  if (!state?.active) return
  const shift = state.shift
  if (Math.abs(shift) > SWIPE_THRESHOLD) {
    drag.value = { ...drag.value, [toast.id]: { ...state, active: false, flung: shift > 0 ? 1 : -1 } }
    setTimeout(() => close(toast.id), 220)
    return
  }
  drag.value = { ...drag.value, [toast.id]: { ...state, active: false, shift: 0 } }
  resumeTimer(toast)
}

function runAction(toast, action) {
  close(toast.id)
  action.onClick?.()
}

function toastStyle(toast) {
  const state = drag.value[toast.id]
  if (!state) return undefined
  if (state.flung) {
    return {
      transform: `translateX(${state.flung * 140}%)`,
      opacity: 0,
      transition: 'transform .22s ease, opacity .22s ease'
    }
  }
  if (state.active) {
    return {
      transform: `translateX(${state.shift}px)`,
      opacity: String(Math.max(0, 1 - Math.abs(state.shift) / SWIPE_FADE_OVER)),
      animation: 'none'
    }
  }
  return { transform: 'translateX(0)', opacity: '1', transition: 'transform .2s ease, opacity .2s ease' }
}
</script>

<template>
  <div class="toast-stack">
    <TransitionGroup name="toast-list">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast toast-glow"
        :class="[`is-${toast.type}`, { 'is-rich': toast.actions?.length || toast.title }]"
        role="status"
        :style="toastStyle(toast)"
        @pointerdown="onPointerDown($event, toast)"
        @pointermove="onPointerMove($event, toast)"
        @pointerup="onPointerUp(toast)"
        @pointercancel="onPointerUp(toast)"
        @mouseenter="pauseTimer(toast.id)"
        @mouseleave="resumeTimer(toast)"
      >
        <span class="toast-dot" :class="toast.actions?.length || toast.title ? 'mt-1.5' : ''" />
        <span class="toast-body">
          <span v-if="toast.title" class="toast-title">{{ toast.title }}</span>
          <span class="toast-text">{{ toast.message }}</span>
          <span v-if="toast.actions?.length" class="toast-actions">
            <button
              v-for="action in toast.actions"
              :key="action.label"
              type="button"
              class="toast-action"
              :class="{ 'is-primary': action.primary }"
              @pointerdown.stop
              @click.stop="runAction(toast, action)"
            >
              {{ action.label }}
            </button>
          </span>
        </span>
      </div>
    </TransitionGroup>
  </div>
</template>
