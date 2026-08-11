<script setup>
import { onMounted, ref } from 'vue'
import { Check, Pencil, Plus, Trash2 } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import SamsungButton from '../components/ui/SamsungButton.vue'
import SamsungModal from '../components/ui/SamsungModal.vue'
import OneuiInput from '../components/ui/OneuiInput.vue'
import OneuiSwitch from '../components/ui/OneuiSwitch.vue'
import OneuiCheckbox from '../components/ui/OneuiCheckbox.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { t } from '../lang/index.js'
import { confirm } from '../stores/confirm.js'
import { showToast } from '../stores/toast.js'
import {
  activeWorkspaceId,
  createWorkspace,
  deleteWorkspace,
  fetchWorkspaces,
  selectWorkspace,
  sharedCacheRoot,
  updateWorkspace,
  workspaces,
  workspacesLoading,
  workspacesRoot
} from '../stores/app.js'

const editorOpen = ref(false)
const editorBusy = ref(false)
const editing = ref(null)
const formName = ref('')
const formUrl = ref('')
const formRef = ref('sixteen')
const formUsername = ref('')
const formToken = ref('')
const formShared = ref(true)
const formCloneNow = ref(true)

function openCreate() {
  editing.value = null
  formName.value = ''
  formUrl.value = 'https://github.com/salvogiangri/UN1CA.git'
  formRef.value = 'sixteen'
  formUsername.value = ''
  formToken.value = ''
  formShared.value = true
  formCloneNow.value = true
  editorOpen.value = true
}

function openEdit(ws) {
  editing.value = ws
  formName.value = ws.name
  formUrl.value = ws.git_url
  formRef.value = ws.git_ref
  formUsername.value = ws.git_username
  formToken.value = ''
  formShared.value = ws.shared_fw_cache
  editorOpen.value = true
}

async function save() {
  editorBusy.value = true
  try {
    if (editing.value) {
      const patch = {
        name: formName.value,
        git_url: formUrl.value,
        git_ref: formRef.value,
        git_username: formUsername.value,
        shared_fw_cache: formShared.value
      }
      // An empty token field means "leave it alone", not "clear it"
      if (formToken.value) patch.git_token = formToken.value
      await updateWorkspace(editing.value.id, patch)
    } else {
      await createWorkspace({
        name: formName.value,
        git_url: formUrl.value,
        git_ref: formRef.value,
        git_username: formUsername.value,
        git_token: formToken.value,
        shared_fw_cache: formShared.value,
        clone_now: formCloneNow.value
      })
    }
    editorOpen.value = false
  } catch (e) {
    showToast(`${t('workspaceSaveFailed')}: ${e?.message || e}`, 'error')
  } finally {
    editorBusy.value = false
  }
}

async function remove(ws) {
  const withFiles = await confirm({
    title: t('workspaceDelete'),
    message: t('workspaceDeleteConfirm', { name: ws.name }),
    confirmText: t('workspaceDeleteWithFiles'),
    cancelText: t('cancel'),
    danger: true
  })
  if (!withFiles) return
  try {
    await deleteWorkspace(ws.id, true)
  } catch (e) {
    showToast(`${t('workspaceDeleteFailed')}: ${e?.message || e}`, 'error')
  }
}

onMounted(fetchWorkspaces)
</script>

<template>
  <OverlayView :title="t('workspaces')">
    <template #actions>
      <SamsungButton small variant="primary" @click="openCreate">
        <Plus :size="15" /> {{ t('workspaceNew') }}
      </SamsungButton>
    </template>

    <p class="page-subtitle">{{ t('workspacesHint') }}</p>

    <div v-if="workspacesLoading && !workspaces.length" class="loading-block"><SamsungLoader /></div>

    <div class="list">
      <article
        v-for="ws in workspaces"
        :key="ws.id"
        class="list-row is-clickable"
        :class="{ 'is-selected': ws.id === activeWorkspaceId }"
        @click="selectWorkspace(ws.id)"
      >
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <p class="list-row-title flex items-center gap-2">
              <Check v-if="ws.id === activeWorkspaceId" :size="16" class="text-un1ca-accent" />
              {{ ws.name }}
            </p>
            <p class="list-row-meta font-mono">{{ ws.root_path }}</p>
            <p class="list-row-meta font-mono">{{ ws.git_url }} - {{ ws.git_ref }}</p>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-1.5">
            <StatusPill :tone="ws.repo_exists ? 'success' : 'warning'" :dot="false">
              {{ ws.repo_exists ? t('repoReady') : t('repoMissing') }}
            </StatusPill>
            <StatusPill :tone="ws.shared_fw_cache ? 'info' : ''" :dot="false">
              {{ ws.shared_fw_cache ? t('sharedCacheOn') : t('sharedCacheOff') }}
            </StatusPill>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-2">
          <button type="button" class="chip-button" @click.stop="openEdit(ws)">
            <Pencil :size="14" /> {{ t('edit') }}
          </button>
          <button v-if="workspaces.length > 1" type="button" class="chip-button is-danger" @click.stop="remove(ws)">
            <Trash2 :size="14" /> {{ t('delete') }}
          </button>
        </div>
      </article>
    </div>

    <SectionCard :title="t('workspacePaths')">
      <div class="keyvals">
        <div class="keyval">
          <span class="keyval-label">{{ t('workspacesRoot') }}</span>
          <span class="keyval-value mono">{{ workspacesRoot || 'n/a' }}</span>
        </div>
        <div class="keyval">
          <span class="keyval-label">{{ t('sharedCacheRoot') }}</span>
          <span class="keyval-value mono">{{ sharedCacheRoot || 'n/a' }}</span>
        </div>
      </div>
    </SectionCard>

    <SamsungModal
      :open="editorOpen"
      :title="editing ? t('workspaceEdit') : t('workspaceNew')"
      @close="editorOpen = false"
    >
      <div class="flex flex-col gap-4">
        <OneuiInput v-model="formName" :label="t('workspaceName')" />
        <OneuiInput v-model="formUrl" :label="t('repoUrlLabel')" mono />
        <OneuiInput v-model="formRef" :label="t('repoRefLabel')" mono />
        <OneuiInput v-model="formUsername" :label="t('repoUsername')" />
        <OneuiInput
          v-model="formToken"
          type="password"
          :label="t('repoToken')"
          :placeholder="editing ? t('repoTokenKeep') : ''"
        />
        <div class="form-section">
          <div class="form-row">
            <div class="min-w-0">
              <p class="form-label">{{ t('sharedFwCache') }}</p>
              <p class="form-hint">{{ t('sharedFwCacheHint') }}</p>
            </div>
            <OneuiSwitch v-model="formShared" />
          </div>
        </div>
        <OneuiCheckbox v-if="!editing" v-model="formCloneNow" :label="t('workspaceCloneNow')" />
      </div>
      <template #actions>
        <SamsungButton @click="editorOpen = false">{{ t('cancel') }}</SamsungButton>
        <SamsungButton variant="primary" :loading="editorBusy" @click="save">{{ t('save') }}</SamsungButton>
      </template>
    </SamsungModal>
  </OverlayView>
</template>
