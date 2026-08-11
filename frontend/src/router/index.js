import { createRouter, createWebHistory } from 'vue-router'

import BuildView from '../views/BuildView.vue'
import JobsView from '../views/JobsView.vue'
import LogsView from '../views/LogsView.vue'
import FirmwareView from '../views/FirmwareView.vue'
import SettingsView from '../views/SettingsView.vue'

import ModsOverlay from '../views/ModsOverlay.vue'
import DebloatOverlay from '../views/DebloatOverlay.vue'
import FloatingFeaturesOverlay from '../views/FloatingFeaturesOverlay.vue'
import LocalUpdateOverlay from '../views/LocalUpdateOverlay.vue'
import ArtifactsOverlay from '../views/ArtifactsOverlay.vue'
import UploadModsOverlay from '../views/UploadModsOverlay.vue'
import WorkspacesOverlay from '../views/WorkspacesOverlay.vue'
import AboutOverlay from '../views/AboutOverlay.vue'
import LicensesOverlay from '../views/LicensesOverlay.vue'
import RepoOverlay from '../views/RepoOverlay.vue'
import BuildHintsOverlay from '../views/BuildHintsOverlay.vue'
import JobModsOverlay from '../views/JobModsOverlay.vue'

// Tabs live at the top level; everything reachable from them is a full-screen
// route of its own, so every screen is linkable and the browser back button
// does what it looks like it should. meta.tab keeps the tab bar highlighted
// while a sub-screen is open, meta.overlay hides the tab bar
export const TAB_ROUTES = ['build', 'jobs', 'logs', 'firmware', 'settings']

const routes = [
  { path: '/', redirect: '/build' },
  { path: '/build', name: 'build', component: BuildView, meta: { tab: 'build' } },
  { path: '/jobs', name: 'jobs', component: JobsView, meta: { tab: 'jobs' } },
  { path: '/logs', name: 'logs', component: LogsView, meta: { tab: 'logs' } },
  { path: '/firmware', name: 'firmware', component: FirmwareView, meta: { tab: 'firmware' } },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { tab: 'settings' } },

  { path: '/build/mods', name: 'mods', component: ModsOverlay, meta: { tab: 'build', overlay: true } },
  { path: '/build/debloat', name: 'debloat', component: DebloatOverlay, meta: { tab: 'build', overlay: true } },
  {
    path: '/build/features',
    name: 'features',
    component: FloatingFeaturesOverlay,
    meta: { tab: 'build', overlay: true }
  },
  {
    path: '/build/mods/upload',
    name: 'modsUpload',
    component: UploadModsOverlay,
    meta: { tab: 'build', overlay: true }
  },
  { path: '/build/artifacts', name: 'artifacts', component: ArtifactsOverlay, meta: { tab: 'build', overlay: true } },
  {
    path: '/build/artifacts/update',
    name: 'localUpdate',
    component: LocalUpdateOverlay,
    meta: { tab: 'build', overlay: true }
  },
  { path: '/build/repo', name: 'repo', component: RepoOverlay, meta: { tab: 'build', overlay: true } },
  {
    path: '/settings/workspaces',
    name: 'workspaces',
    component: WorkspacesOverlay,
    meta: { tab: 'settings', overlay: true }
  },
  {
    path: '/settings/about',
    name: 'about',
    component: AboutOverlay,
    meta: { tab: 'settings', overlay: true }
  },
  {
    path: '/settings/about/licenses',
    name: 'licenses',
    component: LicensesOverlay,
    meta: { tab: 'settings', overlay: true }
  },
  {
    path: '/jobs/:jobId/hints',
    name: 'hints',
    component: BuildHintsOverlay,
    props: true,
    meta: { tab: 'jobs', overlay: true }
  },
  {
    path: '/jobs/:jobId/mods',
    name: 'jobMods',
    component: JobModsOverlay,
    props: true,
    meta: { tab: 'jobs', overlay: true }
  },

  { path: '/:pathMatch(.*)*', redirect: '/build' }
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})
