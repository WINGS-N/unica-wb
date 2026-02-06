<script setup>
defineProps({
  t: { type: Function, required: true },
  defaultsLoading: { type: Boolean, required: true },
  repoSyncClass: { type: String, required: true },
  repoSyncText: { type: String, required: true },
  currentCommitDetails: { type: Object, required: true },
  currentCommit: { type: String, required: true },
  currentCommitSubject: { type: String, required: true },
  firmwareStatus: { type: Object, required: true },
  targetFirmwareStatus: { type: Object, required: true },
  target: { type: String, required: true },
  language: { type: String, required: true },
  firmwareStatusToneClass: { type: Function, required: true },
  normalizeModelForImage: { type: Function, required: true },
  deviceImageSvgData: { type: Function, required: true },
  firmwareProgressForStatus: { type: Function, required: true },
  progressTitle: { type: Function, required: true },
  progressPct: { type: Function, required: true },
  progressBarWidth: { type: Function, required: true },
  formatSpeed: { type: Function, required: true },
  formatDuration: { type: Function, required: true }
})

const emit = defineEmits(['open-commit', 'open-samsung-fw', 'stop-progress', 'set-language', 'open-settings'])
</script>

<template>
  <div class="mx-auto mb-3 grid max-w-7xl grid-cols-1 gap-3 lg:grid-cols-4">
    <button class="rounded-xl border px-3 py-2 text-left transition hover:bg-slate-800/60" :class="repoSyncClass" @click="$emit('open-commit')">
      <div class="flex items-center gap-2 text-[10px] uppercase tracking-wide text-slate-400">
        <span>{{ t('currentCommit') }}</span>
        <span v-if="defaultsLoading" class="h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-cyan-400" />
      </div>
      <div class="mt-0.5 text-[11px] text-slate-300">{{ repoSyncText }}</div>
      <div class="mt-0.5 text-[11px] text-slate-400">{{ t('branchLabel') }}: {{ currentCommitDetails.branch || 'n/a' }}</div>
      <div class="mt-0.5 font-mono text-xs text-cyan-300">{{ currentCommit }}</div>
      <div v-if="currentCommitSubject" class="truncate text-xs text-slate-300">{{ currentCommitSubject }}</div>
    </button>

    <button class="flex items-center gap-3 rounded-xl border px-3 py-2 text-left transition hover:bg-slate-800/60" :class="firmwareStatusToneClass(firmwareStatus)" @click="$emit('open-samsung-fw')">
      <img
        :src="`/devices/${normalizeModelForImage(firmwareStatus.source_model)}.png`"
        alt="source device"
        class="h-14 w-14 rounded-lg border border-slate-700 bg-slate-900 object-cover"
        @error="(e) => { e.target.src = deviceImageSvgData(firmwareStatus.source_model || target) }"
      />
      <div class="min-w-0">
        <div class="text-[10px] uppercase tracking-wide text-slate-300">{{ t('sourceFirmwareStatus') }}</div>
        <div v-if="defaultsLoading" class="mt-1 flex items-center gap-2 text-xs text-slate-300">
          <span class="h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-cyan-400" />
          <span>{{ t('loading') }}</span>
        </div>
        <template v-else>
          <div class="truncate text-xs text-slate-200">{{ firmwareStatus.source_model }}<span v-if="firmwareStatus.source_csc">/{{ firmwareStatus.source_csc }}</span></div>
          <div class="truncate text-[11px] text-slate-300">{{ t('latestVersion') }}: {{ firmwareStatus.latest_version || 'n/a' }}</div>
          <div class="truncate text-[11px] text-slate-300">{{ t('downloadedVersion') }}: {{ firmwareStatus.downloaded_version || firmwareStatus.extracted_version || 'n/a' }}</div>
          <div v-if="firmwareProgressForStatus(firmwareStatus)?.status === 'running'" class="mt-1">
            <div class="mb-1 flex items-center justify-between gap-2 text-[10px] text-cyan-300">
              <span>{{ progressTitle(firmwareProgressForStatus(firmwareStatus)) }}: {{ progressPct(firmwareProgressForStatus(firmwareStatus)) }}%</span>
              <button class="rounded border border-red-400/60 bg-red-500/20 px-1.5 py-0 text-[10px] font-semibold text-red-300 hover:bg-red-500/30" @click.stop="$emit('stop-progress', firmwareProgressForStatus(firmwareStatus), $event)">✕</button>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-slate-700"><div class="h-full bg-cyan-400 transition-all duration-200" :style="{ width: `${progressBarWidth(firmwareProgressForStatus(firmwareStatus))}%` }" /></div>
            <div class="mt-1 text-[10px] text-slate-300">{{ t('speedLabel') }}: {{ formatSpeed(firmwareProgressForStatus(firmwareStatus)?.speed_bps) }} • {{ t('elapsedLabel') }}: {{ formatDuration(firmwareProgressForStatus(firmwareStatus)?.elapsed_sec) }} • {{ t('etaLabel') }}: {{ formatDuration(firmwareProgressForStatus(firmwareStatus)?.eta_sec) }}</div>
          </div>
        </template>
      </div>
    </button>

    <button class="flex items-center gap-3 rounded-xl border px-3 py-2 text-left transition hover:bg-slate-800/60" :class="firmwareStatusToneClass(targetFirmwareStatus)" @click="$emit('open-samsung-fw')">
      <img :src="`/devices/${normalizeModelForImage(targetFirmwareStatus.source_model)}.png`" alt="target device" class="h-14 w-14 rounded-lg border border-slate-700 bg-slate-900 object-cover" @error="(e) => { e.target.src = deviceImageSvgData(targetFirmwareStatus.source_model || target) }" />
      <div class="min-w-0">
        <div class="text-[10px] uppercase tracking-wide text-slate-300">{{ t('targetFirmwareStatus') }}</div>
        <div v-if="defaultsLoading" class="mt-1 flex items-center gap-2 text-xs text-slate-300"><span class="h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-cyan-400" /><span>{{ t('loading') }}</span></div>
        <template v-else>
          <div class="truncate text-xs text-slate-200">{{ targetFirmwareStatus.source_model }}<span v-if="targetFirmwareStatus.source_csc">/{{ targetFirmwareStatus.source_csc }}</span></div>
          <div class="truncate text-[11px] text-slate-300">{{ t('latestVersion') }}: {{ targetFirmwareStatus.latest_version || 'n/a' }}</div>
          <div class="truncate text-[11px] text-slate-300">{{ t('downloadedVersion') }}: {{ targetFirmwareStatus.downloaded_version || targetFirmwareStatus.extracted_version || 'n/a' }}</div>
          <div v-if="firmwareProgressForStatus(targetFirmwareStatus)?.status === 'running'" class="mt-1">
            <div class="mb-1 flex items-center justify-between gap-2 text-[10px] text-cyan-300">
              <span>{{ progressTitle(firmwareProgressForStatus(targetFirmwareStatus)) }}: {{ progressPct(firmwareProgressForStatus(targetFirmwareStatus)) }}%</span>
              <button class="rounded border border-red-400/60 bg-red-500/20 px-1.5 py-0 text-[10px] font-semibold text-red-300 hover:bg-red-500/30" @click.stop="$emit('stop-progress', firmwareProgressForStatus(targetFirmwareStatus), $event)">✕</button>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-slate-700"><div class="h-full bg-cyan-400 transition-all duration-200" :style="{ width: `${progressBarWidth(firmwareProgressForStatus(targetFirmwareStatus))}%` }" /></div>
            <div class="mt-1 text-[10px] text-slate-300">{{ t('speedLabel') }}: {{ formatSpeed(firmwareProgressForStatus(targetFirmwareStatus)?.speed_bps) }} • {{ t('elapsedLabel') }}: {{ formatDuration(firmwareProgressForStatus(targetFirmwareStatus)?.elapsed_sec) }} • {{ t('etaLabel') }}: {{ formatDuration(firmwareProgressForStatus(targetFirmwareStatus)?.eta_sec) }}</div>
          </div>
        </template>
      </div>
    </button>

    <div class="flex items-start justify-end gap-2">
      <button class="rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-200 hover:bg-slate-800/70" @click="$emit('open-settings')">
        {{ t('settings') }}
      </button>
      <div class="flex shrink-0 items-center">
        <label class="mr-2 self-center text-xs text-slate-300">{{ t('language') }}</label>
        <select :value="language" class="rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm" @change="$emit('set-language', $event.target.value)">
          <option value="en">🇺🇸 English</option>
          <option value="ru">🇷🇺 Русский</option>
        </select>
      </div>
    </div>
  </div>
</template>
