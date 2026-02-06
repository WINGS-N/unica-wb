<script setup>
const props = defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  artifacts: { type: Array, required: true },
  artifactsLoading: { type: Boolean, required: true },
  target: { type: String, required: true },
  apiBase: { type: String, required: true },
  apiPrefix: { type: String, required: true },
  authToken: { type: String, required: true }
})

const emit = defineEmits(['close'])

function formatBytes(bytes) {
  const value = Number(bytes || 0)
  if (value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const scaled = value / (1024 ** idx)
  return `${scaled.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4" @click.self="$emit('close')">
    <div class="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('artifactsHistory') }}</h3>
        <button class="rounded-lg border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800" @click="$emit('close')">{{ t('done') }}</button>
      </div>
      <div class="mt-2 text-xs text-slate-400">{{ target ? `${t('target')}: ${target}` : t('allDevices') }}</div>
      <div v-if="artifactsLoading" class="mt-5 text-xs text-slate-400">{{ t('loading') }}</div>
      <div v-else class="mt-4 space-y-2">
        <div
          v-for="item in artifacts"
          :key="item.job_id"
          class="rounded-xl border border-slate-700 bg-slate-800/70 p-3 text-xs text-slate-200"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="font-semibold">{{ item.target }} • {{ item.job_id }}</div>
            <a class="rounded-md border border-emerald-500/60 bg-emerald-500/20 px-2 py-1 text-[10px] font-semibold uppercase text-emerald-200 hover:bg-emerald-500/30" :href="`${apiBase}${apiPrefix}/jobs/${item.job_id}/artifact${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`">
              {{ t('downloadZip') }}
            </a>
          </div>
          <div class="mt-1 text-[11px] text-slate-400">{{ formatBytes(item.size_bytes) }} • {{ item.finished_at || 'n/a' }}</div>
          <div class="mt-1 text-[11px] text-slate-400">v{{ item.version_major }}.{{ item.version_minor }}.{{ item.version_patch }}{{ item.version_suffix ? `-${item.version_suffix}` : '' }}</div>
        </div>
        <div v-if="!artifacts.length" class="text-xs text-slate-500">{{ t('noArtifacts') }}</div>
      </div>
    </div>
  </div>
</template>
