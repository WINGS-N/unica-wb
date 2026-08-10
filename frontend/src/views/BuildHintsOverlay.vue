<script setup>
import { computed, onMounted, watch } from 'vue'
import OverlayView from '../components/ui/OverlayView.vue'
import SamsungLoader from '../components/ui/SamsungLoader.vue'
import { t } from '../lang/index.js'
import { buildHints, buildHintsLoading, jobs, loadBuildHints } from '../stores/app.js'

const props = defineProps({
  jobId: { type: String, required: true }
})

const job = computed(() => jobs.value.find((x) => x.id === props.jobId) || { id: props.jobId })

// The route carries the job id, so a deep link loads the hints on its own
function load() {
  loadBuildHints(job.value)
}

onMounted(load)
watch(() => props.jobId, load)
</script>

<template>
  <OverlayView :title="t('whyBuildFailed')">
    <p class="page-subtitle font-mono">{{ jobId }}</p>

    <div v-if="buildHintsLoading" class="loading-block"><SamsungLoader /></div>
    <div v-else-if="!buildHints.length" class="empty-state">{{ t('noHintsFound') }}</div>

    <div v-else class="list">
      <article v-for="hint in buildHints" :key="hint.id" class="list-row is-off">
        <p class="list-row-title text-un1ca-danger">{{ hint.title }}</p>
        <p class="muted mt-1">{{ hint.detail }}</p>
        <p class="mt-2 text-[13px]">{{ hint.suggestion }}</p>
      </article>
    </div>
  </OverlayView>
</template>
