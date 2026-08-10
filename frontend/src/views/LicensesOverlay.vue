<script setup>
import { ChevronRight } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import AvatarCircle from '../components/ui/AvatarCircle.vue'
import { t } from '../lang/index.js'
import { BULLET, LICENSES, PROPRIETARY } from '../data/credits.js'

function open(url) {
  window.open(url, '_blank', 'noreferrer,noopener')
}
</script>

<template>
  <OverlayView :title="t('openSourceLicenses')">
    <SectionCard :title="t('openSourceLicenses')" :subtitle="t('licensesIntro')" />

    <SectionCard :kicker="t('openSourceLicenses')">
      <div class="divide-y divide-un1ca-divider">
        <button
          v-for="lib in LICENSES"
          :key="lib.title"
          type="button"
          class="flex w-full items-center gap-3.5 py-3.5 text-left"
          @click="open(lib.url)"
        >
          <AvatarCircle :initials="lib.initials" :color="lib.color" :size="44" />
          <span class="flex min-w-0 flex-1 flex-col">
            <span class="truncate text-[17px] text-un1ca-text">{{ lib.title }}</span>
            <span class="mt-0.5 text-sm text-un1ca-muted"
              >{{ lib.license }}<span class="license-sep">{{ BULLET }}</span
              >{{ t(lib.summaryId) }}</span
            >
          </span>
          <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
        </button>
      </div>
    </SectionCard>

    <SectionCard :kicker="t('licenseGroupFonts')" :subtitle="t('licenseFontsHint')">
      <div class="divide-y divide-un1ca-divider">
        <button
          v-for="item in PROPRIETARY"
          :key="item.title"
          type="button"
          class="flex w-full items-center gap-3.5 py-3.5 text-left"
          @click="open(item.url)"
        >
          <AvatarCircle :initials="item.initials" :color="item.color" :size="44" />
          <span class="flex min-w-0 flex-1 flex-col">
            <span class="truncate text-[17px] text-un1ca-text">{{ item.title }}</span>
            <span class="mt-0.5 text-sm text-un1ca-muted"
              >{{ item.license }}<span class="license-sep">{{ BULLET }}</span
              >{{ t(item.summaryId) }}</span
            >
          </span>
          <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
        </button>
      </div>
    </SectionCard>
  </OverlayView>
</template>
