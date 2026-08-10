<script setup>
import { ArrowDownToLine, GitPullRequestArrow, RotateCcw, Trash2 } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import { t } from '../lang/index.js'
import {
  activeRepoProgress,
  cloneRepository,
  currentCommit,
  currentCommitDetails,
  deleteRepository,
  formatBytes,
  pullRepository,
  recloneRepository,
  repoActionBusy,
  repoInfo,
  repoSync,
  repoSyncText,
  repoSyncTone,
  updateRepoSubmodules,
  updateRepoUrlInput
} from '../stores/app.js'
</script>

<template>
  <OverlayView :title="t('repository')">
    <SectionCard :title="t('repoUrlLabel')">
      <OneuiInput
        :model-value="repoInfo.git_url || ''"
        mono
        placeholder="https://github.com/user/UN1CA.git"
        @update:model-value="updateRepoUrlInput"
      />
      <p class="form-hint">
        {{ t('repoRefLabel') }}: <span class="mono-chip">{{ repoInfo.git_ref || 'n/a' }}</span>
      </p>

      <div class="actions-row">
        <SamsungButton variant="primary" :disabled="repoActionBusy" @click="cloneRepository">
          <ArrowDownToLine :size="16" /> {{ t('repoClone') }}
        </SamsungButton>
        <SamsungButton :disabled="repoActionBusy" @click="pullRepository">
          <GitPullRequestArrow :size="16" /> {{ t('pullRepo') }}
        </SamsungButton>
        <SamsungButton :disabled="repoActionBusy" @click="updateRepoSubmodules">
          {{ t('updateSubmodules') }}
        </SamsungButton>
      </div>
      <p class="form-hint">{{ t('repoCloneHint') }}</p>
    </SectionCard>

    <SectionCard :title="t('repoState')">
      <ProgressBar v-if="activeRepoProgress" :progress="activeRepoProgress" />
      <div class="keyvals">
        <div class="keyval">
          <span class="keyval-label">{{ t('repoSyncStatus') }}</span>
          <span class="keyval-value"
            ><StatusPill :tone="repoSyncTone()" :dot="false">{{ repoSyncText() }}</StatusPill></span
          >
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('repoSyncRemote') }}</span>
          <span class="keyval-value mono">{{ repoSync.remote_ref || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('repoPathLabel') }}</span>
          <span class="keyval-value mono">{{ repoInfo.repo_path || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('sizeLabel') }}</span>
          <span class="keyval-value">{{ formatBytes(repoInfo.repo_size_bytes || 0) }}</span>
        </div>
      </div>
    </SectionCard>

    <SectionCard :title="t('currentCommit')">
      <div class="keyvals">
        <div class="keyval">
          <span class="keyval-label">{{ t('branchLabel') }}</span>
          <span class="keyval-value mono">{{ currentCommitDetails.branch || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('shortHashLabel') }}</span>
          <span class="keyval-value mono">{{ currentCommitDetails.short_hash || currentCommit }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('fullHashLabel') }}</span>
          <span class="keyval-value mono">{{ currentCommitDetails.full_hash || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('commitTitleLabel') }}</span>
          <span class="keyval-value">{{ currentCommitDetails.subject || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('authorLabel') }}</span>
          <span class="keyval-value">{{ currentCommitDetails.author_name || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('committerLabel') }}</span>
          <span class="keyval-value">{{ currentCommitDetails.committer_name || 'n/a' }}</span>
        </div>
      </div>
      <pre v-if="currentCommitDetails.body" class="log-pane max-h-52">{{ currentCommitDetails.body }}</pre>
    </SectionCard>

    <SectionCard :title="t('dangerZone')" :subtitle="t('dangerZoneHint')">
      <div class="actions-row">
        <SamsungButton variant="danger" :disabled="repoActionBusy" @click="recloneRepository">
          <RotateCcw :size="16" /> {{ t('repoReclone') }}
        </SamsungButton>
        <SamsungButton variant="danger" :disabled="repoActionBusy" @click="deleteRepository('repo_only')">
          <Trash2 :size="16" /> {{ t('deleteRepoKeepOut') }}
        </SamsungButton>
        <SamsungButton variant="danger" :disabled="repoActionBusy" @click="deleteRepository('repo_with_out')">
          <Trash2 :size="16" /> {{ t('deleteRepoWithOut') }}
        </SamsungButton>
      </div>
    </SectionCard>
  </OverlayView>
</template>
