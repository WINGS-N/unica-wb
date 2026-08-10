<script setup>
import SamsungLoader from './SamsungLoader.vue'

defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  kicker: { type: String, default: '' },
  loading: { type: Boolean, default: false }
})
</script>

<template>
  <section class="surface-card flex flex-col gap-4">
    <header v-if="title || kicker || subtitle || $slots.actions" class="card-header">
      <div class="min-w-0">
        <div v-if="kicker" class="text-[12px] font-bold uppercase tracking-[0.14em] text-un1ca-kicker">
          {{ kicker }}
        </div>
        <h2 v-if="title" class="card-title mt-1 flex items-center gap-2">
          {{ title }}
          <SamsungLoader v-if="loading" small />
        </h2>
        <p v-if="subtitle" class="body-copy" :class="title ? 'mt-2' : 'mt-1'">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="actions-row shrink-0"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>
