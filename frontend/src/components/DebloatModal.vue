<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  debloatLoading: { type: Boolean, required: true },
  debloatEntries: { type: Array, required: true },
  debloatDisabledIds: { type: Array, required: true },
  debloatAddSystemText: { type: String, required: true },
  debloatAddProductText: { type: String, required: true },
  debloatAddedCount: { type: Number, required: true }
})

const emit = defineEmits(['close', 'toggle', 'update:debloatAddSystemText', 'update:debloatAddProductText'])

const disabledSet = computed(() => new Set(props.debloatDisabledIds || []))

function isEnabled(id) {
  return !disabledSet.value.has(id)
}
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="$emit('close')">
      <div class="max-h-[90vh] w-full max-w-3xl overflow-y-auto overflow-x-hidden rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('debloatList') }}</h3>
        <p class="mt-2 text-sm text-slate-300">
          {{ t('debloatHint') }} <span class="font-mono text-xs">unica/debloat.sh</span> {{ t('debloatHint2') }}
        </p>
        <div v-if="debloatLoading && !debloatEntries.length" class="mt-5 flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/60 py-10">
          <div class="flex items-center gap-3 text-sm text-slate-200">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-slate-500 border-t-cyan-400"></span>
            <span>{{ t('loading') }}</span>
          </div>
        </div>
        <div v-else class="mt-4 space-y-2 pr-1">
          <div
            v-for="entry in debloatEntries"
            :key="entry.id"
            class="flex cursor-pointer items-start justify-between gap-3 rounded-lg border p-3 transition"
            :class="isEnabled(entry.id)
              ? 'border-slate-700 bg-slate-800/70 hover:bg-slate-700/70'
              : 'border-red-600/50 bg-red-900/10 hover:bg-red-900/20'"
            @click="$emit('toggle', entry.id)"
          >
            <div class="min-w-0 flex-1">
              <div class="break-words text-sm font-semibold text-slate-100">{{ entry.path }}</div>
              <div class="mt-1 text-xs text-slate-400">{{ entry.partition }} • {{ entry.section }}</div>
            </div>
            <button type="button" class="rounded-md px-2 py-1 text-xs font-semibold uppercase" :class="isEnabled(entry.id) ? 'bg-emerald-600/30 text-emerald-300' : 'bg-red-600/30 text-red-200'">
              {{ isEnabled(entry.id) ? t('enabled') : t('disabled') }}
            </button>
          </div>
          <div v-if="debloatLoading" class="flex items-center gap-2 text-sm text-slate-300">
            <span class="h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-cyan-400"></span>
            <span>{{ t('loading') }}</span>
          </div>
        </div>

        <label class="mt-4 block text-sm text-slate-200">{{ t('systemAdds') }}</label>
        <textarea
          :value="debloatAddSystemText"
          :placeholder="t('onePerLine')"
          class="mt-1 h-20 w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-xs sm:h-24"
          @input="$emit('update:debloatAddSystemText', $event.target.value)"
        />
        <label class="mt-3 block text-sm text-slate-200">{{ t('productAdds') }}</label>
        <textarea
          :value="debloatAddProductText"
          :placeholder="t('onePerLine')"
          class="mt-1 h-20 w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-xs sm:h-24"
          @input="$emit('update:debloatAddProductText', $event.target.value)"
        />

        <div v-if="debloatAddedCount" class="mt-2 text-xs text-amber-200">
          {{ t('customAddedPaths') }}: {{ debloatAddedCount }}
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
            {{ t('done') }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
