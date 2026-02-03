<script setup>
defineProps({
  toasts: { type: Array, required: true },
  toastClass: { type: Function, required: true }
})

const emit = defineEmits(['dismiss'])
</script>

<template>
  <div class="fixed right-3 top-3 z-[70] w-[min(92vw,420px)] sm:right-5 sm:top-5">
    <TransitionGroup name="toast-list" tag="div" class="flex flex-col gap-2">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="rounded-xl border px-3 py-2 text-sm shadow-xl backdrop-blur"
        :class="toastClass(toast.type)"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="break-words">{{ toast.message }}</div>
          <button class="shrink-0 text-xs opacity-80 hover:opacity-100" @click="$emit('dismiss', toast.id)">✕</button>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-list-enter-active,
.toast-list-leave-active {
  transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

.toast-list-enter-from,
.toast-list-leave-to {
  opacity: 0;
  transform: translateX(14px) translateY(-4px) scale(0.98);
}

.toast-list-move {
  transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1);
}
</style>
