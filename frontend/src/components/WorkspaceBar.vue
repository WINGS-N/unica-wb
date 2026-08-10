<script setup>
import { ref } from 'vue'
import { Check, ChevronDown, Layers, Settings2 } from 'lucide-vue-next'
import SamsungModal from './ui/SamsungModal.vue'
import SamsungButton from './ui/SamsungButton.vue'
import StatusPill from './ui/StatusPill.vue'
import { t } from '../lang/index.js'
import { openOverlay } from '../stores/nav.js'
import { activeWorkspace, activeWorkspaceId, runningJobsCount, selectWorkspace, workspaces } from '../stores/app.js'

const pickerOpen = ref(false)

async function pick(id) {
  pickerOpen.value = false
  await selectWorkspace(id)
}

function manage() {
  pickerOpen.value = false
  openOverlay('workspaces')
}
</script>

<template>
  <header class="app-bar">
    <div class="app-bar-inner">
      <button type="button" class="chip-button min-w-0 flex-1 justify-start sm:max-w-xs" @click="pickerOpen = true">
        <Layers :size="15" class="shrink-0" />
        <span class="min-w-0 truncate text-un1ca-text">{{ activeWorkspace?.name || t('noWorkspace') }}</span>
        <ChevronDown :size="14" class="ml-auto shrink-0" />
      </button>
      <StatusPill v-if="runningJobsCount" tone="warning">{{ runningJobsCount }}</StatusPill>
    </div>
  </header>

  <SamsungModal :open="pickerOpen" :title="t('workspaces')" @close="pickerOpen = false">
    <div class="list">
      <button
        v-for="ws in workspaces"
        :key="ws.id"
        type="button"
        class="list-row is-clickable flex items-center gap-3"
        :class="{ 'is-selected': ws.id === activeWorkspaceId }"
        @click="pick(ws.id)"
      >
        <Check v-if="ws.id === activeWorkspaceId" :size="16" class="shrink-0 text-un1ca-accent" />
        <span class="min-w-0 flex-1">
          <span class="list-row-title block truncate">{{ ws.name }}</span>
          <span class="list-row-meta block truncate font-mono">{{ ws.root_path }}</span>
        </span>
        <StatusPill :tone="ws.repo_exists ? 'success' : 'warning'" :dot="false">
          {{ ws.repo_exists ? t('repoReady') : t('repoMissing') }}
        </StatusPill>
      </button>
    </div>
    <template #actions>
      <SamsungButton variant="primary" @click="manage">
        <Settings2 :size="15" /> {{ t('workspaceManage') }}
      </SamsungButton>
    </template>
  </SamsungModal>
</template>
