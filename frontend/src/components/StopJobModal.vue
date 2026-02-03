<script setup>
defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  stopTargetJob: { type: Object, default: null },
  stopSignalType: { type: String, required: true }
})

const emit = defineEmits(['close', 'confirm', 'update:stopSignalType'])
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div class="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('stopBuildTitle') }}</h3>
        <p class="mt-2 text-sm text-slate-300">
          Job <span class="font-mono text-xs">{{ stopTargetJob?.id }}</span> {{ t('willBeCanceled') }}
        </p>
        <div class="mt-3 rounded-lg border border-slate-700 bg-slate-800/70 p-3">
          <div class="mb-2 text-xs uppercase tracking-wide text-slate-400">{{ t('stopSignal') }}</div>
          <label class="flex items-center gap-2 text-sm text-slate-200">
            <input :checked="stopSignalType === 'sigterm'" type="radio" value="sigterm" @change="$emit('update:stopSignalType', 'sigterm')" />
            {{ t('sigtermLabel') }}
          </label>
          <label class="mt-1 flex items-center gap-2 text-sm text-slate-200">
            <input :checked="stopSignalType === 'sigkill'" type="radio" value="sigkill" @change="$emit('update:stopSignalType', 'sigkill')" />
            {{ t('sigkillLabel') }}
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
            {{ t('keepRunning') }}
          </button>
          <button class="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-500" @click="$emit('confirm')">
            {{ t('stopJob') }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
