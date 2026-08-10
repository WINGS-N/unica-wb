<script setup>
import { ChevronDown } from 'lucide-vue-next'

defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  label: { type: String, default: '' },
  block: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'change'])

function onChange(event) {
  emit('update:modelValue', event.target.value)
  emit('change', event.target.value)
}
</script>

<template>
  <div class="input-field" :class="block ? 'w-full' : ''">
    <span v-if="label" class="field-label">{{ label }}</span>
    <div class="oneui-select-wrapper" :class="block ? 'w-full' : ''">
      <select class="oneui-select" :value="modelValue" :disabled="disabled" @change="onChange">
        <option v-for="opt in options" :key="String(opt.value)" :value="opt.value">{{ opt.label }}</option>
      </select>
      <ChevronDown class="oneui-select-chevron" :size="16" />
    </div>
  </div>
</template>
