<script setup>
import { computed, onMounted, ref } from 'vue'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import OneuiTextarea from '../components/ui/OneuiTextarea.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { t } from '../lang/index.js'
import {
  debloatAddProductText,
  debloatAddSystemText,
  debloatAddedCount,
  debloatDisabledIds,
  debloatEntries,
  debloatLoading,
  loadDebloatEntries,
  toggleDebloat
} from '../stores/app.js'

const search = ref('')
const disabledSet = computed(() => new Set(debloatDisabledIds.value))

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return debloatEntries.value
  return debloatEntries.value.filter(
    (entry) =>
      String(entry.path || '')
        .toLowerCase()
        .includes(q) ||
      String(entry.partition || '')
        .toLowerCase()
        .includes(q) ||
      String(entry.section || '')
        .toLowerCase()
        .includes(q)
  )
})

onMounted(() => {
  if (!debloatEntries.value.length) loadDebloatEntries()
})
</script>

<template>
  <OverlayView :title="t('debloatList')">
    <p class="page-subtitle">
      {{ t('debloatHint') }} <span class="mono-chip">unica/debloat.sh</span> {{ t('debloatHint2') }}
    </p>

    <SectionCard :title="t('customAddedPaths')" :subtitle="t('onePerLine')">
      <OneuiTextarea v-model="debloatAddSystemText" :label="t('systemAdds')" :rows="4" />
      <OneuiTextarea v-model="debloatAddProductText" :label="t('productAdds')" :rows="4" />
      <p v-if="debloatAddedCount" class="section-kicker">+{{ debloatAddedCount }} {{ t('customDebloatPaths') }}</p>
    </SectionCard>

    <OneuiInput v-model="search" :placeholder="t('search')" />
    <p class="section-kicker">
      {{ t('debloatDisabledShort') }}: {{ debloatDisabledIds.length }} / {{ debloatEntries.length }}
    </p>

    <div v-if="debloatLoading && !debloatEntries.length" class="loading-block"><SamsungLoader /></div>

    <div v-else-if="!filtered.length" class="empty-state">{{ t('noMatches') }}</div>

    <div v-else class="list">
      <div
        v-for="entry in filtered"
        :key="entry.id"
        class="list-row flex items-center gap-4"
        :class="{ 'is-off': disabledSet.has(entry.id) }"
      >
        <div class="min-w-0 flex-1">
          <p class="list-row-title font-mono text-[13px]">{{ entry.path }}</p>
          <p class="list-row-meta">{{ entry.partition }} - {{ entry.section }}</p>
        </div>
        <OneuiSwitch :model-value="!disabledSet.has(entry.id)" @update:model-value="toggleDebloat(entry.id)" />
      </div>
    </div>
  </OverlayView>
</template>
