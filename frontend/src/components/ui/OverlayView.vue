<script setup>
import { ChevronLeft } from 'lucide-vue-next'
import { closeOverlay } from '../../stores/nav.js'

defineProps({
  title: { type: String, default: '' },
  wide: { type: Boolean, default: false }
})
</script>

<template>
  <section class="overlay-view">
    <header class="flex shrink-0 items-center gap-2 px-3 pb-3 pt-6">
      <button
        type="button"
        class="rounded-full p-1.5 text-un1ca-mutedStrong transition-colors hover:text-un1ca-text"
        aria-label="back"
        @click="closeOverlay()"
      >
        <ChevronLeft :size="24" />
      </button>
      <h1 class="min-w-0 flex-1 truncate font-sharp text-[22px] font-bold text-white">{{ title }}</h1>
      <slot name="actions" />
    </header>
    <div class="overlay-body">
      <div class="page" :class="wide ? 'page-wide' : ''">
        <slot />
      </div>
    </div>
  </section>
</template>
