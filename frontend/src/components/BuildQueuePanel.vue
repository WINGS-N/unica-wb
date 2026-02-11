<script setup>
// Панель очереди сборки только про ввод и кнопки, без бизнес-логики
// Build queue panel is only inputs and buttons, no business logic here
defineProps({
  t: { type: Function, required: true },
  target: { type: String, required: true },
  targetOptions: { type: Array, required: true },
  latestArtifactAvailable: { type: Boolean, required: true },
  sourceFirmware: { type: String, required: true },
  targetFirmware: { type: String, required: true },
  versionMajor: { type: Number, required: true },
  versionMinor: { type: Number, required: true },
  versionPatch: { type: Number, required: true },
  versionSuffix: { type: String, required: true },
  force: { type: Boolean, required: true },
  noRomZip: { type: Boolean, required: true },
  loading: { type: Boolean, required: true },
  modsDisabledCount: { type: Number, required: true },
  debloatDisabledCount: { type: Number, required: true },
  ffOverridesCount: { type: Number, required: true },
  uploadedModsId: { type: String, required: true },
  uploadedModsCount: { type: Number, required: true }
})

const emit = defineEmits([
  'update:target',
  'target-change',
  'update:sourceFirmware',
  'update:targetFirmware',
  'update:versionMajor',
  'update:versionMinor',
  'update:versionPatch',
  'update:versionSuffix',
  'update:force',
  'update:noRomZip',
  'submit',
  'open-upload',
  'open-mods',
  'open-debloat',
  'open-ff',
  'open-artifacts',
  'open-latest',
  'clear-uploaded-mods'
])

function numberOrZero(value) {
  // Number input может отдать пустую строку, нормализуем в 0
  // Number input can give empty string, normalize it to 0
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function onTargetChange(value) {
  // Сначала обновляем modelValue, потом шлём событие для подгрузки дефолтов
  // First update model value, then emit event for load defaults
  emit('update:target', value)
  emit('target-change', value)
}
</script>

<template>
  <div class="rounded-2xl border border-slate-800 bg-slate-900/70 p-4 sm:p-6">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold">{{ t('appTitle') }}</h1>
        <p class="mt-1 text-sm text-slate-400">{{ t('queueTitle') }}</p>
      </div>
      <button
        v-if="target"
        class="inline-flex shrink-0 items-center justify-center rounded-xl border px-3 py-2 text-xs font-semibold"
        :class="latestArtifactAvailable
          ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25'
          : 'cursor-not-allowed border-slate-600 bg-slate-800 text-slate-500 opacity-70'"
        :disabled="!latestArtifactAvailable"
        @click="$emit('open-latest')"
      >
        {{ t('downloadLatestForTarget') }}
      </button>
    </div>

    <label class="mt-4 block text-sm">{{ t('target') }}</label>
    <select
      :value="target"
      class="mt-1 w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2"
      @change="onTargetChange($event.target.value)"
    >
      <option v-for="item in targetOptions" :key="item.code" :value="item.code">{{ item.code }} - {{ item.name }}</option>
    </select>

    <label class="mt-3 block text-sm">{{ t('sourceFirmware') }}</label>
    <input
      :value="sourceFirmware"
      class="mt-1 w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2"
      @input="$emit('update:sourceFirmware', $event.target.value)"
    />

    <label class="mt-3 block text-sm">{{ t('targetFirmware') }}</label>
    <input
      :value="targetFirmware"
      class="mt-1 w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2"
      @input="$emit('update:targetFirmware', $event.target.value)"
    />

    <label class="mt-3 block text-sm">{{ t('version') }}</label>
    <div class="mt-1 grid grid-cols-3 gap-2">
      <input :value="versionMajor" type="number" min="0" class="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2" @input="$emit('update:versionMajor', numberOrZero($event.target.value))" />
      <input :value="versionMinor" type="number" min="0" class="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2" @input="$emit('update:versionMinor', numberOrZero($event.target.value))" />
      <input :value="versionPatch" type="number" min="0" class="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2" @input="$emit('update:versionPatch', numberOrZero($event.target.value))" />
    </div>

    <label class="mt-3 block text-sm">{{ t('customSuffix') }}</label>
    <input
      :value="versionSuffix"
      class="mt-1 w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2"
      :placeholder="t('optional')"
      @input="$emit('update:versionSuffix', $event.target.value)"
    />

    <label class="mt-4 flex items-center gap-2 text-sm">
      <input :checked="force" type="checkbox" @change="$emit('update:force', $event.target.checked)" />
      {{ t('forceBuild') }}
    </label>
    <p class="ml-6 text-xs text-slate-400">{{ t('forceBuildHint') }}</p>

    <label class="mt-2 flex items-center gap-2 text-sm">
      <input :checked="noRomZip" type="checkbox" @change="$emit('update:noRomZip', $event.target.checked)" />
      {{ t('skipRomZip') }}
    </label>
    <p class="ml-6 text-xs text-slate-400">{{ t('skipRomZipHint') }}</p>

    <button
      class="mt-4 w-full rounded-xl bg-cyan-500 px-4 py-2 font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-50"
      :disabled="loading"
      @click="$emit('submit')"
    >
      {{ loading ? t('submitting') : t('startBuild') }}
    </button>

    <button class="mt-2 w-full rounded-xl border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800" @click="$emit('open-upload')">
      {{ t('uploadMods') }}
    </button>
    <button class="mt-2 w-full rounded-xl border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800" @click="$emit('open-mods')">
      {{ t('modsList') }}
    </button>
    <button class="mt-2 w-full rounded-xl border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800" @click="$emit('open-debloat')">
      {{ t('debloatList') }}
    </button>
    <button class="mt-2 w-full rounded-xl border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800" @click="$emit('open-ff')">
      {{ t('ffEditor') }}
    </button>
    <button class="mt-2 w-full rounded-xl border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800" @click="$emit('open-artifacts')">
      {{ t('artifactsHistory') }}
    </button>

    <div v-if="modsDisabledCount" class="mt-2 rounded-xl border border-sky-700/60 bg-sky-900/20 p-3 text-xs text-sky-200">
      {{ t('modsDisabledForBuild') }}: {{ modsDisabledCount }} {{ t('entries') }}
    </div>
    <div v-if="debloatDisabledCount" class="mt-2 rounded-xl border border-amber-700/60 bg-amber-900/20 p-3 text-xs text-amber-200">
      {{ t('debloatDisabledForBuild') }}: {{ debloatDisabledCount }} {{ t('entries') }}
    </div>
    <div v-if="ffOverridesCount" class="mt-2 rounded-xl border border-cyan-700/60 bg-cyan-900/20 p-3 text-xs text-cyan-200">
      {{ t('ffOverridesForBuild') }}: {{ ffOverridesCount }} {{ t('entries') }}
    </div>

    <div v-if="uploadedModsId" class="mt-2 rounded-xl border border-emerald-700/60 bg-emerald-900/20 p-3 text-xs text-emerald-200">
      <div class="flex items-center justify-between gap-2">
        <span>{{ t('extraModsReady') }} ({{ uploadedModsCount }}) {{ t('nextBuildOnly') }}</span>
        <button class="rounded border border-emerald-600 px-2 py-0.5 text-[10px] uppercase" @click="$emit('clear-uploaded-mods')">{{ t('clear') }}</button>
      </div>
    </div>
  </div>
</template>
