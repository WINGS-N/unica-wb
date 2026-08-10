<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: '' },
  tone: { type: String, default: '' },
  dot: { type: Boolean, default: true }
})

const TONES = {
  succeeded: 'is-success',
  reused: 'is-info',
  failed: 'is-danger',
  canceled: 'is-danger',
  running: 'is-warning',
  queued: 'is-warning'
}

const toneClass = computed(() => (props.tone ? `is-${props.tone}` : TONES[props.status] || ''))
</script>

<template>
  <span class="pill" :class="toneClass">
    <span v-if="dot" class="pill-dot" :class="status === 'running' || status === 'queued' ? 'animate-pulse' : ''" />
    <slot>{{ status }}</slot>
  </span>
</template>
