<script setup>
defineProps({
  t: { type: Function, required: true },
  logTailKb: { type: Number, required: true },
  followLogs: { type: Boolean, required: true },
  selectedJob: { type: Object, default: null },
  logs: { type: String, required: true },
  logsPlaceholder: { type: String, required: true },
  apiBase: { type: String, required: true },
  apiPrefix: { type: String, required: true },
  authToken: { type: String, required: true }
})

const emit = defineEmits(['update:logTailKb', 'update:followLogs', 'log-tail-change', 'open-hints'])
</script>

<template>
  <div class="rounded-2xl border border-slate-800 bg-black/50 p-4 sm:p-6 lg:col-span-3">
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-xl font-semibold">{{ t('logs') }}</h2>
      <div class="flex items-center gap-2">
        <label class="text-xs text-slate-300">{{ t('tailKb') }}</label>
        <select
          :value="logTailKb"
          class="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100"
          @change="$emit('update:logTailKb', Number($event.target.value)); $emit('log-tail-change')"
        >
          <option :value="64">64</option>
          <option :value="128">128</option>
          <option :value="256">256</option>
          <option :value="512">512</option>
          <option :value="1024">1024</option>
        </select>
        <button
          type="button"
          class="rounded-lg border px-2 py-1 text-xs font-medium"
          :class="followLogs ? 'border-emerald-600 bg-emerald-500/20 text-emerald-200' : 'border-slate-700 bg-slate-900 text-slate-300'"
          @click="$emit('update:followLogs', !followLogs)"
        >
          {{ t('followLogs') }}
        </button>
        <button
          v-if="selectedJob?.status === 'failed'"
          class="rounded-lg border border-red-500/60 bg-red-500/20 px-2 py-1 text-xs font-semibold text-red-200 hover:bg-red-500/30"
          @click="$emit('open-hints', selectedJob, $event)"
        >
          {{ t('whyBuildFailed') }}
        </button>
        <a v-if="selectedJob?.artifact_path" :href="`${apiBase}${apiPrefix}/jobs/${selectedJob.id}/artifact${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`" class="rounded-lg bg-emerald-500 px-3 py-1 text-sm font-medium text-slate-950 hover:bg-emerald-400">{{ t('downloadZip') }}</a>
      </div>
    </div>
    <pre id="logs" class="h-[45vh] overflow-auto rounded-xl border border-slate-800 bg-black p-3 text-xs leading-5 text-emerald-300">{{ logs || logsPlaceholder }}</pre>
  </div>
</template>
