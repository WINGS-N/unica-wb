<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import { formatBytes, formatDuration, formatSpeed, progressPct } from '../../stores/app.js'
import { t } from '../../lang/index.js'

const props = defineProps({
  progress: { type: Object, default: null },
  title: { type: String, default: '' },
  stoppable: { type: Boolean, default: false }
})

const emit = defineEmits(['stop'])

const status = computed(() => String(props.progress?.status || ''))
const pct = computed(() => progressPct(props.progress))

// A bar only claims a number when the backend actually measured one. Otherwise
// it says "working" with a sliding band rather than inventing a percentage
const indeterminate = computed(
  () => status.value === 'running' && (props.progress?.indeterminate === true || pct.value <= 0)
)

const fillClass = computed(() => {
  if (status.value === 'completed') return 'is-success'
  if (status.value === 'failed' || status.value === 'canceled') return 'is-danger'
  return ''
})

const label = computed(() => {
  if (status.value === 'completed') return t('progressDone')
  if (status.value === 'failed') return t('progressFailed')
  if (status.value === 'canceled') return t('progressCanceled')
  return indeterminate.value ? t('progressWorking') : `${pct.value}%`
})

const heading = computed(() => props.title || props.progress?.title || props.progress?.stage || '')

// The server sends elapsed and eta with a progress event, and between events a
// quiet download would leave both frozen. Counting locally from the last update
// keeps them moving without asking the server for anything
const receivedAt = ref(Date.now())
const now = ref(Date.now())
let ticker = null

watch(
  () => props.progress?.elapsed_sec,
  () => {
    receivedAt.value = Date.now()
    now.value = Date.now()
  }
)

watch(
  () => status.value === 'running',
  (live) => {
    clearInterval(ticker)
    ticker = live ? setInterval(() => (now.value = Date.now()), 1000) : null
  },
  { immediate: true }
)

onUnmounted(() => clearInterval(ticker))

const sinceUpdate = computed(() => Math.max(0, Math.floor((now.value - receivedAt.value) / 1000)))

const elapsedSec = computed(() => {
  const base = Number(props.progress?.elapsed_sec ?? 0)
  return status.value === 'running' ? base + sinceUpdate.value : base
})

const etaSec = computed(() => {
  const base = Number(props.progress?.eta_sec ?? 0)
  if (!base) return 0
  return status.value === 'running' ? Math.max(0, base - sinceUpdate.value) : base
})

const hasMeta = computed(
  () =>
    status.value === 'running' &&
    (props.progress?.speed_bps || props.progress?.elapsed_sec || props.progress?.eta_sec || props.progress?.total_bytes)
)
</script>

<template>
  <div v-if="progress">
    <div class="progress-row">
      <span class="min-w-0 truncate">{{ heading }}</span>
      <span class="flex shrink-0 items-center gap-2">
        <span>{{ label }}</span>
        <button
          v-if="stoppable && status === 'running' && progress.job_id"
          type="button"
          class="icon-button is-danger h-6 w-6"
          :title="t('stop')"
          @click.stop="emit('stop', progress)"
        >
          <X :size="13" />
        </button>
      </span>
    </div>
    <div class="progress-track" :class="{ 'is-indeterminate': indeterminate }">
      <div class="progress-fill" :class="fillClass" :style="{ width: `${indeterminate ? 38 : pct}%` }" />
    </div>
    <div v-if="hasMeta" class="progress-meta">
      <span v-if="progress.total_bytes">
        {{ formatBytes(progress.downloaded_bytes) }} / {{ formatBytes(progress.total_bytes) }}
      </span>
      <span v-if="progress.speed_bps">{{ t('speedLabel') }}: {{ formatSpeed(progress.speed_bps) }}</span>
      <span>{{ t('elapsedLabel') }}: {{ formatDuration(elapsedSec) }}</span>
      <span v-if="etaSec">{{ t('etaLabel') }}: {{ formatDuration(etaSec) }}</span>
    </div>
    <div v-if="progress.message && status === 'running'" class="mt-1 truncate font-mono text-[11px] text-un1ca-muted">
      {{ progress.message }}
    </div>
  </div>
</template>
