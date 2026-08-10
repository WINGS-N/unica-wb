<script setup>
import { computed } from 'vue'
import {
  Archive,
  ChevronRight,
  Download,
  GitBranch,
  Hammer,
  ListChecks,
  PackagePlus,
  Sparkles,
  Trash2
} from 'lucide-vue-next'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import OneuiSelect from '../components/ui/OneuiSelect.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import { goTab, openOverlay } from '../stores/nav.js'
import { t } from '../lang/index.js'
import { downloadUrl } from '../stores/api.js'
import {
  changeTarget,
  clearUploadedMods,
  currentCommit,
  currentCommitSubject,
  currentCommitDetails,
  debloatAddedCount,
  debloatDisabledIds,
  defaultsLoading,
  firmwareDownloadBusyKind,
  firmwareStatusLabel,
  firmwareStatusLoading,
  repoInfoLoading,
  targetsLoading,
  deviceImageSvgData,
  ffOverridesCount,
  firmwarePhaseLabel,
  firmwareProgressForStatus,
  downloadSamsungFw,
  firmwareStatus,
  firmwareStatusTone,
  force,
  latestArtifactAvailable,
  loading,
  modsDisabledIds,
  noRomZip,
  normalizeModelForImage,
  openStopModalForProgress,
  repoSyncText,
  repoSyncTone,
  activeRepoProgress,
  sourceFirmware,
  submitJob,
  target,
  targetFirmware,
  targetFirmwareStatus,
  targetOptions,
  uploadedMods,
  uploadedModsId,
  versionMajor,
  versionMinor,
  versionPatch,
  versionSuffix
} from '../stores/app.js'

const targetSelectOptions = computed(() =>
  targetOptions.value.map((item) => ({ value: item.code, label: `${item.code} - ${item.name}` }))
)

const customizations = computed(() => [
  {
    key: 'mods',
    icon: ListChecks,
    label: t('modsList'),
    count: modsDisabledIds.value.length,
    countLabel: t('modsDisabledShort'),
    overlay: 'mods'
  },
  {
    key: 'debloat',
    icon: Trash2,
    label: t('debloatList'),
    count: debloatDisabledIds.value.length + debloatAddedCount.value,
    countLabel: t('debloatDisabledShort'),
    overlay: 'debloat'
  },
  {
    key: 'ff',
    icon: Sparkles,
    label: t('ffEditor'),
    count: ffOverridesCount.value,
    countLabel: t('ffOverridesForBuild'),
    overlay: 'features'
  },
  {
    key: 'upload',
    icon: PackagePlus,
    label: t('uploadMods'),
    count: uploadedMods.value.length,
    countLabel: t('extraModsReady'),
    overlay: 'modsUpload'
  }
])

