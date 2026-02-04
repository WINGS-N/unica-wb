<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  modsLoading: { type: Boolean, required: true },
  modsEntries: { type: Array, required: true },
  modsDisabledIds: { type: Array, required: true }
})

const emit = defineEmits(['close', 'toggle'])

const disabledSet = computed(() => new Set(props.modsDisabledIds || []))
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4" @click.self="$emit('close')">
    <div class="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('modsList') }}</h3>
        <button class="rounded-lg border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800" @click="$emit('close')">{{ t('done') }}</button>
      </div>
      <p class="mt-2 text-xs text-slate-400">{{ t('modsHint') }} <span class="font-mono text-[11px]">unica/mods</span></p>

      <div v-if="modsLoading && !modsEntries.length" class="mt-5 flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/60 py-10">
        <div class="h-5 w-5 animate-spin rounded-full border-2 border-cyan-300 border-t-transparent"></div>
      </div>

      <div v-else class="mt-4 space-y-2">
        <button
          v-for="entry in modsEntries"
          :key="entry.id"
          class="flex w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition"
          :class="disabledSet.has(entry.id) ? 'border-red-600/50 bg-red-900/10 hover:bg-red-900/20' : 'border-slate-700 bg-slate-800/50 hover:bg-slate-800'"
          @click="$emit('toggle', entry.id)"
        >
          <div>
            <div class="text-sm font-semibold text-slate-100">{{ entry.module_dir }} - {{ entry.name || entry.module_dir }}</div>
            <div class="mt-1 text-xs text-slate-400">{{ entry.author || 'n/a' }}</div>
          </div>
          <span
            class="rounded-md px-2 py-1 text-xs font-semibold uppercase"
            :class="disabledSet.has(entry.id) ? 'bg-red-600/30 text-red-200' : 'bg-emerald-600/30 text-emerald-200'"
          >
            {{ disabledSet.has(entry.id) ? t('disabled') : t('enabled') }}
          </span>
        </button>
      </div>
    </div>
  </div>
</template>
