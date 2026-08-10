<script setup>
import { computed, onMounted, ref } from 'vue'
import { RotateCcw } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { t } from '../lang/index.js'
import { loadModsEntries, modsDisabledIds, modsEntries, modsLoading, resetMods, toggleMod } from '../stores/app.js'

const search = ref('')

const disabledSet = computed(() => new Set(modsDisabledIds.value))

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return modsEntries.value
  return modsEntries.value.filter(
    (entry) =>
      String(entry.module_dir || '')
        .toLowerCase()
        .includes(q) ||
      String(entry.name || '')
        .toLowerCase()
        .includes(q) ||
      String(entry.author || '')
        .toLowerCase()
        .includes(q)
  )
})

onMounted(() => {
  if (!modsEntries.value.length) loadModsEntries()
})
</script>

<template>
  <OverlayView :title="t('modsList')">
    <template #actions>
      <SamsungButton small @click="resetMods"> <RotateCcw :size="14" /> {{ t('useDefault') }} </SamsungButton>
    </template>

    <p class="page-subtitle">{{ t('modsHint') }} <span class="mono-chip">unica/mods</span></p>
    <OneuiInput v-model="search" :placeholder="t('search')" />
    <p class="section-kicker">{{ t('modsDisabledShort') }}: {{ modsDisabledIds.length }} / {{ modsEntries.length }}</p>

    <div v-if="modsLoading && !modsEntries.length" class="loading-block"><SamsungLoader /></div>

    <div v-else-if="!filtered.length" class="empty-state">{{ t('noMatches') }}</div>

    <div v-else class="list">
      <div
        v-for="entry in filtered"
        :key="entry.id"
        class="list-row flex items-center gap-4"
        :class="{ 'is-off': disabledSet.has(entry.id) }"
      >
        <div class="min-w-0 flex-1">
          <p class="list-row-title">{{ entry.name || entry.module_dir }}</p>
          <p class="list-row-meta font-mono">{{ entry.module_dir }}</p>
          <p v-if="entry.author" class="list-row-meta">{{ entry.author }}</p>
        </div>
        <OneuiSwitch :model-value="!disabledSet.has(entry.id)" @update:model-value="toggleMod(entry.id)" />
      </div>
    </div>
  </OverlayView>
</template>
