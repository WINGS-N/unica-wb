<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { Bell, ChevronRight, Info, Layers, RefreshCw } from 'lucide-vue-next'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import OneuiSelect from '../components/ui/OneuiSelect.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import OneuiTextarea from '../components/ui/OneuiTextarea.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { language, setLanguage, t } from '../lang/index.js'
import { openOverlay } from '../stores/nav.js'
import { APP_VERSION, PROJECT } from '../data/credits.js'
import {
  disablePush,
  enablePush,
  isIos,
  isStandalone,
  pushBusy,
  pushPermission,
  pushSubscribed,
  pushSupported,
  refreshPushState,
  sendTestPush
} from '../stores/push.js'
import {
  activeWorkspace,
  advancedLoading,
  advancedSettings,
  advancedSourceOverrideInput,
  advancedTargetsOverrideInput,
  advancedBusy,
  authBusy,
  authEnabled,
  authPassword,
  authPasswordConfirm,
  clearPassword,
  fetchAdvancedSettings,
  fetchResources,
  unwatchResources,
  watchResources,
  formatBytes,
  repoTokenInput,
  repoUsernameInput,
  repoInfo,
  requestAdvancedSave,
  resources,
  resourcesLoading,
  saveRepoCredentials,
  setPassword,
  workspaces
} from '../stores/app.js'

const languageOptions = computed(() => [
  { value: 'en', label: `\u{1F1FA}\u{1F1F8} ${t('langEn')}` },
  { value: 'ru', label: `\u{1F1F7}\u{1F1FA} ${t('langRu')}` }
])

const sourceConfigOptions = () => [
  { value: '', label: t('auto') },
  ...(advancedSettings.value.source_config_candidates || []).map((cfg) => ({ value: cfg.name, label: cfg.name }))
]

function onSourceConfigChange(value) {
  advancedSourceOverrideInput.value = value
  requestAdvancedSave()
}

function clearTargetsOverride() {
  advancedTargetsOverrideInput.value = ''
  requestAdvancedSave()
}

function toggleTarget(code) {
  const set = new Set(
    (advancedTargetsOverrideInput.value || '')
      .split(/[\s,]+/)
      .map((x) => x.trim())
      .filter(Boolean)
  )
  if (set.has(code)) set.delete(code)
  else set.add(code)
  advancedTargetsOverrideInput.value = Array.from(set).join('\n')
  requestAdvancedSave()
}

onMounted(() => {
  watchResources()
  fetchAdvancedSettings()
  refreshPushState()
})

const pushBlockedOnIos = computed(() => isIos() && !isStandalone())

