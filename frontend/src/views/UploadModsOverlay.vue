<script setup>
import { Upload } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import { t } from '../lang/index.js'
import {
  clearUploadedMods,
  onUploadFileChanged,
  uploadBusy,
  uploadError,
  uploadFile,
  uploadModsArchive,
  uploadedMods,
  uploadedModsId
} from '../stores/app.js'

const ACCEPT = '.zip,.tar,.gz,.xz,.bz2,.zst,.tgz,.txz,.tbz2,.tar.gz,.tar.xz,.tar.zst'
</script>

<template>
  <OverlayView :title="t('uploadExtraModsTitle')">
    <SectionCard>
      <p class="page-subtitle">
        {{ t('uploadHint') }} <span class="mono-chip">module-name/module.prop</span> {{ t('oneBuildModsHint') }}
      </p>

      <label class="surface-inset flex cursor-pointer items-center gap-3">
        <Upload :size="18" class="shrink-0 text-un1ca-muted" />
        <span class="min-w-0 flex-1 truncate text-[14px]">{{ uploadFile?.name || t('chooseArchiveFirst') }}</span>
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

    <div v-if="uploadedMods.length" class="list">
      <div v-for="m in uploadedMods" :key="`${m.module_dir}-${m.id}`" class="list-row">
        <p class="list-row-title">{{ m.name || m.module_dir }}</p>
        <p class="list-row-meta font-mono">{{ m.module_dir }}</p>
        <p class="list-row-meta">
          id: {{ m.id || 'n/a' }} - ver: {{ m.version || 'n/a' }} ({{ m.versionCode || 'n/a' }})
        </p>
        <p class="list-row-meta">{{ m.author || 'n/a' }}</p>
        <p v-if="m.description" class="list-row-meta">{{ m.description }}</p>
      </div>
    </div>
  </OverlayView>
</template>
