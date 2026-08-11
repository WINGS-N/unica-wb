<script setup>
import { computed } from 'vue'
import { CircleHelp, Download, Layers, ListChecks, Octagon, PackageOpen, Sparkles, Trash2 } from 'lucide-vue-next'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import OneuiSelect from '../components/ui/OneuiSelect.vue'
import { t } from '../lang/index.js'
import { downloadUrl } from '../stores/api.js'
import { goTab, openOverlay } from '../stores/nav.js'
import {
  buildProgress,
  capabilities,
  filteredJobs,
  formatDateTime,
  hasJobDebloatChanges,
  hasJobFFOverrides,
  hasJobModsConfig,
  jobTitle,
  jobs,
  jobsFilterBuildOnly,
  jobsFilterDevice,
  jobsFilterSucceededOnly,
  jobsLoading,
  loadDebloatFromJob,
  loadFFFromJob,
  loadModsFromJob,
  openDeleteArtifactModal,
  openIncrementalModal,
  openStopModal,
  parseJobMods,
  parseJobDebloatDisabled,
  parseJobFFOverrides,
  parseJobModsDisabled,
  queueDsuPackage,
  selectJob,
  selectedJob,
  targetOptions
} from '../stores/app.js'

const deviceOptions = computed(() => [
  { value: '', label: t('allDevices') },
  ...targetOptions.value.map((x) => ({ value: x.code, label: x.code }))
])

function onSelect(job) {
  selectJob(job)
  goTab('logs')
}

function openHints(job) {
  openOverlay('hints', { jobId: job.id })
}

function openJobMods(job) {
  openOverlay('jobMods', { jobId: job.id })
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="section-kicker">{{ jobs.length }} {{ t('entries') }}</p>
        <h1 class="page-title">{{ t('jobs') }}</h1>
      </div>
    </header>

    <div class="flex flex-wrap items-center gap-2">
      <button
        type="button"
        class="chip-button"
        :class="{ 'is-active': jobsFilterBuildOnly }"
        @click="jobsFilterBuildOnly = !jobsFilterBuildOnly"
      >
        {{ t('build') }}
      </button>
      <button
        type="button"
        class="chip-button"
        :class="{ 'is-active': jobsFilterSucceededOnly }"
        @click="jobsFilterSucceededOnly = !jobsFilterSucceededOnly"
      >
        {{ t('succeeded') }}
      </button>
      <OneuiSelect v-model="jobsFilterDevice" :options="deviceOptions" />
    </div>

    <div v-if="jobsLoading && !filteredJobs.length" class="loading-block"><SamsungLoader /></div>

    <div v-else-if="!filteredJobs.length" class="empty-state">{{ t('noJobs') }}</div>

    <div v-else class="list">
      <article
        v-for="job in filteredJobs"
        :key="job.id"
        class="list-row is-clickable"
        :class="{ 'is-selected': selectedJob?.id === job.id }"
        @click="onSelect(job)"
      >
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <p class="list-row-title">{{ jobTitle(job) }}</p>
            <p class="list-row-meta font-mono">{{ job.id }}</p>
            <p class="list-row-meta">{{ formatDateTime(job.created_at) }}</p>
          </div>
          <StatusPill :status="job.status" />
        </div>

        <ProgressBar
          v-if="buildProgress[job.id]"
          class="mt-3"
          :progress="buildProgress[job.id]"
          :title="t(`buildStage_${buildProgress[job.id]?.stage}`)"
        />

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <button
            v-if="job.status === 'running' || job.status === 'queued'"
            type="button"
            class="chip-button is-danger"
            @click.stop="openStopModal(job)"
          >
            <Octagon :size="14" /> {{ t('stop') }}
          </button>
          <a
            v-if="job.artifact_path"
            class="chip-button is-success"
            :href="downloadUrl(`/jobs/${job.id}/artifact`)"
            @click.stop
          >
            <Download :size="14" /> {{ t('downloadZip') }}
          </a>
          <button
            v-if="job.artifact_path || job.target_files_path"
            type="button"
            class="chip-button is-danger"
            @click.stop="openDeleteArtifactModal(job)"
          >
            <Trash2 :size="14" /> {{ t('delete') }}
          </button>
          <button
            v-if="job.status === 'succeeded' && job.target_files_path"
            type="button"
            class="chip-button is-accent"
            @click.stop="openIncrementalModal(job)"
          >
            <Layers :size="14" /> {{ t('incrementalZip') }}
          </button>
          <button
            v-if="capabilities.dsu_package && job.status === 'succeeded' && job.target_files_path"
            type="button"
            class="chip-button is-accent"
            @click.stop="queueDsuPackage(job)"
          >
            <PackageOpen :size="14" /> {{ t('dsuPackage') }}
          </button>
          <button
            v-if="job.status === 'failed'"
            type="button"
            class="chip-button is-warning"
            @click.stop="openHints(job)"
          >
            <CircleHelp :size="14" /> {{ t('whyBuildFailed') }}
          </button>
          <button v-if="parseJobMods(job).length" type="button" class="chip-button" @click.stop="openJobMods(job)">
            {{ t('mods') }} ({{ parseJobMods(job).length }})
          </button>
          <button
            v-if="hasJobModsConfig(job)"
            type="button"
            class="chip-button is-info"
            @click.stop="loadModsFromJob(job)"
          >
            <ListChecks :size="14" /> {{ t('useModlist') }} ({{ parseJobModsDisabled(job).length }})
          </button>
          <button
            v-if="hasJobDebloatChanges(job)"
            type="button"
            class="chip-button is-info"
            @click.stop="loadDebloatFromJob(job)"
          >
            <Trash2 :size="14" /> {{ t('loadDebloat') }} ({{ parseJobDebloatDisabled(job).length }})
          </button>
          <button
            v-if="hasJobFFOverrides(job)"
            type="button"
            class="chip-button is-info"
            @click.stop="loadFFFromJob(job)"
          >
            <Sparkles :size="14" /> {{ t('useFF') }} ({{ Object.keys(parseJobFFOverrides(job)).length }})
          </button>
        </div>

        <p v-if="job.error" class="state-error mt-2">{{ job.error }}</p>
      </article>
    </div>
  </div>
</template>
