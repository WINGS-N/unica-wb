<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Hammer, HardDrive, ListTodo, ScrollText, Settings } from 'lucide-vue-next'

import WorkspaceBar from './components/WorkspaceBar.vue'
import ToastHost from './components/ui/ToastHost.vue'
import ConfirmDialog from './components/ui/ConfirmDialog.vue'
import StopJobDialog from './components/StopJobDialog.vue'
import LoginDialog from './components/LoginDialog.vue'

import { closeOverlay, goTab } from './stores/nav.js'
import { language, setLanguage, t } from './lang/index.js'
import { runningJobsCount, startApp, stopApp } from './stores/app.js'

const TABS = [
  { id: 'build', labelKey: 'tabBuild', icon: Hammer },
  { id: 'jobs', labelKey: 'tabJobs', icon: ListTodo },
  { id: 'logs', labelKey: 'tabLogs', icon: ScrollText },
  { id: 'firmware', labelKey: 'tabFirmware', icon: HardDrive },
  { id: 'settings', labelKey: 'tabSettings', icon: Settings }
]

const route = useRoute()
const isOverlay = computed(() => Boolean(route.meta?.overlay))
const currentTab = computed(() => route.meta?.tab || 'build')

function onKey(event) {
  if (event.key === 'Escape' && isOverlay.value) closeOverlay()
}

onMounted(() => {
  setLanguage(language.value)
  window.addEventListener('keydown', onKey)
  startApp()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  stopApp()
})
</script>

<template>
  <div class="app-shell">
    <RouterView v-slot="{ Component }">
      <Transition name="overlay-slide" mode="out-in">
        <component :is="Component" v-if="isOverlay" :key="route.fullPath" class="min-h-0 flex-1" />

        <div v-else :key="currentTab" class="flex min-h-0 flex-1 flex-col">
          <WorkspaceBar />
          <main class="app-main">
            <component :is="Component" />
          </main>
        </div>
      </Transition>
    </RouterView>

    <nav v-if="!isOverlay" class="app-nav">
      <div class="app-nav-inner">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          class="app-nav-item"
          :class="{ 'is-active': tab.id === currentTab }"
          @click="goTab(tab.id)"
        >
          <span class="relative">
            <component :is="tab.icon" :size="21" :stroke-width="tab.id === currentTab ? 2.4 : 1.9" />
            <span v-if="tab.id === 'jobs' && runningJobsCount" class="app-nav-dot bg-un1ca-accent" />
          </span>
          <span class="app-nav-label">{{ t(tab.labelKey) }}</span>
        </button>
      </div>
    </nav>

    <ToastHost />
    <ConfirmDialog />
    <StopJobDialog />
    <LoginDialog />
  </div>
</template>
