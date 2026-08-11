<script setup>
import { computed } from 'vue'
import { Download, Upload } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import { t } from '../lang/index.js'
import { formatBytes } from '../stores/app.js'
import {
  localUpdateBlocks,
  localUpdateBusy,
  localUpdateBytes,
  localUpdateError,
  localUpdateFile,
  localUpdatePercent,
  localUpdatePhase,
  localUpdateResult,
  localUpdateRow,
  runLocalUpdate,
  setLocalUpdateFile
} from '../stores/localupdate.js'

const phaseLabel = computed(() => {
  const map = {
    hashing: t('localUpdateHashing'),
    fetching: t('localUpdateFetching'),
    writing: t('localUpdateWriting'),
    done: t('localUpdateDone'),
    error: t('localUpdateFailed')
  }
  return map[localUpdatePhase.value] || ''
})

const saved = computed(() => formatBytes(Math.max(0, localUpdateBytes.value.total - localUpdateBytes.value.fetched)))

function onFileChanged(event) {
  setLocalUpdateFile(event.target.files?.[0] || null)
}
</script>

<template>
  <OverlayView :title="t('localUpdateTitle')">
    <SectionCard>
      <p class="page-subtitle">{{ t('localUpdateHint') }}</p>
      <p v-if="localUpdateRow" class="list-row-meta font-mono">{{ localUpdateRow.target }}</p>

      <label class="dropzone mt-3">
        <Upload :size="22" class="shrink-0 text-un1ca-muted" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[15px] font-bold">{{ localUpdateFile?.name || t('localUpdatePick') }}</span>
          <span class="block truncate text-[13px] text-un1ca-muted">{{
            localUpdateFile ? formatBytes(localUpdateFile.size) : t('localUpdatePickHint')
          }}</span>
        </span>
        <input type="file" class="hidden" @change="onFileChanged" />
        <span class="chip-button shrink-0">{{ t('browse') }}</span>
      </label>

      <div class="actions-row">
        <SamsungButton
          variant="primary"
          :loading="localUpdateBusy"
          :disabled="!localUpdateFile"
          @click="runLocalUpdate"
        >
          {{ t('localUpdateStart') }}
        </SamsungButton>
      </div>
    </SectionCard>

    <SectionCard v-if="localUpdatePhase !== 'idle'" :title="phaseLabel">
      <div class="progress-track">
        <div
          class="progress-fill"
          :class="{ 'is-success': localUpdatePhase === 'done' }"
          :style="{ width: `${localUpdatePercent}%` }"
        />
      </div>
      <div class="keyvals mt-3">
        <div class="keyval">
          <span class="keyval-label">{{ t('localUpdateBlocks') }}</span>
          <span class="keyval-value">{{ localUpdateBlocks.done }} / {{ localUpdateBlocks.total }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('localUpdateReused') }}</span>
          <span class="keyval-value">{{ localUpdateBlocks.reused }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('localUpdateDownloaded') }}</span>
          <span class="keyval-value">{{ formatBytes(localUpdateBytes.fetched) }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('localUpdateSaved') }}</span>
          <span class="keyval-value">{{ saved }}</span>
        </div>
      </div>

      <p v-if="localUpdateError" class="state-error mt-3">{{ localUpdateError }}</p>

      <a
        v-if="localUpdateResult?.url"
        class="chip-button is-success mt-3"
        :href="localUpdateResult.url"
        :download="localUpdateResult.name"
      >
        <Download :size="14" /> {{ t('localUpdateSave') }}
      </a>
    </SectionCard>
  </OverlayView>
</template>
