<script setup>
import { Check } from 'lucide-vue-next'

defineProps({
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  label: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <label class="oneui-checkbox" :class="{ 'is-disabled': disabled }">
    <input
      class="oneui-input-hidden"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      @change="emit('update:modelValue', $event.target.checked)"
    />
    <span class="oneui-checkbox-box"><Check v-if="modelValue" :size="14" :stroke-width="3" class="text-white" /></span>
    <span v-if="label || $slots.default" class="oneui-checkbox-label"
      ><slot>{{ label }}</slot></span
    >
  </label>
</template>
