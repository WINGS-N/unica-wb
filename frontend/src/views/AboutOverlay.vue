<script setup>
import { ChevronRight } from 'lucide-vue-next'
import OverlayView from '../components/ui/OverlayView.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import AvatarCircle from '../components/ui/AvatarCircle.vue'
import { t } from '../lang/index.js'
import { openOverlay } from '../stores/nav.js'
import { APP_VERSION, CREDITS, PROJECT, SHOW_TELEGRAM } from '../data/credits.js'

function open(url) {
  window.open(url, '_blank', 'noreferrer,noopener')
}
</script>

<template>
  <OverlayView :title="t('about')">
    <SectionCard>
      <div class="flex select-none items-center gap-4 py-1">
        <img src="/appicon.svg" alt="" class="h-16 w-16 shrink-0 rounded-2xl" />
        <span class="flex flex-col">
          <span class="text-[22px] font-bold text-white">{{ PROJECT.name }}</span>
          <span class="mt-0.5 text-[17px] text-un1ca-muted">{{ t('appVersion') }} {{ APP_VERSION }}</span>
        </span>
      </div>
    </SectionCard>

    <SectionCard :kicker="t('aboutDevelopers')">
      <button type="button" class="flex w-full items-center gap-3.5 py-2 text-left" @click="open(PROJECT.teamUrl)">
        <AvatarCircle username="WINGS-N" initials="WN" color="#2D6BE5" :size="48" />
        <span class="flex min-w-0 flex-1 flex-col">
          <span class="text-[17px] text-un1ca-text">{{ PROJECT.team }}</span>
          <span class="mt-0.5 text-sm text-un1ca-muted">{{ t('aboutTeamSummary') }}</span>
        </span>
        <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
      </button>
    </SectionCard>

    <SectionCard :kicker="t('aboutSourceAndLicenses')">
      <div class="divide-y divide-un1ca-divider">
        <button
          type="button"
          class="flex w-full items-center justify-between py-3.5 text-left"
          @click="open(PROJECT.repository)"
        >
          <span class="flex min-w-0 flex-col">
            <span class="text-[17px] text-un1ca-text">{{ t('sourceCode') }}</span>
            <span class="mt-0.5 truncate text-sm text-un1ca-muted">{{ PROJECT.repositoryLabel }}</span>
          </span>
          <ChevronRight :size="20" class="shrink-0 text-un1ca-muted" />
        </button>
        <button
          type="button"
          class="flex w-full items-center justify-between py-3.5 text-left"
          @click="openOverlay('licenses')"
        >
          <span class="flex min-w-0 flex-col">
            <span class="text-[17px] text-un1ca-text">{{ t('openSourceLicenses') }}</span>
            <span class="mt-0.5 text-sm text-un1ca-muted">{{ t('openSourceLicensesHint') }}</span>
          </span>
          <ChevronRight :size="20" class="shrink-0 text-un1ca-muted" />
        </button>
      </div>
    </SectionCard>

    <SectionCard :kicker="t('aboutFirmware')">
      <div class="divide-y divide-un1ca-divider">
        <button
          type="button"
          class="flex w-full items-center justify-between py-3.5 text-left"
          @click="open(PROJECT.upstream)"
        >
          <span class="flex min-w-0 flex-col">
            <span class="text-[17px] text-un1ca-text">{{ t('link_upstream') }}</span>
            <span class="mt-0.5 truncate text-sm text-un1ca-muted">{{ PROJECT.upstreamLabel }}</span>
          </span>
          <ChevronRight :size="20" class="shrink-0 text-un1ca-muted" />
        </button>
        <button
          type="button"
          class="flex w-full items-center justify-between py-3.5 text-left"
          @click="open(PROJECT.firmwareFork)"
        >
          <span class="flex min-w-0 flex-col">
            <span class="text-[17px] text-un1ca-text">{{ t('link_firmwareFork') }}</span>
            <span class="mt-0.5 truncate text-sm text-un1ca-muted">{{ PROJECT.firmwareForkLabel }}</span>
          </span>
          <ChevronRight :size="20" class="shrink-0 text-un1ca-muted" />
        </button>
        <button
          type="button"
          class="flex w-full items-center justify-between py-3.5 text-left"
          @click="open(PROJECT.discussions)"
        >
          <span class="flex min-w-0 flex-col">
            <span class="text-[17px] text-un1ca-text">{{ t('link_discussions') }}</span>
            <span class="mt-0.5 text-sm text-un1ca-muted">{{ t('aboutDiscussionsSummary') }}</span>
          </span>
          <ChevronRight :size="20" class="shrink-0 text-un1ca-muted" />
        </button>
      </div>
    </SectionCard>

    <SectionCard v-if="SHOW_TELEGRAM" kicker="Telegram">
      <button
        type="button"
        class="flex w-full items-center justify-between py-2 text-left"
        @click="open(PROJECT.telegram)"
      >
        <span class="flex min-w-0 flex-col">
          <span class="text-[17px] text-un1ca-text">{{ t('aboutTelegramTitle') }}</span>
          <span class="mt-0.5 text-sm text-un1ca-muted">{{ t('aboutTelegramSummary') }}</span>
        </span>
        <ChevronRight :size="20" class="shrink-0 text-un1ca-muted" />
      </button>
    </SectionCard>

    <SectionCard kicker="Special thanks to">
      <div class="divide-y divide-un1ca-divider">
        <button
          v-for="credit in CREDITS"
          :key="credit.title"
          type="button"
          class="flex w-full items-center gap-3.5 py-3.5 text-left"
          @click="open(credit.url)"
        >
          <AvatarCircle
            :src="credit.src"
            :username="credit.username"
            :initials="credit.initials"
            :color="credit.color"
            :contain="credit.contain"
            :size="44"
          />
          <span class="flex min-w-0 flex-1 flex-col">
            <span class="text-[17px] text-un1ca-text">{{ credit.title }}</span>
            <span class="mt-0.5 text-sm text-un1ca-muted">{{ t(credit.summaryId) }}</span>
          </span>
          <ChevronRight :size="18" class="shrink-0 text-un1ca-muted" />
        </button>
      </div>
    </SectionCard>
  </OverlayView>
</template>
