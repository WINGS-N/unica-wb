<script setup>
defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  job: { type: Object, default: null },
  modules: { type: Array, required: true }
})

const emit = defineEmits(['close'])
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div class="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('extraModsForJob') }}</h3>
        <p class="mt-2 text-sm text-slate-300">
          Job <span class="font-mono text-xs">{{ job?.id }}</span>
        </p>
        <div class="mt-4 max-h-72 space-y-2 overflow-auto pr-1">
          <div v-for="m in modules" :key="`${m.module_dir}-${m.id}`" class="rounded-lg border border-slate-700 bg-slate-800/70 p-3">
            <div class="text-sm font-semibold text-slate-100">{{ m.name || m.module_dir }}</div>
            <div class="mt-1 text-xs text-slate-300">dir: {{ m.module_dir }}</div>
            <div class="text-xs text-slate-300">id: {{ m.id || 'n/a' }} | ver: {{ m.version || 'n/a' }} ({{ m.versionCode || 'n/a' }})</div>
            <div class="text-xs text-slate-300">author: {{ m.author || 'n/a' }}</div>
            <div class="mt-1 text-xs text-slate-400">{{ m.description || 'No description' }}</div>
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
            {{ t('close') }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
