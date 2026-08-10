<script setup>
import { confirmState, resolveConfirm } from '../../stores/confirm.js'
import SamsungButton from './SamsungButton.vue'
import SamsungModal from './SamsungModal.vue'
</script>

<template>
  <SamsungModal :open="Boolean(confirmState)" :title="confirmState?.title || ''" @close="resolveConfirm(false)">
    <p v-if="confirmState?.message" class="text-[14px] leading-relaxed text-un1ca-muted">{{ confirmState.message }}</p>
    <template #actions>
      <SamsungButton variant="secondary" @click="resolveConfirm(false)">{{ confirmState?.cancelText }}</SamsungButton>
      <SamsungButton :variant="confirmState?.danger ? 'danger' : 'primary'" @click="resolveConfirm(true)">
        {{ confirmState?.confirmText }}
      </SamsungButton>
    </template>
  </SamsungModal>
</template>
