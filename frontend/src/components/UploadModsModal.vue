<script setup>
defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  uploadError: { type: String, required: true },
  uploadedMods: { type: Array, required: true },
  uploadBusy: { type: Boolean, required: true }
})

const emit = defineEmits(['close', 'file-change', 'upload'])
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div class="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <h3 class="text-lg font-semibold text-slate-100">{{ t('uploadExtraModsTitle') }}</h3>
        <p class="mt-2 text-sm text-slate-300">
          {{ t('uploadHint') }} <span class="font-mono text-xs">module-name/module.prop</span>
          {{ t('oneBuildModsHint') }}
        </p>
        <input
          type="file"
          accept=".zip,.tar,.gz,.xz,.bz2,.zst,.tgz,.txz,.tbz2,.tar.gz,.tar.xz,.tar.zst"
          class="mt-3 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          @change="$emit('file-change', $event)"
        />
        <p v-if="uploadError" class="mt-2 text-sm text-red-300">{{ uploadError }}</p>
        <div v-if="uploadedMods.length" class="mt-4 max-h-64 space-y-2 overflow-auto pr-1">
          <div v-for="m in uploadedMods" :key="`${m.module_dir}-${m.id}`" class="rounded-lg border border-slate-700 bg-slate-800/70 p-3">
            <div class="text-sm font-semibold text-slate-100">{{ m.name || m.module_dir }}</div>
            <div class="mt-1 text-xs text-slate-300">dir: {{ m.module_dir }}</div>
            <div class="text-xs text-slate-300">id: {{ m.id || 'n/a' }} | ver: {{ m.version || 'n/a' }} ({{ m.versionCode || 'n/a' }})</div>
            <div class="text-xs text-slate-300">author: {{ m.author || 'n/a' }}</div>
            <div class="mt-1 text-xs text-slate-400">{{ m.description || 'No description' }}</div>
          </div>
        </div>
        <div v-if="uploadBusy" class="mt-4 flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/60 py-4">
          <div class="flex items-center gap-3 text-sm text-slate-200">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-slate-500 border-t-cyan-400"></span>
            <span>{{ t('loading') }}</span>
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
            {{ t('close') }}
          </button>
          <button
            class="rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
            :disabled="uploadBusy"
            @click="$emit('upload')"
          >
            {{ uploadBusy ? t('uploading') : t('uploadValidate') }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
