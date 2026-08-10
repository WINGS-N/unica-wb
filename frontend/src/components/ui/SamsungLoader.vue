<script setup>
defineProps({
  small: { type: Boolean, default: false },
  mono: { type: Boolean, default: false }
})
</script>

<template>
  <span class="samsung-loader-box" :class="{ 'is-small': small }" role="status" aria-live="polite">
    <span class="samsung-loader" :class="{ 'is-small': small, 'is-mono': mono }">
      <span class="samsung-loader-dot samsung-loader-dot-top" />
      <span class="samsung-loader-dot samsung-loader-dot-right" />
      <span class="samsung-loader-dot samsung-loader-dot-bottom" />
      <span class="samsung-loader-dot samsung-loader-dot-left" />
    </span>
  </span>
</template>
