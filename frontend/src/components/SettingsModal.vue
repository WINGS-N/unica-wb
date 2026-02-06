<script setup>
const props = defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  authEnabled: { type: Boolean, required: true },
  authBusy: { type: Boolean, required: true },
  authPassword: { type: String, required: true },
  authPasswordConfirm: { type: String, required: true },
  repoUsername: { type: String, required: true },
  repoToken: { type: String, required: true },
  repoTokenSet: { type: Boolean, required: true },
  resources: { type: Object, default: null },
  resourcesLoading: { type: Boolean, required: true }
})

const emit = defineEmits([
  'close',
  'set-password',
  'clear-password',
  'save-repo-creds',
  'refresh-resources',
  'update:authPassword',
  'update:authPasswordConfirm',
  'update:repoUsername',
  'update:repoToken'
])

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const scaled = bytes / (1024 ** idx)
  return `${scaled.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4" @click.self="$emit('close')">
    <div class="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('settings') }}</h3>
        <button class="rounded-lg border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800" @click="$emit('close')">{{ t('done') }}</button>
      </div>

      <div class="mt-4 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
        <div class="text-sm font-semibold text-slate-200">{{ t('authTitle') }}</div>
        <div class="mt-2 text-xs text-slate-400">{{ authEnabled ? t('authEnabled') : t('authDisabled') }}</div>

        <div class="mt-4 grid gap-2">
          <input
            :value="authPassword"
            type="password"
            class="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            :placeholder="t('authNewPassword')"
            @input="$emit('update:authPassword', $event.target.value)"
          />
          <input
            :value="authPasswordConfirm"
            type="password"
            class="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            :placeholder="t('authConfirmPassword')"
            @input="$emit('update:authPasswordConfirm', $event.target.value)"
          />
          <div class="flex flex-wrap gap-2">
            <button class="rounded-lg border border-cyan-500/60 bg-cyan-500/20 px-3 py-1.5 text-sm text-cyan-200" :disabled="authBusy" @click="$emit('set-password')">
              {{ t('authSetPassword') }}
            </button>
            <button class="rounded-lg border border-red-500/60 bg-red-500/20 px-3 py-1.5 text-sm text-red-200" :disabled="authBusy" @click="$emit('clear-password')">
              {{ t('authClearPassword') }}
            </button>
          </div>
        </div>
      </div>

      <div class="mt-4 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
        <div class="text-sm font-semibold text-slate-200">{{ t('repoCredsTitle') }}</div>
        <div class="mt-2 text-xs text-slate-400">{{ repoTokenSet ? t('repoTokenSet') : t('repoTokenNotSet') }}</div>
        <div class="mt-3 grid gap-2">
          <input
            :value="repoUsername"
            class="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            :placeholder="t('repoUsername')"
            @input="$emit('update:repoUsername', $event.target.value)"
          />
          <input
            :value="repoToken"
            type="password"
            class="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            :placeholder="t('repoToken')"
            @input="$emit('update:repoToken', $event.target.value)"
          />
          <button class="rounded-lg border border-emerald-500/60 bg-emerald-500/20 px-3 py-1.5 text-sm text-emerald-200" :disabled="authBusy" @click="$emit('save-repo-creds')">
            {{ t('save') }}
          </button>
        </div>
      </div>

      <div class="mt-4 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
        <div class="flex items-center justify-between">
          <div class="text-sm font-semibold text-slate-200">{{ t('resourcesTitle') }}</div>
          <button class="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800" :disabled="resourcesLoading" @click="$emit('refresh-resources')">
            {{ t('refresh') }}
          </button>
        </div>
        <div v-if="resourcesLoading" class="mt-3 text-xs text-slate-400">{{ t('loading') }}</div>
        <div v-else class="mt-3 grid gap-2 text-xs text-slate-300">
          <div>CPU load: {{ resources?.load?.['1m']?.toFixed?.(2) || 0 }} / {{ resources?.load?.['5m']?.toFixed?.(2) || 0 }} / {{ resources?.load?.['15m']?.toFixed?.(2) || 0 }}</div>
          <div>RAM: {{ formatBytes(resources?.memory?.used) }} / {{ formatBytes(resources?.memory?.total) }}</div>
          <div>Disk (out): {{ formatBytes(resources?.disk?.out?.used) }} / {{ formatBytes(resources?.disk?.out?.total) }}</div>
          <div>Disk (data): {{ formatBytes(resources?.disk?.data?.used) }} / {{ formatBytes(resources?.disk?.data?.total) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
