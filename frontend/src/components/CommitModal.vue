<script setup>
defineProps({
  open: { type: Boolean, required: true },
  t: { type: Function, required: true },
  defaultsLoading: { type: Boolean, required: true },
  repoSyncText: { type: String, required: true },
  repoSync: { type: Object, required: true },
  currentCommitDetails: { type: Object, required: true },
  currentCommit: { type: String, required: true },
  repoInfo: { type: Object, required: true },
  repoActionBusy: { type: Boolean, required: true },
  repoProgress: { type: Object, required: true },
  formatBytes: { type: Function, required: true },
  formatSpeed: { type: Function, required: true },
  formatDuration: { type: Function, required: true }
})

const emit = defineEmits(['close', 'clone', 'pull', 'submodules', 'delete-repo-only', 'delete-repo-with-out', 'git-url-input'])

function progressPct(progress) {
  const val = Number(progress?.percent ?? 0)
  if (!Number.isFinite(val)) return 0
  return Math.max(0, Math.min(100, Math.round(val)))
}
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="$emit('close')">
      <div class="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-lg font-semibold text-slate-100">{{ t('currentCommit') }}</h3>
          <button class="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" @click="$emit('close')">
            {{ t('close') }}
          </button>
        </div>

        <div class="mt-3 grid gap-2 rounded-xl border border-slate-700 bg-slate-800/60 p-3 text-xs text-slate-200">
          <div class="text-slate-300">{{ t('repoUrlLabel') }}</div>
          <input
            class="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-200"
            :value="repoInfo.git_url || ''"
            @input="$emit('git-url-input', $event.target.value)"
            placeholder="https://github.com/user/UN1CA.git"
          />
          <div class="flex flex-wrap items-center gap-2 pt-1">
            <button class="rounded-lg border border-cyan-500/70 bg-cyan-500/20 px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-60" :disabled="repoActionBusy" @click="$emit('clone')">{{ t('repoClone') }}</button>
            <button class="rounded-lg border border-emerald-500/70 bg-emerald-500/20 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-60" :disabled="repoActionBusy" @click="$emit('pull')">{{ t('pullRepo') }}</button>
            <button class="rounded-lg border border-amber-500/70 bg-amber-500/20 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/30 disabled:opacity-60" :disabled="repoActionBusy" @click="$emit('submodules')">{{ t('updateSubmodules') }}</button>
            <button class="rounded-lg border border-red-500/70 bg-red-500/20 px-3 py-1.5 text-xs font-semibold text-red-200 hover:bg-red-500/30 disabled:opacity-60" :disabled="repoActionBusy" @click="$emit('delete-repo-only')">{{ t('deleteRepoKeepOut') }}</button>
            <button class="rounded-lg border border-rose-500/70 bg-rose-500/20 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/30 disabled:opacity-60" :disabled="repoActionBusy" @click="$emit('delete-repo-with-out')">{{ t('deleteRepoWithOut') }}</button>
          </div>
        </div>

        <div class="mt-3 grid gap-2 rounded-xl border border-slate-700 bg-slate-800/60 p-3 text-xs text-slate-200">
          <div><span class="text-slate-400">{{ t('repoSyncStatus') }}:</span> {{ repoSyncText }}</div>
          <div><span class="text-slate-400">{{ t('repoSyncRemote') }}:</span> <span class="font-mono">{{ repoSync.remote_ref || 'n/a' }}</span></div>
          <div><span class="text-slate-400">{{ t('repoPathLabel') }}:</span> <span class="font-mono break-all">{{ repoInfo.repo_path || 'n/a' }}</span></div>
          <div><span class="text-slate-400">{{ t('sizeLabel') }}:</span> {{ formatBytes(repoInfo.repo_size_bytes || 0) }}</div>
        </div>

        <div v-if="repoProgress?.status === 'running'" class="mt-3 rounded-xl border border-cyan-600/60 bg-cyan-500/10 p-3 text-xs text-cyan-100">
          <div class="mb-1 flex items-center justify-between gap-2">
            <span class="font-semibold">{{ repoProgress.title || t('repoProgressTitle') }}</span>
            <span>{{ progressPct(repoProgress) }}%</span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-slate-700">
            <div class="h-full bg-cyan-400 transition-all duration-200" :style="{ width: `${progressPct(repoProgress)}%` }" />
          </div>
          <div class="mt-1 text-[11px] text-slate-200">{{ repoProgress.message || '' }}</div>
          <div class="mt-1 text-[11px] text-slate-300">
            {{ t('speedLabel') }}: {{ formatSpeed(repoProgress.speed_bps) }} • {{ t('elapsedLabel') }}: {{ formatDuration(repoProgress.elapsed_sec) }} • {{ t('etaLabel') }}: {{ formatDuration(repoProgress.eta_sec) }}
          </div>
        </div>

        <div v-if="defaultsLoading" class="mt-5 flex items-center justify-center rounded-xl border border-slate-700 bg-slate-800/60 py-10">
          <div class="flex items-center gap-3 text-sm text-slate-200">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-slate-500 border-t-cyan-400"></span>
            <span>{{ t('loading') }}</span>
          </div>
        </div>

        <div v-else class="mt-3 grid gap-2 rounded-xl border border-slate-700 bg-slate-800/60 p-3 text-xs text-slate-200">
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
