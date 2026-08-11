<script setup>
import { onMounted } from 'vue'
import { Download, GitCompare, Layers, PackageOpen, RefreshCw, Trash2 } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import { t } from '../lang/index.js'
import { downloadUrl } from '../stores/api.js'
import { openOverlay } from '../stores/nav.js'
import { openLocalUpdate } from '../stores/localupdate.js'
import {
  artifacts,
  capabilities,
  artifactsLoading,
  fetchArtifacts,
  formatBytes,
  formatDateTime,
  openDeleteArtifactModal,
  openDeltaModal,
  openIncrementalModal,
  queueDsuPackage,
  target
} from '../stores/app.js'

function startLocalUpdate(item) {
  openLocalUpdate(item)
  openOverlay('localUpdate')
}

onMounted(fetchArtifacts)
</script>

<template>
  <OverlayView :title="t('artifactsHistory')">
    <p class="page-subtitle">{{ target ? `${t('target')}: ${target}` : t('allDevices') }}</p>

    <div v-if="artifactsLoading" class="loading-block"><SamsungLoader /></div>
    <div v-else-if="!artifacts.length" class="empty-state">{{ t('noArtifacts') }}</div>

    <div v-else class="list">
      <article v-for="item in artifacts" :key="item.job_id" class="list-row">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <p class="list-row-title">
              {{ item.target }} - v{{ item.version_major }}.{{ item.version_minor }}.{{ item.version_patch
              }}{{ item.version_suffix ? `-${item.version_suffix}` : '' }}
            </p>
            <p class="list-row-meta font-mono">{{ item.job_id }}</p>
            <p class="list-row-meta">{{ formatBytes(item.size_bytes) }} - {{ formatDateTime(item.finished_at) }}</p>
            <p v-if="item.target_files_exists" class="list-row-meta">
              target-files: {{ formatBytes(item.target_files_size) }}
            </p>
          </div>
          <StatusPill v-if="!item.exists" tone="danger" :dot="false">{{ t('artifactMissing') }}</StatusPill>
        </div>
        <div class="mt-3 flex flex-wrap gap-2">
          <a v-if="item.exists" class="chip-button is-success" :href="downloadUrl(`/jobs/${item.job_id}/artifact`)">
            <Download :size="14" /> {{ t('downloadZip') }}
          </a>
          <button
            v-if="item.target_files_exists"
            type="button"
            class="chip-button is-accent"
            @click="openIncrementalModal({ id: item.job_id, target: item.target })"
          >
            <Layers :size="14" /> {{ t('incrementalZip') }}
          </button>
          <button
            v-if="capabilities.delta_zstd && item.target_files_exists"
            type="button"
            class="chip-button is-info"
            @click="openDeltaModal(item)"
          >
            <GitCompare :size="14" /> {{ t('deltaPatch') }}
          </button>
          <button v-if="item.exists" type="button" class="chip-button is-info" @click="startLocalUpdate(item)">
            <RefreshCw :size="14" /> {{ t('localUpdateChip') }}
          </button>
          <button
            v-if="capabilities.dsu_package && item.target_files_exists"
            type="button"
            class="chip-button is-accent"
            @click="queueDsuPackage(item)"
          >
            <PackageOpen :size="14" /> {{ t('dsuPackage') }}
          </button>
          <button
            v-if="item.exists || item.target_files_exists"
            type="button"
            class="chip-button is-danger"
            @click="openDeleteArtifactModal(item)"
          >
            <Trash2 :size="14" /> {{ t('delete') }}
          </button>
        </div>
      </article>
    </div>
  </OverlayView>
</template>
