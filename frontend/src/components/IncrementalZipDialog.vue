<script setup>
import { computed } from 'vue'
import SamsungModal from './ui/SamsungModal.vue'
import SamsungButton from './ui/SamsungButton.vue'
import SamsungLoader from './ui/SamsungLoader.vue'
import { t } from '../lang/index.js'
import { goTab } from '../stores/nav.js'
import {
  formatBytes,
  formatDateTime,
  incrementalBase,
  incrementalBases,
  incrementalBusy,
  incrementalForJob,
  incrementalLoading,
  incrementalMode,
  queueIncrementalZip,
  selectJob
} from '../stores/app.js'

const targetLabel = computed(() => incrementalForJob.value?.target || '')

async function submit() {
  const created = await queueIncrementalZip()
  if (!created) return
  selectJob(created)
  goTab('logs')
}
</script>

<template>
  <SamsungModal
    :open="Boolean(incrementalForJob)"
    :title="incrementalMode === 'delta' ? t('deltaTitle') : t('incrementalTitle')"
    @close="incrementalForJob = null"
  >
    <p class="text-[14px] text-un1ca-muted">
      {{ incrementalMode === 'delta' ? t('deltaHint') : t('incrementalHint') }}
    </p>
    <p class="section-kicker mt-3">{{ t('target') }}: {{ targetLabel }}</p>

    <div v-if="incrementalLoading" class="loading-block"><SamsungLoader /></div>
    <p v-else-if="!incrementalBases.length" class="form-hint mt-3">{{ t('noIncrementalBases') }}</p>
    <div v-else class="form-section mt-3">
      <label v-for="base in incrementalBases" :key="base.job_id" class="form-row cursor-pointer">
        <span class="min-w-0">
          <span class="form-label block truncate">{{ base.name }}</span>
          <span class="form-hint block">{{ formatBytes(base.size) }} - {{ formatDateTime(base.finished_at) }}</span>
        </span>
        <input
          type="radio"
          name="incremental-base"
          class="accent-un1ca-accent"
          :value="base.job_id"
          :checked="incrementalBase === base.job_id"
          @change="incrementalBase = base.job_id"
        />
      </label>
    </div>

    <template #actions>
      <SamsungButton @click="incrementalForJob = null">{{ t('cancel') }}</SamsungButton>
      <SamsungButton variant="primary" :loading="incrementalBusy" :disabled="!incrementalBase" @click="submit">
        {{ t('startBuild') }}
      </SamsungButton>
    </template>
  </SamsungModal>
</template>
