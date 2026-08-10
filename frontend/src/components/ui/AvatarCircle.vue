<script setup>
import { computed, ref, watch } from 'vue'
import { downloadUrl } from '../../stores/api.js'

const props = defineProps({
  // Either a direct src (local asset) or a GitHub `username`. On failure it
  // falls back to the initials disc
  src: { type: String, default: '' },
  username: { type: String, default: '' },
  initials: { type: String, default: '' },
  color: { type: String, default: '#3a3a4a' },
  size: { type: Number, default: 44 },
  // Fit the image inside the circle with padding instead of cropping it to fill
  contain: { type: Boolean, default: false }
})

const failed = ref(false)

// GitHub caches avatars for five minutes and never caches the redirect, so the
// backend proxies and stores them instead. It revalidates by ETag, which keeps a
// changed avatar showing up while still working offline
const resolved = computed(() => {
  if (props.username) {
    return downloadUrl(
      `/avatars/${encodeURIComponent(props.username)}`,
      { size: props.size * 2 },
      { skipWorkspace: true }
    )
  }
  return props.src
})

watch(resolved, () => {
  failed.value = false
})
</script>

<template>
  <span
    class="relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full"
    :style="{ width: `${size}px`, height: `${size}px`, backgroundColor: color }"
  >
    <span
      v-if="!resolved || failed"
      class="font-bold leading-none text-white"
      :style="{ fontSize: `${Math.round(size * 0.36)}px` }"
    >
      {{ initials }}
    </span>
    <img
      v-else
      :src="resolved"
      alt=""
      loading="lazy"
      class="absolute inset-0 h-full w-full"
      :class="contain ? 'object-contain p-[18%]' : 'object-cover'"
      @error="failed = true"
    />
  </span>
</template>
