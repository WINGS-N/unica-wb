<script setup>
import SamsungModal from './ui/SamsungModal.vue'
import SamsungButton from './ui/SamsungButton.vue'
import { t } from '../lang/index.js'
import { stopJobConfirmed, stopModalJob, stopSignalType } from '../stores/app.js'

const SIGNALS = [
  { value: 'sigterm', labelKey: 'sigtermLabel' },
  { value: 'sigkill', labelKey: 'sigkillLabel' }
]
</script>

<template>
  <SamsungModal :open="Boolean(stopModalJob)" :title="t('stopBuildTitle')" @close="stopModalJob = null">
    <p class="text-[14px] text-un1ca-muted">
      {{ t('willBeCanceled') }} <span class="mono-chip">{{ stopModalJob?.id }}</span>
    </p>
    <div class="form-section mt-4">
      <p class="section-kicker mb-2">{{ t('stopSignal') }}</p>
      <label v-for="sig in SIGNALS" :key="sig.value" class="form-row cursor-pointer">
        <span class="form-label">{{ t(sig.labelKey) }}</span>
        <input
          type="radio"
          name="stop-signal"
          class="accent-un1ca-accent"
          :value="sig.value"
          :checked="stopSignalType === sig.value"
          @change="stopSignalType = sig.value"
        />
      </label>
    </div>
    <template #actions>
      <SamsungButton @click="stopModalJob = null">{{ t('keepRunning') }}</SamsungButton>
      <SamsungButton variant="danger" @click="stopJobConfirmed">{{ t('stopJob') }}</SamsungButton>
    </template>
  </SamsungModal>
</template>
