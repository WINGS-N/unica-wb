<script setup>
import { computed } from 'vue'
import SamsungLoader from './SamsungLoader.vue'
import { haptic } from '../../stores/haptics.js'

// Written out in full instead of `button-${variant}`: Tailwind scans source text
// for class names, and a class it never sees as a literal gets tree-shaken out
const VARIANTS = {
  primary: 'button-primary',
  secondary: 'button-secondary',
  ghost: 'button-ghost',
  danger: 'button-danger',
  text: 'button-text'
}

const props = defineProps({
  variant: { type: String, default: 'secondary' },
  small: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  type: { type: String, default: 'button' }
})

function onPointerDown() {
  if (props.disabled || props.loading) return
  haptic(props.variant === 'danger' ? 'warning' : 'tap')
}

const classes = computed(() => [
  VARIANTS[props.variant] || VARIANTS.secondary,
  { 'is-small': props.small, 'is-block': props.block }
])
</script>

<template>
  <button :type="type" :class="classes" :disabled="disabled || loading" @pointerdown="onPointerDown">
    <SamsungLoader v-if="loading" small mono />
    <slot />
  </button>
</template>
