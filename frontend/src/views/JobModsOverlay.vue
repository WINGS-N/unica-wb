<script setup>
import { computed } from 'vue'
import OverlayView from '../components/ui/OverlayView.vue'
import { t } from '../lang/index.js'
import { jobs, parseJobMods } from '../stores/app.js'

const props = defineProps({
  jobId: { type: String, required: true }
})

const job = computed(() => jobs.value.find((x) => x.id === props.jobId) || null)
const modules = computed(() => parseJobMods(job.value))
</script>

<template>
  <OverlayView :title="t('extraModsForJob')">
    <p class="page-subtitle font-mono">{{ jobId }}</p>

    <div v-if="!modules.length" class="empty-state">{{ t('noEntries') }}</div>

    <div v-else class="list">
      <div v-for="m in modules" :key="`${m.module_dir}-${m.id}`" class="list-row">
        <p class="list-row-title">{{ m.name || m.module_dir }}</p>
        <p class="list-row-meta font-mono">{{ m.module_dir }}</p>
        <p class="list-row-meta">
          id: {{ m.id || 'n/a' }} - ver: {{ m.version || 'n/a' }} ({{ m.versionCode || 'n/a' }})
        </p>
        <p class="list-row-meta">{{ m.author || 'n/a' }}</p>
        <p v-if="m.description" class="list-row-meta">{{ m.description }}</p>
      </div>
    </div>
  </OverlayView>
</template>
