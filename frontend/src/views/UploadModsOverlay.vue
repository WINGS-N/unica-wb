<script setup>
import { computed, ref } from 'vue'
import { Upload } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import { t } from '../lang/index.js'
import {
  clearUploadedMods,
  onUploadFileChanged,
  setUploadFile,
  toggleUploadedMod,
  uploadBusy,
  uploadError,
  uploadFile,
  uploadModsArchive,
  uploadedMods,
  uploadedModsDisabled,
  uploadedModsId
} from '../stores/app.js'

const ACCEPT = '.zip,.tar,.gz,.xz,.bz2,.zst,.tgz,.txz,.tbz2,.tar.gz,.tar.xz,.tar.zst'

const dragging = ref(false)
const disabledSet = computed(() => new Set(uploadedModsDisabled.value))
const enabledCount = computed(() => uploadedMods.value.length - uploadedModsDisabled.value.length)

// A drag that leaves for a child element still fires dragleave on the zone, so
// the highlight is counted rather than toggled
let dragDepth = 0

function onDragEnter() {
  dragDepth += 1
  dragging.value = true
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}

function onDrop(event) {
  dragDepth = 0
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) setUploadFile(file)
}
</script>

<template>
  <OverlayView :title="t('uploadExtraModsTitle')">
    <SectionCard>
      <p class="page-subtitle">
        {{ t('uploadHint') }} <span class="mono-chip">module-name/module.prop</span> {{ t('oneBuildModsHint') }}
      </p>

      <label
        class="dropzone"
        :class="{ 'is-dragging': dragging }"
        @dragenter.prevent="onDragEnter"
        @dragover.prevent
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
      >
        <Upload :size="22" class="shrink-0 text-un1ca-muted" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[15px] font-bold">{{ uploadFile?.name || t('dropArchiveHere') }}</span>
          <span class="block truncate text-[13px] text-un1ca-muted">{{
            uploadFile ? t('archiveReady') : t('dropArchiveHint')
          }}</span>
        </span>
        <input type="file" class="hidden" :accept="ACCEPT" @change="onUploadFileChanged" />
        <span class="chip-button shrink-0">{{ t('browse') }}</span>
      </label>

      <p v-if="uploadError" class="state-error">{{ uploadError }}</p>

      <div class="actions-row">
        <SamsungButton variant="primary" :loading="uploadBusy" :disabled="!uploadFile" @click="uploadModsArchive">
          {{ uploadBusy ? t('uploading') : t('uploadValidate') }}
        </SamsungButton>
        <SamsungButton v-if="uploadedModsId" @click="clearUploadedMods">{{ t('clear') }}</SamsungButton>
      </div>
    </SectionCard>

    <template v-if="uploadedMods.length">
      <p class="section-kicker">{{ t('modsEnabledShort') }}: {{ enabledCount }} / {{ uploadedMods.length }}</p>

      <div class="list">
        <div
          v-for="m in uploadedMods"
          :key="`${m.module_dir}-${m.id}`"
          class="list-row flex items-center gap-4"
          :class="{ 'is-off': disabledSet.has(m.module_dir) }"
        >
          <div class="min-w-0 flex-1">
            <p class="list-row-title">{{ m.name || m.module_dir }}</p>
            <p class="list-row-meta wrap-anywhere font-mono">{{ m.module_dir }}</p>
            <p class="list-row-meta">
              id: {{ m.id || 'n/a' }} - ver: {{ m.version || 'n/a' }} ({{ m.versionCode || 'n/a' }})
            </p>
            <p v-if="m.author" class="list-row-meta">{{ m.author }}</p>
            <p v-if="m.description" class="list-row-meta wrap-anywhere">{{ m.description }}</p>
          </div>
          <OneuiSwitch
            :model-value="!disabledSet.has(m.module_dir)"
            @update:model-value="toggleUploadedMod(m.module_dir)"
          />
        </div>
      </div>
    </template>
  </OverlayView>
</template>
