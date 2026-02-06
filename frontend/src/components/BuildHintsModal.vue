<script setup>
const props = defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  hints: { type: Array, required: true },
  loading: { type: Boolean, required: true }
})

const emit = defineEmits(['close'])
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4" @click.self="$emit('close')">
    <div class="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('whyBuildFailed') }}</h3>
        <button class="rounded-lg border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800" @click="$emit('close')">{{ t('done') }}</button>
      </div>
      <div v-if="loading" class="mt-4 text-xs text-slate-400">{{ t('loading') }}</div>
      <div v-else class="mt-4 space-y-3">
        <div v-for="hint in hints" :key="hint.id" class="rounded-xl border border-red-600/40 bg-red-900/10 p-3 text-xs text-slate-200">
          <div class="font-semibold text-red-200">{{ hint.title }}</div>
          <div class="mt-1 text-slate-300">{{ hint.detail }}</div>
          <div class="mt-2 text-slate-300">{{ hint.suggestion }}</div>
        </div>
        <div v-if="!hints.length" class="text-xs text-slate-400">{{ t('noHintsFound') }}</div>
      </div>
    </div>
  </div>
</template>
