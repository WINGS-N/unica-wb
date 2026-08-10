<script setup>
import { onMounted } from 'vue'
import { HardDriveDownload, RefreshCw, Trash2 } from 'lucide-vue-next'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { t } from '../lang/index.js'
import {
  activeWorkspace,
  deleteSamsungFwEntry,
  deviceImageSvgData,
  extractSamsungFwEntry,
  fetchSamsungFw,
  firmwareDeleteBusyKey,
  firmwareExtractBusyKey,
  firmwareProgressFor,
  formatBytes,
  normalizeModelForImage,
  openStopModalForProgress,
  samsungFwItems,
  samsungFwLoading,
  target
} from '../stores/app.js'

onMounted(fetchSamsungFw)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="section-kicker">{{ activeWorkspace?.name || '' }}</p>
        <h1 class="page-title">{{ t('samsungFw') }}</h1>
        <p class="page-subtitle">{{ t('samsungFwHint') }}</p>
      </div>
      <SamsungButton small :loading="samsungFwLoading" @click="fetchSamsungFw">
        <RefreshCw v-if="!samsungFwLoading" :size="15" />
        {{ t('refresh') }}
      </SamsungButton>
    </header>

    <div class="surface-inset">
      <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p class="section-kicker">{{ t('firmwareCacheMode') }}</p>
        <StatusPill :tone="activeWorkspace?.shared_fw_cache ? 'info' : ''" :dot="false">
          {{ activeWorkspace?.shared_fw_cache ? t('sharedCacheOn') : t('sharedCacheOff') }}
        </StatusPill>
      </div>
      <p class="form-hint mt-2">
        {{ activeWorkspace?.shared_fw_cache ? t('sharedCacheOnHint') : t('sharedCacheOffHint') }}
      </p>
      <div class="keyvals mt-3">
        <div class="keyval">
          <span class="keyval-label">{{ t('cacheLocation') }}</span>
          <span class="keyval-value mono wrap-anywhere">{{ activeWorkspace?.out_path || 'n/a' }}</span>
        </div>
      </div>
    </div>

    <div v-if="samsungFwLoading && !samsungFwItems.length" class="loading-block"><SamsungLoader /></div>

    <div v-else-if="!samsungFwItems.length" class="empty-state">{{ t('samsungFwEmpty') }}</div>

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <SectionCard v-for="item in samsungFwItems" :key="item.key">
        <div class="flex items-start gap-4">
          <img
            :src="`/devices/${normalizeModelForImage(item.model)}.png`"
            alt=""
            class="h-14 w-14 shrink-0 rounded-2xl border border-un1ca-border bg-black object-cover"
            @error="
              (e) => {
                e.target.src = deviceImageSvgData(item.model || target)
              }
            "
          />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h2 class="card-title truncate">
                {{ item.model }}<span v-if="item.csc"> / {{ item.csc }}</span>
              </h2>
              <StatusPill v-if="item.update_available" tone="warning" :dot="false">{{
                t('updateAvailable')
              }}</StatusPill>
            </div>
            <p class="muted wrap-anywhere mt-1">{{ t('latestVersion') }}: {{ item.latest_version || 'n/a' }}</p>
          </div>
        </div>

        <ProgressBar
          v-if="firmwareProgressFor(item.key)"
          stoppable
          :progress="firmwareProgressFor(item.key)"
          :title="
            firmwareProgressFor(item.key)?.phase === 'extract' ? t('extractProgressLabel') : t('downloadProgressLabel')
          "
          @stop="openStopModalForProgress"
        />

        <div class="grid gap-3 sm:grid-cols-2">
          <div class="form-section">
            <p class="section-kicker">ODIN</p>
            <div class="keyvals mt-2">
              <div class="keyval">
                <span class="keyval-label">{{ t('versionLabel') }}</span
                ><span class="keyval-value">{{ item.odin_version || 'n/a' }}</span>
              </div>
              <div class="keyval">
                <span class="keyval-label">{{ t('sizeLabel') }}</span
                ><span class="keyval-value">{{ formatBytes(item.odin_size_bytes) }}</span>
              </div>
            </div>
            <div v-if="item.has_odin" class="actions-row mt-3">
              <SamsungButton
                small
                variant="primary"
                :loading="firmwareExtractBusyKey === item.key"
                @click="extractSamsungFwEntry(item.key)"
              >
                <HardDriveDownload v-if="firmwareExtractBusyKey !== item.key" :size="14" />
                {{ t('extractForce') }}
              </SamsungButton>
              <SamsungButton
                small
                variant="danger"
                :loading="firmwareDeleteBusyKey === `odin:${item.key}`"
                @click="deleteSamsungFwEntry('odin', item.key)"
              >
                <Trash2 v-if="firmwareDeleteBusyKey !== `odin:${item.key}`" :size="14" />
                {{ t('delete') }}
              </SamsungButton>
            </div>
          </div>

          <div class="form-section">
            <p class="section-kicker">FW</p>
            <div class="keyvals mt-2">
              <div class="keyval">
                <span class="keyval-label">{{ t('versionLabel') }}</span
                ><span class="keyval-value">{{ item.fw_version || 'n/a' }}</span>
              </div>
              <div class="keyval">
                <span class="keyval-label">{{ t('sizeLabel') }}</span
                ><span class="keyval-value">{{ formatBytes(item.fw_size_bytes) }}</span>
              </div>
            </div>
            <div v-if="item.has_fw" class="actions-row mt-3">
              <SamsungButton
                small
                variant="danger"
                :loading="firmwareDeleteBusyKey === `fw:${item.key}`"
                @click="deleteSamsungFwEntry('fw', item.key)"
              >
                <Trash2 v-if="firmwareDeleteBusyKey !== `fw:${item.key}`" :size="14" />
                {{ t('delete') }}
              </SamsungButton>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  </div>
</template>
