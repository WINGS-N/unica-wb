<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { CircleHelp, Download } from 'lucide-vue-next'
import OneuiSelect from '../components/ui/OneuiSelect.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import { t } from '../lang/index.js'
import { downloadUrl } from '../stores/api.js'
import { openOverlay } from '../stores/nav.js'
import {
  attachLogs,
  buildProgress,
  detachLogs,
  followLogs,
  jobTitle,
  logTailKb,
  logs,
  logsPlaceholder,
  scrollLogsToBottom,
  selectedJob,
  setFollowLogs,
  setLogTailKb
} from '../stores/app.js'

const tailOptions = [64, 128, 256, 512, 1024].map((x) => ({ value: x, label: `${x} KB` }))

// The feed runs only while this screen is on. Opening a log means wanting its
// end, and so does switching to another job
onMounted(() => {
  attachLogs()
  scrollLogsToBottom()
})
onUnmounted(detachLogs)
watch(() => selectedJob.value?.id, scrollLogsToBottom)
watch(followLogs, (on) => {
  if (on) scrollLogsToBottom()
})

function openHints() {
  if (!selectedJob.value) return
  openOverlay('hints', { jobId: selectedJob.value.id })
}
</script>

<template>
  <div class="page flex h-full flex-col">
    <header class="page-head">
      <div class="min-w-0">
        <p class="section-kicker">{{ t('logs') }}</p>
        <h1 class="page-title truncate">{{ selectedJob ? jobTitle(selectedJob) : t('noJobSelected') }}</h1>
        <p v-if="selectedJob" class="page-subtitle font-mono">{{ selectedJob.id }}</p>
      </div>
      <StatusPill v-if="selectedJob" :status="selectedJob.status" />
    </header>

    <ProgressBar
      v-if="selectedJob && buildProgress[selectedJob.id]"
      :progress="buildProgress[selectedJob.id]"
      :title="t(`buildStage_${buildProgress[selectedJob.id]?.stage}`)"
    />

    <div class="flex flex-wrap items-center gap-2">
      <OneuiSelect :model-value="logTailKb" :options="tailOptions" :label="t('tailKb')" @change="setLogTailKb" />
      <button
        type="button"
        class="chip-button self-end"
        :class="{ 'is-active': followLogs }"
        @click="setFollowLogs(!followLogs)"
      >
        {{ t('followLogs') }}
      </button>
      <button v-if="selectedJob?.status === 'failed'" type="button" class="chip-button self-end" @click="openHints">
        <CircleHelp :size="14" /> {{ t('whyBuildFailed') }}
      </button>
      <a
        v-if="selectedJob?.artifact_path"
        class="chip-button self-end"
        :href="downloadUrl(`/jobs/${selectedJob.id}/artifact`)"
      >
        <Download :size="14" /> {{ t('downloadZip') }}
      </a>
    </div>

    <pre id="logs" class="log-pane min-h-[40vh]">{{ logs || logsPlaceholder() }}</pre>
  </div>
</template>
