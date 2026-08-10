<script setup>
import { onBeforeUnmount, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, required: true },
  title: { type: String, default: '' },
  dismissible: { type: Boolean, default: true }
})

const emit = defineEmits(['close'])

function onKey(event) {
  if (event.key === 'Escape' && props.open && props.dismissible) emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKey)
    else window.removeEventListener('keydown', onKey)
  },
  { immediate: true }
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="modal-fade">
    <div v-if="open" class="modal-backdrop" @click.self="dismissible && emit('close')">
      <div class="modal-card" role="dialog" aria-modal="true">
        <div v-if="title || $slots.header" class="mb-4 flex items-start justify-between gap-3">
          <h3 class="modal-title">
            <slot name="header">{{ title }}</slot>
          </h3>
        </div>
        <slot />
        <div v-if="$slots.actions" class="mt-6 flex flex-wrap justify-end gap-2">
          <slot name="actions" />
        </div>
      </div>
    </div>
  </Transition>
</template>