onBeforeUnmount(unwatchResources)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="section-kicker">{{ activeWorkspace?.name || '' }}</p>
        <h1 class="page-title">{{ t('settings') }}</h1>
      </div>
    </header>

    <button
      type="button"
      class="surface-card flex items-center gap-4 text-left transition-colors hover:bg-white/[0.03]"
      @click="openOverlay('workspaces')"
    >
      <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/[0.07]"
        ><Layers :size="20"
      /></span>
      <span class="min-w-0 flex-1">
        <span class="section-kicker">{{ t('workspaces') }}</span>
        <span class="mt-1 block truncate text-[15px] font-bold">{{ activeWorkspace?.name || t('noWorkspace') }}</span>
        <span class="muted block truncate"
          >{{ workspaces.length }} {{ t('entries') }} - {{ activeWorkspace?.root_path || '' }}</span
        >
      </span>
      <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
    </button>

    <button
      type="button"
      class="surface-card flex items-center gap-4 text-left transition-colors hover:bg-white/[0.03]"
      @click="openOverlay('about')"
    >
      <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/[0.07]"
        ><Info :size="20"
      /></span>
      <span class="min-w-0 flex-1">
        <span class="section-kicker">{{ t('about') }}</span>
        <span class="mt-1 block truncate text-[15px] font-bold">{{ PROJECT.name }} {{ APP_VERSION }}</span>
        <span class="muted block truncate">{{ t('aboutRowHint') }}</span>
      </span>
      <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
    </button>

    <SectionCard :title="t('language')">
      <OneuiSelect block :model-value="language" :options="languageOptions" @change="setLanguage" />
    </SectionCard>

    <SectionCard :title="t('notificationsTitle')" :subtitle="t('notificationsHint')">
      <template v-if="pushSupported && !pushBlockedOnIos">
        <div class="form-section">
          <div class="form-row">
            <div class="min-w-0">
              <p class="form-label">{{ t('notificationsToggle') }}</p>
              <p class="form-hint">{{ t('notificationsToggleHint') }}</p>
            </div>
            <OneuiSwitch
              :model-value="pushSubscribed"
              :disabled="pushBusy || pushPermission === 'denied'"
              @update:model-value="(v) => (v ? enablePush() : disablePush())"
            />
          </div>
        </div>
        <p v-if="pushPermission === 'denied'" class="form-hint">{{ t('pushBlocked') }}</p>
        <SamsungButton v-if="pushSubscribed" small :loading="pushBusy" @click="sendTestPush">
          <Bell :size="14" /> {{ t('pushTest') }}
        </SamsungButton>
      </template>
      <p v-else-if="pushBlockedOnIos" class="form-hint">{{ t('pushIosHint') }}</p>
      <p v-else class="form-hint">{{ t('pushUnsupported') }}</p>
    </SectionCard>

    <SectionCard :title="t('authTitle')">
      <div class="flex items-center gap-2">
        <StatusPill :tone="authEnabled ? 'success' : 'warning'" :dot="false">
          {{ authEnabled ? t('authEnabled') : t('authDisabled') }}
        </StatusPill>
      </div>
      <OneuiInput v-model="authPassword" type="password" :label="t('authNewPassword')" />
      <OneuiInput v-model="authPasswordConfirm" type="password" :label="t('authConfirmPassword')" />
      <div class="actions-row">
        <SamsungButton variant="primary" :loading="authBusy" @click="setPassword">{{
          t('authSetPassword')
        }}</SamsungButton>
        <SamsungButton variant="danger" :disabled="!authEnabled || authBusy" @click="clearPassword">
          {{ t('authClearPassword') }}
        </SamsungButton>
      </div>
    </SectionCard>

    <SectionCard :title="t('repoCredsTitle')" :subtitle="t('repoCredsHint')">
      <StatusPill :tone="repoInfo.git_token_set ? 'success' : 'warning'" :dot="false">
        {{ repoInfo.git_token_set ? t('repoTokenSet') : t('repoTokenNotSet') }}
      </StatusPill>
      <OneuiInput v-model="repoUsernameInput" :label="t('repoUsername')" />
      <OneuiInput v-model="repoTokenInput" type="password" :label="t('repoToken')" />
      <SamsungButton variant="primary" :loading="authBusy" @click="saveRepoCredentials">{{ t('save') }}</SamsungButton>
    </SectionCard>

    <SectionCard :title="t('advancedTitle')" :loading="advancedBusy">
      <div v-if="advancedLoading" class="loading-block"><SamsungLoader /></div>
      <template v-else>
        <div class="form-section">
          <p class="form-section-title">{{ t('sourceConfigTitle') }}</p>
          <div class="keyvals">
            <div class="keyval">
              <span class="keyval-label">{{ t('sourceConfigAuto') }}</span>
              <span class="keyval-value mono">{{ advancedSettings.source_config_auto || t('auto') }}</span>
            </div>
            <div class="keyval">
              <span class="keyval-label">{{ t('sourceFirmwareAuto') }}</span>
              <span class="keyval-value mono">{{ advancedSettings.source_firmware_auto || 'n/a' }}</span>
            </div>
          </div>
          <div v-if="advancedSettings.source_config_preferred?.length" class="mt-2 flex flex-wrap gap-1.5">
            <span v-for="name in advancedSettings.source_config_preferred" :key="name" class="chip-static">{{
              name
            }}</span>
          </div>
          <OneuiSelect
            block
            class="mt-3"
            :label="t('sourceConfigOverride')"
            :model-value="advancedSourceOverrideInput"
            :options="sourceConfigOptions()"
            @change="onSourceConfigChange"
          />
        </div>

        <div class="form-section">
          <p class="form-section-title">{{ t('targetsTitle') }}</p>
          <p class="form-hint">
            {{ t('targetsDetected') }}: {{ advancedSettings.targets_detected?.length || 0 }} -
            {{ t('targetsEffective') }}: {{ advancedSettings.targets_effective?.length || 0 }}
          </p>
          <div v-if="advancedSettings.targets_detected?.length" class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="code in advancedSettings.targets_detected"
              :key="code"
              type="button"
              class="chip-button"
              :class="{
                'is-active': String(advancedTargetsOverrideInput || '')
                  .split(/[\s,]+/)
                  .includes(code)
              }"
              @click="toggleTarget(code)"
            >
              {{ code }}
            </button>
          </div>
          <OneuiTextarea
            v-model="advancedTargetsOverrideInput"
            class="mt-3"
            :label="t('targetsOverride')"
            :placeholder="t('targetsOverrideHint')"
            :rows="3"
            @update:model-value="requestAdvancedSave()"
          />
          <SamsungButton small class="mt-2" @click="clearTargetsOverride">
            {{ t('useDefault') }}
          </SamsungButton>
        </div>
      </template>
    </SectionCard>

    <SectionCard :title="t('resourcesTitle')">
      <template #actions>
        <SamsungButton small :loading="resourcesLoading" @click="fetchResources">
          <RefreshCw v-if="!resourcesLoading" :size="14" />
          {{ t('refresh') }}
        </SamsungButton>
      </template>
      <div class="keyvals">
        <div class="keyval">
          <span class="keyval-label">CPU load</span>
          <span class="keyval-value">
            {{ resources?.load?.['1m']?.toFixed?.(2) ?? 0 }} / {{ resources?.load?.['5m']?.toFixed?.(2) ?? 0 }} /
            {{ resources?.load?.['15m']?.toFixed?.(2) ?? 0 }}
          </span>
        </div>
        <div class="keyval">
          <span class="keyval-label">RAM</span>
          <span class="keyval-value"
            >{{ formatBytes(resources?.memory?.used) }} / {{ formatBytes(resources?.memory?.total) }}</span
          >
        </div>
        <div class="keyval">
          <span class="keyval-label">Disk (out)</span>
          <span class="keyval-value"
            >{{ formatBytes(resources?.disk?.out?.used) }} / {{ formatBytes(resources?.disk?.out?.total) }}</span
          >
        </div>
        <div class="keyval">
          <span class="keyval-label">Disk (data)</span>
          <span class="keyval-value"
            >{{ formatBytes(resources?.disk?.data?.used) }} / {{ formatBytes(resources?.disk?.data?.total) }}</span
          >
        </div>
      </div>
    </SectionCard>
  </div>
</template>
