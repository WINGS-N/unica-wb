<script setup>
import { computed, onMounted, ref } from 'vue'
import { RotateCcw } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { hasTranslation, t } from '../lang/index.js'
import {
  clearFFOverrides,
  effectiveFFValue,
  ffEntries,
  ffLoading,
  ffOverrides,
  ffOverridesCount,
  loadFFEntries,
  toggleFF,
  updateFFValue,
  useFFDefault
} from '../stores/app.js'

const search = ref('')

function describe(entry) {
  const key = `ffDesc_${entry.key || ''}`
  return hasTranslation(key) ? t(key) : ''
}

function hasOverride(entry) {
  return Object.prototype.hasOwnProperty.call(ffOverrides.value || {}, entry.key)
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return ffEntries.value
  return ffEntries.value.filter(
    (entry) =>
      String(entry.key || '')
        .toLowerCase()
        .includes(q) || describe(entry).toLowerCase().includes(q)
  )
})

onMounted(() => {
  if (!ffEntries.value.length) loadFFEntries()
})
</script>

<template>
  <OverlayView :title="t('ffEditor')">
    <template #actions>
      <SamsungButton small :disabled="!ffOverridesCount" @click="clearFFOverrides">
        <RotateCcw :size="14" /> {{ t('clear') }}
      </SamsungButton>
    </template>

    <p class="page-subtitle">{{ t('ffHint') }}</p>
    <OneuiInput v-model="search" :placeholder="t('ffSearch')" />
    <p class="section-kicker">{{ t('ffOverridesForBuild') }}: {{ ffOverridesCount }} / {{ ffEntries.length }}</p>

    <div v-if="ffLoading && !ffEntries.length" class="loading-block"><SamsungLoader /></div>

    <div v-else-if="!filtered.length" class="empty-state">{{ t('ffNoMatch') }}</div>

    <div v-else class="list">
      <div v-for="entry in filtered" :key="entry.key" class="list-row" :class="{ 'is-selected': hasOverride(entry) }">
        <div class="flex items-start gap-4">
          <div class="min-w-0 flex-1">
            <p class="list-row-title font-mono text-[13px]">{{ entry.key }}</p>
            <p v-if="describe(entry)" class="list-row-meta">{{ describe(entry) }}</p>
            <p class="list-row-meta">
              {{ t('ffDefault') }}: <span class="mono-chip">{{ entry.value || '""' }}</span>
            </p>
          </div>
          <OneuiSwitch
            v-if="entry.is_boolean"
            :model-value="effectiveFFValue(entry).toUpperCase() === 'TRUE'"
            @update:model-value="toggleFF(entry)"
          />
        </div>
        <div v-if="!entry.is_boolean" class="mt-2">
          <OneuiInput
            mono
            :model-value="hasOverride(entry) ? ffOverrides[entry.key] : entry.value"
            @update:model-value="(v) => updateFFValue(entry, v)"
          />
        </div>
        <SamsungButton v-if="hasOverride(entry)" small class="mt-2" @click="useFFDefault(entry)">
          {{ t('useDefault') }}
        </SamsungButton>
      </div>
    </div>
  </OverlayView>
</template>
