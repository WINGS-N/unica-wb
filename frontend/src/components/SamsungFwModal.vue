<script setup>
defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  samsungFwLoading: { type: Boolean, required: true },
  samsungFwItems: { type: Array, required: true },
  target: { type: String, required: true },
  firmwareProgress: { type: Object, required: true },
  firmwareDeleteBusyKey: { type: String, required: true },
  firmwareExtractBusyKey: { type: String, required: true },
  normalizeModelForImage: { type: Function, required: true },
  deviceImageSvgData: { type: Function, required: true },
  progressTitle: { type: Function, required: true },
  progressPct: { type: Function, required: true },
  progressBarWidth: { type: Function, required: true },
  formatSpeed: { type: Function, required: true },
  formatDuration: { type: Function, required: true },
  formatBytes: { type: Function, required: true }
})

const emit = defineEmits(['close', 'stop-progress', 'extract-entry', 'delete-entry'])
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="$emit('close')">
      <div class="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-lg font-semibold text-slate-100">{{ t('samsungFw') }}</h3>
          <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
            {{ t('close') }}
          </button>
        </div>
        <p class="mt-2 text-sm text-slate-300">{{ t('samsungFwHint') }}</p>
        <div v-if="samsungFwLoading" class="mt-5 flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/60 py-10">
          <div class="flex items-center gap-3 text-sm text-slate-200">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-slate-500 border-t-cyan-400"></span>
            <span>{{ t('loading') }}</span>
          </div>
        </div>
        <div v-else-if="!samsungFwItems.length" class="mt-4 text-sm text-slate-400">{{ t('samsungFwEmpty') }}</div>
        <div v-else class="mt-4 grid gap-3 sm:grid-cols-2">
          <div v-for="item in samsungFwItems" :key="item.key" class="rounded-xl border border-slate-700 bg-slate-800/70 p-4">
            <div class="text-sm font-semibold text-slate-100">{{ item.model }}<span v-if="item.csc"> / {{ item.csc }}</span></div>
            <img
              :src="`/devices/${normalizeModelForImage(item.model)}.png`"
              alt="firmware device"
              class="mt-2 h-14 w-14 rounded-lg border border-slate-700 bg-slate-900 object-cover"
              @error="(e) => { e.target.src = deviceImageSvgData(item.model || target) }"
            />
            <div class="mt-1 text-xs text-slate-400">{{ t('latestVersion') }}: {{ item.latest_version || 'n/a' }}</div>
            <div v-if="firmwareProgress[item.key]?.status === 'running'" class="mt-2">
              <div class="mb-1 flex items-center justify-between gap-2 text-[11px] text-cyan-300">
                <span>{{ progressTitle(firmwareProgress[item.key]) }}: {{ progressPct(firmwareProgress[item.key]) }}%</span>
                <button
                  class="rounded border border-red-400/60 bg-red-500/20 px-1.5 py-0 text-[10px] font-semibold text-red-300 hover:bg-red-500/30"
                  @click.stop="$emit('stop-progress', firmwareProgress[item.key], $event)"
                >✕</button>
              </div>
              <div class="h-1.5 overflow-hidden rounded-full bg-slate-700">
                <div
                  class="h-full bg-cyan-400 transition-all duration-200"
                  :style="{ width: `${progressBarWidth(firmwareProgress[item.key])}%` }"
                />
              </div>
              <div class="mt-1 text-[11px] text-slate-300">
                {{ t('speedLabel') }}: {{ formatSpeed(firmwareProgress[item.key]?.speed_bps) }}
                • {{ t('elapsedLabel') }}: {{ formatDuration(firmwareProgress[item.key]?.elapsed_sec) }}
                • {{ t('etaLabel') }}: {{ formatDuration(firmwareProgress[item.key]?.eta_sec) }}
              </div>
            </div>
            <div class="mt-3 rounded-lg border border-slate-700 bg-slate-900/60 p-3">
              <div class="text-xs font-semibold uppercase text-slate-300">ODIN</div>
              <div class="mt-1 text-xs text-slate-300">{{ t('versionLabel') }}: {{ item.odin_version || 'n/a' }}</div>
              <div class="text-xs text-slate-300">{{ t('sizeLabel') }}: {{ formatBytes(item.odin_size_bytes) }}</div>
              <button
                v-if="item.has_odin"
                class="mt-2 mr-2 rounded-md border border-cyan-400/60 bg-cyan-500/20 px-2 py-1 text-[11px] font-semibold uppercase text-cyan-300 hover:bg-cyan-500/30 disabled:opacity-50"
                :disabled="firmwareExtractBusyKey === item.key"
                @click="$emit('extract-entry', item.key)"
              >
                {{ t('extractForce') }}
              </button>
              <button
                v-if="item.has_odin"
                class="mt-2 rounded-md border border-red-400/60 bg-red-500/20 px-2 py-1 text-[11px] font-semibold uppercase text-red-300 hover:bg-red-500/30 disabled:opacity-50"
                :disabled="firmwareDeleteBusyKey === `odin:${item.key}`"
                @click="$emit('delete-entry', 'odin', item.key)"
              >
                {{ t('delete') }}
              </button>
            </div>
            <div class="mt-2 rounded-lg border border-slate-700 bg-slate-900/60 p-3">
              <div class="text-xs font-semibold uppercase text-slate-300">FW</div>
              <div class="mt-1 text-xs text-slate-300">{{ t('versionLabel') }}: {{ item.fw_version || 'n/a' }}</div>
              <div class="text-xs text-slate-300">{{ t('sizeLabel') }}: {{ formatBytes(item.fw_size_bytes) }}</div>
              <button
                v-if="item.has_fw"
                class="mt-2 rounded-md border border-red-400/60 bg-red-500/20 px-2 py-1 text-[11px] font-semibold uppercase text-red-300 hover:bg-red-500/30 disabled:opacity-50"
                :disabled="firmwareDeleteBusyKey === `fw:${item.key}`"
                @click="$emit('delete-entry', 'fw', item.key)"
              >
                {{ t('delete') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>
