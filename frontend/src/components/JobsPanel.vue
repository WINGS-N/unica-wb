<script setup>
defineProps({
  t: {type: Function, required: true},
  jobsLoading: {type: Boolean, required: true},
  jobs: {type: Array, required: true},
  targetOptions: {type: Array, default: () => []},
  filterBuildOnly: {type: Boolean, required: true},
  filterSucceededOnly: {type: Boolean, required: true},
  filterDevice: {type: String, default: ''},
  jobsMaxHeight: {type: Number, default: null},
  selectedJob: {type: Object, default: null},
  jobTitle: {type: Function, required: true},
  parseJobMods: {type: Function, required: true},
  parseJobModsDisabled: {type: Function, required: true},
  hasJobModsConfig: {type: Function, required: true},
  parseJobDebloatDisabled: {type: Function, required: true},
  parseJobDebloatAddSystem: {type: Function, required: true},
  parseJobDebloatAddProduct: {type: Function, required: true},
  hasJobDebloatChanges: {type: Function, required: true},
  parseJobFfOverrides: {type: Function, required: true},
  hasJobFfOverrides: {type: Function, required: true},
  jobArtifactUrl: {type: Function, required: true},
  buildProgress: {type: Object, required: true}
})

const emit = defineEmits([
  'select-job',
  'open-stop',
  'open-mods',
  'load-mods',
  'load-debloat',
  'load-ff',
  'update:filterBuildOnly',
  'update:filterSucceededOnly',
  'update:filterDevice'
])
</script>

