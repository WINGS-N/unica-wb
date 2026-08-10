// Everything the About and Licenses screens show. Kept as data so adding a
// dependency or a contributor is a one-line change

export const APP_VERSION = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : '0.0.0'

export const BULLET = '\u2022'

export const PROJECT = {
  name: 'UN1CA Build',
  team: 'WINGS-N',
  license: 'GPL-3.0-or-later',
  teamUrl: 'https://github.com/WINGS-N',
  repository: 'https://github.com/WINGS-N/unica-wb',
  repositoryLabel: 'github.com/WINGS-N/unica-wb',
  firmwareFork: 'https://github.com/wings-n/UN1CA',
  firmwareForkLabel: 'github.com/wings-n/UN1CA',
  upstream: 'https://github.com/salvogiangri/UN1CA',
  upstreamLabel: 'github.com/salvogiangri/UN1CA',
  discussions: 'https://github.com/salvogiangri/UN1CA/discussions',
  telegram: 'https://t.me/+KrgCVOtwL980ZDky'
}

// The chat is not public yet, so the card stays hidden until it is
export const SHOW_TELEGRAM = false

// Only the people whose work this builder itself stands on
export const CREDITS = [
  {
    title: 'Samsung',
    summaryId: 'creditSamsung',
    src: '/samsung_black_wtext.jpg',
    initials: 'S',
    color: '#000000',
    contain: true,
    url: 'https://www.samsung.com/'
  },
  {
    title: 'salvogiangri',
    summaryId: 'creditUn1ca',
    username: 'salvogiangri',
    initials: 'SG',
    color: '#9A5C2F',
    url: 'https://github.com/salvogiangri'
  },
  {
    title: 'ExtremeXT',
    summaryId: 'creditExtremeXt',
    username: 'ExtremeXT',
    initials: 'EX',
    color: '#7B3F8F',
    url: 'https://github.com/ExtremeXT'
  },
  {
    title: 'ananjaser1211',
    summaryId: 'creditSamloader',
    username: 'ananjaser1211',
    initials: 'AN',
    color: '#8E5A2B',
    url: 'https://github.com/ananjaser1211'
  }
]

// Third-party code shipped in, or driven by, this project
export const LICENSES = [
  {
    title: 'Vue',
    license: 'MIT License',
    summaryId: 'licVue',
    initials: 'VU',
    color: '#159E6B',
    url: 'https://github.com/vuejs/core'
  },
  {
    title: 'Vue Router',
    license: 'MIT License',
    summaryId: 'licVueRouter',
    initials: 'VR',
    color: '#2E9E8F',
    url: 'https://github.com/vuejs/router'
  },
  {
    title: 'Vite',
    license: 'MIT License',
    summaryId: 'licVite',
    initials: 'VT',
    color: '#7B3F8F',
    url: 'https://github.com/vitejs/vite'
  },
  {
    title: 'Tailwind CSS',
    license: 'MIT License',
    summaryId: 'licTailwind',
    initials: 'TW',
    color: '#2F7DBB',
    url: 'https://github.com/tailwindlabs/tailwindcss'
  },
  {
    title: 'Lucide',
    license: 'ISC License',
    summaryId: 'licLucide',
    initials: 'LU',
    color: '#C24A2B',
    url: 'https://github.com/lucide-icons/lucide'
  },
  {
    title: 'FastAPI',
    license: 'MIT License',
    summaryId: 'licFastapi',
    initials: 'FA',
    color: '#1E8E5A',
    url: 'https://github.com/fastapi/fastapi'
  },
  {
    title: 'Starlette',
    license: 'BSD 3-Clause',
    summaryId: 'licStarlette',
    initials: 'ST',
    color: '#51657A',
    url: 'https://github.com/encode/starlette'
  },
  {
    title: 'SQLAlchemy',
    license: 'MIT License',
    summaryId: 'licSqlalchemy',
    initials: 'SA',
    color: '#685ACF',
    url: 'https://github.com/sqlalchemy/sqlalchemy'
  },
  {
    title: 'arq',
    license: 'MIT License',
    summaryId: 'licArq',
    initials: 'AQ',
    color: '#8E5A2B',
    url: 'https://github.com/samuelcolvin/arq'
  },
  {
    title: 'Redis',
    license: 'BSD 3-Clause',
    summaryId: 'licRedis',
    initials: 'RD',
    color: '#C24A2B',
    url: 'https://github.com/redis/redis'
  },
  {
    title: 'nginx',
    license: 'BSD 2-Clause',
    summaryId: 'licNginx',
    initials: 'NG',
    color: '#1E8E5A',
    url: 'https://nginx.org/LICENSE'
  },
  {
    title: 'Wails',
    license: 'MIT License',
    summaryId: 'licWails',
    initials: 'WL',
    color: '#C24A2B',
    url: 'https://github.com/wailsapp/wails'
  },
  {
    title: 'Go',
    license: 'BSD 3-Clause',
    summaryId: 'licGo',
    initials: 'GO',
    color: '#2F7DBB',
    url: 'https://go.dev/LICENSE'
  },
  {
    title: 'Docker Engine',
    license: 'Apache License 2.0',
    summaryId: 'licDocker',
    initials: 'DK',
    color: '#2D6BE5',
    url: 'https://github.com/moby/moby'
  },
  {
    title: 'UN1CA',
    license: 'GNU GPL v3',
    summaryId: 'licUn1ca',
    initials: 'U1',
    color: '#1259D1',
    url: 'https://github.com/salvogiangri/UN1CA'
  },
  {
    title: 'samloader',
    license: 'GNU GPL v3',
    summaryId: 'licSamloader',
    initials: 'SL',
    color: '#8E5A2B',
    url: 'https://github.com/ananjaser1211/samloader'
  },
  {
    title: 'android-tools',
    license: 'Apache License 2.0',
    summaryId: 'licAndroidTools',
    initials: 'AT',
    color: '#159E6B',
    url: 'https://github.com/nmeum/android-tools'
  },
  {
    title: 'Apktool',
    license: 'Apache License 2.0',
    summaryId: 'licApktool',
    initials: 'AP',
    color: '#F18A27',
    url: 'https://github.com/iBotPeaches/Apktool'
  },
  {
    title: 'erofs-utils',
    license: 'GPL-2.0 / Apache-2.0',
    summaryId: 'licErofs',
    initials: 'ER',
    color: '#51657A',
    url: 'https://github.com/sekaiacg/erofs-utils'
  },
  {
    title: 'img2sdat',
    license: 'MIT License',
    summaryId: 'licImg2sdat',
    initials: 'IM',
    color: '#7B3F8F',
    url: 'https://github.com/xpirt/img2sdat'
  },
  {
    title: 'platform_build',
    license: 'Apache License 2.0',
    summaryId: 'licPlatformBuild',
    initials: 'PB',
    color: '#2E9E8F',
    url: 'https://android.googlesource.com/platform/build/'
  }
]

// Not open source, so these are listed apart from the OSS components
export const PROPRIETARY = [
  {
    title: 'SamsungOne',
    license: 'Proprietary',
    summaryId: 'licSamsungOne',
    initials: 'SO',
    color: '#000000',
    url: 'https://www.brody-associates.com'
  },
  {
    title: 'Samsung Sharp Sans',
    license: 'Proprietary',
    summaryId: 'licSharpSans',
    initials: 'SS',
    color: '#000000',
    url: 'https://sharptype.co'
  }
]