function latestZipHref() {
  return downloadUrl(`/artifacts/latest/${encodeURIComponent(target.value)}`)
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="min-w-0">
        <h1 class="page-title">{{ t('appTitle') }}</h1>
        <p class="page-subtitle">{{ t('queueTitle') }}</p>
      </div>
    </header>

    <!-- Firmware + repo state, the three things that decide whether a build can run -->
    <div class="grid gap-4 md:grid-cols-2">
      <div
        v-for="card in [
          { key: 'source', label: t('sourceFirmwareStatus'), status: firmwareStatus },
          { key: 'target', label: t('targetFirmwareStatus'), status: targetFirmwareStatus }
        ]"
        :key="card.key"
        role="button"
        tabindex="0"
        class="surface-card flex cursor-pointer items-start gap-4 text-left transition-colors hover:bg-white/[0.03]"
        @click="goTab('firmware')"
        @keydown.enter="goTab('firmware')"
      >
        <img
          :src="`/devices/${normalizeModelForImage(card.status.source_model)}.png`"
          alt=""
          class="h-14 w-14 shrink-0 rounded-2xl border border-un1ca-border bg-black object-cover"
          @error="
            (e) => {
              e.target.src = deviceImageSvgData(card.status.source_model || target)
            }
          "
        />
        <div class="min-w-0 flex-1">
          <div class="flex items-center justify-between gap-2">
            <p class="section-kicker">{{ card.label }}</p>
            <SamsungLoader v-if="firmwareStatusLoading" small />
            <StatusPill v-else :tone="firmwareStatusTone(card.status)" :dot="false">
              {{ t(firmwareStatusLabel(card.status)) }}
            </StatusPill>
          </div>
          <p class="mt-1 truncate text-[15px] font-bold">
            {{ card.status.source_model || 'n/a'
            }}<span v-if="card.status.source_csc">/{{ card.status.source_csc }}</span>
          </p>
          <p class="muted mt-0.5 truncate">{{ t('latestVersion') }}: {{ card.status.latest_version || 'n/a' }}</p>
          <p class="muted truncate">
            {{ t('downloadedVersion') }}: {{ card.status.downloaded_version || card.status.extracted_version || 'n/a' }}
          </p>
          <div
            v-if="!firmwareStatusLoading && !card.status.up_to_date && !firmwareProgressForStatus(card.status)"
            class="mt-2 flex justify-end"
          >
            <SamsungButton
              small
              :loading="firmwareDownloadBusyKind === card.key"
              @click.stop="downloadSamsungFw(card.key)"
            >
              <Download :size="14" /> {{ t('downloadFw') }}
            </SamsungButton>
          </div>
          <ProgressBar
            v-if="firmwareProgressForStatus(card.status)"
            class="mt-3"
            stoppable
            :progress="firmwareProgressForStatus(card.status)"
            :title="firmwarePhaseLabel(firmwareProgressForStatus(card.status))"
            @stop="openStopModalForProgress"
          />
        </div>
      </div>
    </div>

    <button
      type="button"
      class="surface-card flex items-center gap-4 text-left transition-colors hover:bg-white/[0.03]"
      @click="openOverlay('repo')"
    >
      <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/[0.07]">
        <GitBranch :size="20" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="flex flex-wrap items-center gap-2">
          <span class="section-kicker">{{ t('currentCommit') }}</span>
          <SamsungLoader v-if="repoInfoLoading" small />
          <StatusPill v-else :tone="repoSyncTone()" :dot="false">{{ repoSyncText() }}</StatusPill>
        </span>
        <span class="mt-1 block truncate text-[15px] font-bold">
          {{ currentCommitDetails.branch || 'n/a' }} - <span class="font-mono">{{ currentCommit }}</span>
        </span>
        <span v-if="currentCommitSubject" class="muted block truncate">{{ currentCommitSubject }}</span>
        <ProgressBar v-if="activeRepoProgress" class="mt-3" :progress="activeRepoProgress" />
      </span>
      <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
    </button>

    <SectionCard :title="t('buildParameters')" :kicker="t('build')" :loading="defaultsLoading">
      <!-- Two columns once there is room; a single stack on a phone -->
      <div class="grid gap-4 md:grid-cols-2 md:gap-x-8">
        <OneuiSelect
          block
          class="md:col-span-2"
          :label="t('target')"
          :model-value="target"
          :options="targetSelectOptions"
          @change="changeTarget"
        />
        <OneuiInput v-model="sourceFirmware" :label="t('sourceFirmware')" mono />
        <OneuiInput v-model="targetFirmware" :label="t('targetFirmware')" mono />

        <div>
          <span class="field-label">{{ t('version') }}</span>
          <div class="grid grid-cols-3 gap-3">
            <OneuiInput v-model="versionMajor" type="number" min="0" />
            <OneuiInput v-model="versionMinor" type="number" min="0" />
            <OneuiInput v-model="versionPatch" type="number" min="0" />
          </div>
        </div>
        <OneuiInput v-model="versionSuffix" :label="t('customSuffix')" :placeholder="t('optional')" />
      </div>

      <div class="grid gap-3 md:grid-cols-2">
        <div class="form-section">
          <div class="form-row">
            <div class="min-w-0">
              <p class="form-label">{{ t('forceBuild') }}</p>
              <p class="form-hint">{{ t('forceBuildHint') }}</p>
            </div>
            <OneuiSwitch v-model="force" />
          </div>
        </div>
        <div class="form-section">
          <div class="form-row">
            <div class="min-w-0">
              <p class="form-label">{{ t('skipRomZip') }}</p>
              <p class="form-hint">{{ t('skipRomZipHint') }}</p>
            </div>
            <OneuiSwitch v-model="noRomZip" />
          </div>
        </div>
      </div>

      <SamsungButton
        variant="primary"
        block
        class="md:ml-auto md:w-auto md:min-w-[220px]"
        :loading="loading"
        :disabled="!target"
        @click="submitJob"
      >
        <Hammer v-if="!loading" :size="17" />
        {{ loading ? t('submitting') : t('startBuild') }}
      </SamsungButton>
    </SectionCard>

    <SectionCard :title="t('customization')" :subtitle="t('customizationHint')">
      <div class="list">
        <button
          v-for="item in customizations"
          :key="item.key"
          type="button"
          class="list-row is-clickable flex items-center gap-3"
          @click="openOverlay(item.overlay)"
        >
          <component :is="item.icon" :size="18" class="shrink-0 text-un1ca-muted" />
          <span class="min-w-0 flex-1">
            <span class="list-row-title block">{{ item.label }}</span>
            <span v-if="item.count" class="list-row-meta block">{{ item.countLabel }}: {{ item.count }}</span>
          </span>
          <StatusPill v-if="item.count" tone="info" :dot="false">{{ item.count }}</StatusPill>
          <ChevronRight :size="16" class="shrink-0 text-un1ca-muted" />
        </button>
      </div>

      <div v-if="uploadedModsId" class="surface-inset flex items-center justify-between gap-3">
        <span class="min-w-0 text-[13px]">
          {{ t('extraModsReady') }} ({{ uploadedMods.length }}) - {{ t('nextBuildOnly') }}
        </span>
        <SamsungButton small @click="clearUploadedMods">{{ t('clear') }}</SamsungButton>
      </div>
    </SectionCard>

    <SectionCard :title="t('output')">
      <div class="actions-row">
        <a v-if="latestArtifactAvailable && target" class="button-primary action-button" :href="latestZipHref()">
          <Download :size="16" />
          {{ t('downloadLatestForTarget') }}
        </a>
        <SamsungButton v-else disabled>
          <Download :size="16" />
          {{ t('downloadLatestForTarget') }}
        </SamsungButton>
        <SamsungButton @click="openOverlay('artifacts')">
          <Archive :size="16" />
          {{ t('artifactsHistory') }}
        </SamsungButton>
      </div>
    </SectionCard>
  </div>
</template>
