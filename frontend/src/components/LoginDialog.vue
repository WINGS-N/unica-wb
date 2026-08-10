<script setup>
import SamsungModal from './ui/SamsungModal.vue'
import SamsungButton from './ui/SamsungButton.vue'
import OneuiInput from './ui/OneuiInput.vue'
import { t } from '../lang/index.js'
import { authBusy, authLoginPassword, loginWithPassword, unauthorizedOpen } from '../stores/app.js'
</script>

<template>
  <SamsungModal :open="unauthorizedOpen" :title="t('unauthorizedTitle')" :dismissible="false">
    <p class="text-[14px] text-un1ca-muted">{{ t('unauthorizedDesc') }}</p>
    <OneuiInput
      v-model="authLoginPassword"
      class="mt-4"
      type="password"
      :label="t('authPassword')"
      @enter="loginWithPassword"
    />
    <template #actions>
      <SamsungButton @click="unauthorizedOpen = false">{{ t('cancel') }}</SamsungButton>
      <SamsungButton variant="primary" :loading="authBusy" @click="loginWithPassword">{{
        t('authLogin')
      }}</SamsungButton>
    </template>
  </SamsungModal>
</template>
