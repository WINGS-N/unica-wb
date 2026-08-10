<script setup>
import { computed } from 'vue'
import SamsungModal from './ui/SamsungModal.vue'
import SamsungButton from './ui/SamsungButton.vue'
import OneuiCheckbox from './ui/OneuiCheckbox.vue'
import { t } from '../lang/index.js'
import {
  deleteArtifactBusy,
  deleteArtifactConfirmed,
  deleteArtifactJob,
  deleteArtifactPick,
  formatBytes
} from '../stores/app.js'

const nothingPicked = computed(() => !deleteArtifactPick.value.rom && !deleteArtifactPick.value.targetFiles)

function pick(name, value) {
  deleteArtifactPick.value = { ...deleteArtifactPick.value, [name]: value }
}
</script>

<template>
  <SamsungModal :open="Boolean(deleteArtifactJob)" :title="t('deleteArtifactTitle')" @close="deleteArtifactJob = null">
    <p class="text-[14px] text-un1ca-muted">{{ t('deleteArtifactMessage') }}</p>

    <div class="form-section mt-4">
      <div v-if="deleteArtifactJob?.hasRom" class="form-row">
        <span class="min-w-0">
          <span class="form-label block">{{ t('flashableZip') }}</span>
          <span v-if="deleteArtifactJob.romSize" class="form-hint block">{{
            formatBytes(deleteArtifactJob.romSize)
          }}</span>
        </span>
        <OneuiCheckbox :model-value="deleteArtifactPick.rom" @update:model-value="(v) => pick('rom', v)" />
      </div>
      <div v-if="deleteArtifactJob?.hasTargetFiles" class="form-row">
        <span class="min-w-0">
          <span class="form-label block">{{ t('targetFilesArchive') }}</span>
          <span v-if="deleteArtifactJob.targetFilesSize" class="form-hint block">{{
            formatBytes(deleteArtifactJob.targetFilesSize)
          }}</span>
        </span>
        <OneuiCheckbox
          :model-value="deleteArtifactPick.targetFiles"
          @update:model-value="(v) => pick('targetFiles', v)"
        />
      </div>
    </div>

    <p v-if="deleteArtifactPick.targetFiles" class="form-hint mt-3">{{ t('deleteTargetFilesMessage') }}</p>

    <template #actions>
      <SamsungButton @click="deleteArtifactJob = null">{{ t('cancel') }}</SamsungButton>
      <SamsungButton
        variant="danger"
        :loading="deleteArtifactBusy"
        :disabled="nothingPicked"
        @click="deleteArtifactConfirmed"
      >
        {{ t('delete') }}
      </SamsungButton>
    </template>
  </SamsungModal>
</template>
