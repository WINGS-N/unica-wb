<script setup>
defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  repoPullBusy: { type: Boolean, required: true },
  defaultsLoading: { type: Boolean, required: true },
  repoSyncText: { type: String, required: true },
  repoSync: { type: Object, required: true },
  currentCommitDetails: { type: Object, required: true },
  currentCommit: { type: String, required: true }
})

const emit = defineEmits(['close', 'pull'])
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="$emit('close')">
      <div class="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-lg font-semibold text-slate-100">{{ t('currentCommit') }}</h3>
          <div class="flex items-center gap-2">
            <button
              class="rounded-lg border border-emerald-500/70 bg-emerald-500/20 px-3 py-1.5 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-60"
              :disabled="repoPullBusy"
              @click="$emit('pull')"
            >
              {{ repoPullBusy ? t('loading') : t('pullRepo') }}
            </button>
            <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
              {{ t('close') }}
            </button>
          </div>
        </div>
        <div v-if="defaultsLoading" class="mt-5 flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/60 py-10">
          <div class="flex items-center gap-3 text-sm text-slate-200">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-slate-500 border-t-cyan-400"></span>
            <span>{{ t('loading') }}</span>
          </div>
        </div>
        <div v-else class="mt-3 grid gap-2 rounded-xl border border-slate-700 bg-slate-800/60 p-3 text-xs text-slate-200">
          <div><span class="text-slate-400">{{ t('repoSyncStatus') }}:</span> {{ repoSyncText }}</div>
          <div><span class="text-slate-400">{{ t('repoSyncRemote') }}:</span> <span class="font-mono">{{ repoSync.remote_ref || 'n/a' }}</span></div>
          <div><span class="text-slate-400">{{ t('branchLabel') }}:</span> <span class="font-mono">{{ currentCommitDetails.branch || 'n/a' }}</span></div>
          <div><span class="text-slate-400">{{ t('shortHashLabel') }}:</span> <span class="font-mono">{{ currentCommitDetails.short_hash || currentCommit }}</span></div>
          <div><span class="text-slate-400">{{ t('fullHashLabel') }}:</span> <span class="font-mono break-all">{{ currentCommitDetails.full_hash || 'n/a' }}</span></div>
          <div><span class="text-slate-400">{{ t('commitTitleLabel') }}:</span> {{ currentCommitDetails.subject || 'n/a' }}</div>
          <div><span class="text-slate-400">{{ t('commitBodyLabel') }}:</span></div>
          <pre class="max-h-40 overflow-auto rounded-lg border border-slate-700 bg-slate-900 p-2 text-[11px] text-slate-300">{{ currentCommitDetails.body || 'n/a' }}</pre>
          <div><span class="text-slate-400">{{ t('authorLabel') }}:</span> {{ currentCommitDetails.author_name || 'n/a' }} <span class="text-slate-400">&lt;{{ currentCommitDetails.author_email || 'n/a' }}&gt;</span></div>
          <div><span class="text-slate-400">{{ t('committerLabel') }}:</span> {{ currentCommitDetails.committer_name || 'n/a' }} <span class="text-slate-400">&lt;{{ currentCommitDetails.committer_email || 'n/a' }}&gt;</span></div>
        </div>
      </div>
    </div>
  </Transition>
</template>