<template>
  <div class="flex min-h-[50vh] flex-col rounded-2xl border border-slate-800 bg-slate-900/70 p-4 sm:p-6 lg:col-span-2"
       :style="jobsMaxHeight ? { maxHeight: `${jobsMaxHeight}px` } : undefined">
    <h2 class="flex items-center gap-2 text-xl font-semibold">
      <span>{{ t('jobs') }}</span>
      <span v-if="jobsLoading" class="h-4 w-4 animate-spin rounded-full border border-slate-500 border-t-cyan-400"/>
    </h2>
    <div class="mt-3 flex flex-wrap items-center gap-2">
      <button
          type="button"
          class="rounded-md border px-2 py-1 text-xs font-semibold uppercase"
          :class="filterBuildOnly ? 'border-cyan-400 bg-cyan-500/20 text-cyan-300' : 'border-slate-700 bg-slate-800/70 text-slate-300'"
          @click="$emit('update:filterBuildOnly', !filterBuildOnly)"
      >
        {{ t('build') }}
      </button>
      <button
          type="button"
          class="rounded-md border px-2 py-1 text-xs font-semibold uppercase"
          :class="filterSucceededOnly ? 'border-emerald-400 bg-emerald-500/20 text-emerald-300' : 'border-slate-700 bg-slate-800/70 text-slate-300'"
          @click="$emit('update:filterSucceededOnly', !filterSucceededOnly)"
      >
        {{ t('succeeded') }}
      </button>
      <select
          class="rounded-md border border-slate-700 bg-slate-800/70 px-2 py-1 text-xs text-slate-200"
          :value="filterDevice"
          @change="$emit('update:filterDevice', $event.target.value)"
      >
        <option value="">{{ t('allDevices') }}</option>
        <option v-for="opt in targetOptions" :key="opt.code" :value="opt.code">{{ opt.code }}</option>
      </select>
    </div>
    <div class="mt-3 flex min-h-0 flex-1 flex-col gap-2 overflow-auto pr-1">
      <div v-if="jobsLoading && !jobs.length"
           class="rounded-xl border border-slate-700 bg-slate-800/70 p-3 text-sm text-slate-300">{{ t('loading') }}
      </div>
      <button
          v-for="job in jobs"
          :key="job.id"
          class="w-full rounded-xl border px-3 py-2 text-left"
          :class="selectedJob?.id === job.id ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 bg-slate-800/70'"
          @click="$emit('select-job', job)"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="font-medium">{{ jobTitle(job) }}</span>
          <div class="flex flex-col items-end gap-2">
            <div class="inline-flex items-center gap-2">
              <button v-if="job.status === 'running' || job.status === 'queued'"
                      class="rounded-md border border-red-400/60 bg-red-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-red-300 hover:bg-red-500/30"
                      @click.stop="$emit('open-stop', job, $event)">{{ t('stop') }}
              </button>
              <button v-if="parseJobMods(job).length"
                      class="rounded-md border border-cyan-400/60 bg-cyan-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-cyan-300 hover:bg-cyan-500/30"
                      @click.stop="$emit('open-mods', job, $event)">{{ t('mods') }}
              </button>
              <button v-if="hasJobModsConfig(job)"
                      class="rounded-md border border-sky-400/60 bg-sky-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-sky-300 hover:bg-sky-500/30"
                      @click.stop="$emit('load-mods', job, $event)">{{ t('useModlist') }}
              </button>
              <button v-if="hasJobDebloatChanges(job)"
                      class="rounded-md border border-amber-400/60 bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-amber-300 hover:bg-amber-500/30"
                      @click.stop="$emit('load-debloat', job, $event)">{{ t('loadDebloat') }}
              </button>
              <button v-if="hasJobFfOverrides(job)"
                      class="rounded-md border border-cyan-400/60 bg-cyan-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-cyan-300 hover:bg-cyan-500/30"
                      @click.stop="$emit('load-ff', job, $event)">{{ t('useFF') }}
              </button>
              <a v-if="job.artifact_path" :href="jobArtifactUrl(job)"
                 class="rounded-md border border-emerald-400/60 bg-emerald-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300 hover:bg-emerald-500/30"
                 @click.stop>{{ t('downloadZip') }}</a>
            </div>
            <div class="text-xs uppercase text-slate-300">
              <span class="inline-flex items-center gap-2"><span class="h-2 w-2 rounded-full"
                                                                 :class="job.status === 'succeeded' ? 'bg-emerald-400' : (job.status === 'failed' || job.status === 'canceled') ? 'bg-red-400' : 'animate-pulse bg-amber-400'"/>{{
                  job.status
                }}</span>
            </div>
          </div>
        </div>
        <div class="mt-1 text-xs text-slate-400">{{ job.id }}</div>
        <div v-if="buildProgress[job.id] && (job.status === 'running' || job.status === 'queued')" class="mt-2">
          <div class="mb-1 flex items-center justify-between text-[10px] text-cyan-300">
            <span>{{ buildProgress[job.id]?.stage || 'build' }} • {{
                Math.round(buildProgress[job.id]?.percent || 0)
              }}%</span>
          </div>
          <div class="h-1.5 overflow-hidden rounded-full bg-slate-700">
            <div class="h-full bg-cyan-400 transition-all duration-200"
                 :style="{ width: `${Math.max(4, Math.round(buildProgress[job.id]?.percent || 0))}%` }"/>
          </div>
        </div>
        <div v-if="parseJobMods(job).length" class="mt-2 text-[11px] text-cyan-300">Extra mods
          ({{ parseJobMods(job).length }}): {{ parseJobMods(job).map((m) => m.name || m.module_dir).join(', ') }}
        </div>
        <div v-if="hasJobModsConfig(job)" class="mt-1 text-[11px] text-sky-300">{{ t('modsDisabledShort') }}:
          {{ parseJobModsDisabled(job).length }} {{ t('entries') }}
        </div>
        <div v-if="parseJobDebloatDisabled(job).length" class="mt-1 text-[11px] text-amber-300">
          {{ t('debloatDisabledShort') }}: {{ parseJobDebloatDisabled(job).length }} {{ t('entries') }}
        </div>
        <div v-if="parseJobDebloatAddSystem(job).length || parseJobDebloatAddProduct(job).length"
             class="mt-1 text-[11px] text-amber-200">
          +{{ parseJobDebloatAddSystem(job).length + parseJobDebloatAddProduct(job).length }} {{
            t('customDebloatPaths')
          }}
        </div>
        <div v-if="hasJobFfOverrides(job)" class="mt-1 text-[11px] text-cyan-300">
          {{ t('ffOverridesForBuild') }}: {{ Object.keys(parseJobFfOverrides(job)).length }} {{ t('entries') }}
        </div>
      </button>
    </div>
  </div>
</template>
