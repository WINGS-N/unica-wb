<script setup>
const props = defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  password: { type: String, required: true },
  busy: { type: Boolean, required: true }
})

const emit = defineEmits(['close', 'login', 'update:password'])
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" @click.self="$emit('close')">
    <div class="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
      <div class="text-lg font-semibold text-slate-100">{{ t('unauthorizedTitle') }}</div>
      <div class="mt-2 text-sm text-slate-300">{{ t('unauthorizedDesc') }}</div>
      <input
        :value="password"
        type="password"
        class="mt-4 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
        :placeholder="t('authPassword')"
        @input="$emit('update:password', $event.target.value)"
        @keydown.enter.prevent="$emit('login')"
      />
      <div class="mt-4 flex justify-end gap-2">
        <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800" @click="$emit('close')">
          {{ t('cancel') }}
        </button>
        <button class="rounded-lg border border-emerald-500/60 bg-emerald-500/20 px-3 py-1.5 text-sm text-emerald-200" :disabled="busy" @click="$emit('login')">
          {{ t('authLogin') }}
        </button>
      </div>
    </div>
  </div>
</template>
