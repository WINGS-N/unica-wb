<script setup>
defineProps({
  modelValue: { type: [String, Number], default: '' },
  label: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  type: { type: String, default: 'text' },
  min: { type: [String, Number], default: undefined },
  disabled: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  mono: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'enter'])
</script>

<template>
  <label class="input-field">
    <span v-if="label" class="field-label">{{ label }}</span>
    <input
      class="text-input"
      :class="mono ? 'font-mono text-[13px]' : ''"
      :type="type"
      :min="min"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      @input="emit('update:modelValue', type === 'number' ? Number($event.target.value) || 0 : $event.target.value)"
      @keydown.enter.prevent="emit('enter')"
    />
    <span v-if="hint" class="form-hint mt-1">{{ hint }}</span>
  </label>
</template>
