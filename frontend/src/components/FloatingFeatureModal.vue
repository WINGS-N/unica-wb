<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, required: true },
  ffLoading: { type: Boolean, required: true },
  ffEntries: { type: Array, required: true },
  ffOverrides: { type: Object, required: true },
  t: { type: Function, required: true }
})

const emit = defineEmits(['close', 'toggle', 'update-value'])
const search = ref('')

watch(
  () => props.open,
  (value) => {
    if (value) search.value = ''
  }
)

const overridesMap = computed(() => props.ffOverrides || {})

function hasOverride(entry) {
  return Object.prototype.hasOwnProperty.call(overridesMap.value, entry.key)
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.ffEntries
  return props.ffEntries.filter((entry) => {
    const key = String(entry.key || '').toLowerCase()
    const descKey = `ffDesc_${entry.key || ''}`
    const desc = String(props.t(descKey) || '').toLowerCase()
    return key.includes(q) || (desc && desc !== descKey.toLowerCase() && desc.includes(q))
  })
})

function effectiveValue(entry) {
  if (!hasOverride(entry)) return entry.value
  const override = overridesMap.value[entry.key]
  return override === undefined || override === null ? entry.value : String(override)
}

function isOverride(entry) {
  return hasOverride(entry)
}

function desc(entry) {
  const key = `ffDesc_${entry.key || ''}`
  const value = props.t(key)
  return value === key ? '' : value
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-40 flex items-center justify-center px-4">
    <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="$emit('close')" />
    <div class="relative z-10 w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/95 p-5 text-slate-100 shadow-2xl">
      <div class="flex items-start justify-between">
        <div>
          <h3 class="text-lg font-semibold">{{ t('ffEditor') }}</h3>
          <p class="mt-1 text-xs text-slate-400">{{ t('ffHint') }}</p>
        </div>
        <button class="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800" @click="$emit('close')">
          {{ t('close') }}
        </button>
      </div>

      <div class="mt-3 flex items-center gap-2">
        <input
          v-model="search"
          type="text"
          class="w-full rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          :placeholder="t('ffSearch')"
        />
        <span v-if="ffLoading" class="h-4 w-4 animate-spin rounded-full border border-slate-500 border-t-cyan-400" />
      </div>

      <div v-if="ffLoading && !ffEntries.length" class="mt-5 flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 py-10 text-sm text-slate-300">
        {{ t('loading') }}
      </div>

      <div v-else class="mt-4 max-h-[60vh] space-y-2 overflow-y-auto overflow-x-hidden pr-1">
        <div v-if="!filtered.length" class="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-300">
          {{ t('ffNoMatch') }}
        </div>
        <div
          v-for="entry in filtered"
          :key="entry.key"
          class="rounded-xl border border-slate-800 bg-slate-900/70 p-3"
          :class="entry.is_boolean ? 'cursor-pointer hover:border-slate-600' : ''"
          @click="entry.is_boolean ? $emit('toggle', entry) : null"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="break-words text-sm font-semibold text-slate-100">{{ entry.key }}</div>
              <div v-if="desc(entry)" class="mt-1 break-words text-xs text-slate-400">{{ desc(entry) }}</div>
              <div class="mt-2 text-[11px] text-slate-500">
                {{ t('ffDefault') }}: <span class="font-mono text-slate-300">{{ entry.value }}</span>
              </div>
              <button
                v-if="isOverride(entry)"
                class="mt-2 rounded-md border border-slate-700 px-2 py-1 text-[11px] font-semibold uppercase text-slate-300 hover:bg-slate-800"
                @click.stop="$emit('use-default', entry)"
              >
                {{ t('useDefault') }}
              </button>
              <div v-if="!entry.is_boolean" class="mt-3">
                <input
                  type="text"
                  class="w-full rounded-xl border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                  :value="isOverride(entry) ? overridesMap[entry.key] : entry.value"
                  @input.stop="$emit('update-value', entry, $event.target.value)"
                />
              </div>
            </div>
            <div class="flex min-w-[120px] items-center justify-end">
              <button
                v-if="entry.is_boolean"
                class="rounded-md px-2 py-1 text-xs font-semibold uppercase"
                :class="effectiveValue(entry).toUpperCase() === 'TRUE'
                  ? (isOverride(entry) ? 'border border-emerald-500/60 bg-emerald-500/20 text-emerald-200' : 'border border-emerald-400/40 bg-emerald-500/10 text-emerald-200')
                  : (isOverride(entry) ? 'border border-red-500/60 bg-red-500/20 text-red-200' : 'border border-red-400/30 bg-red-500/10 text-red-200')"
                @click.stop="$emit('toggle', entry)"
              >
                {{ effectiveValue(entry).toUpperCase() === 'TRUE' ? t('enabled') : t('disabled') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
