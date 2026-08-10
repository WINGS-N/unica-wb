<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  label: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <label class="oneui-switch" :class="{ 'is-disabled': disabled }">
    <input
      class="oneui-input-hidden"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      @change="emit('update:modelValue', $event.target.checked)"
    />
    <span class="oneui-switch-track"><span class="oneui-switch-thumb" /></span>
    <span v-if="label" class="ml-2 text-[14px] text-un1ca-mutedStrong">{{ label }}</span>
  </label>
</template>
