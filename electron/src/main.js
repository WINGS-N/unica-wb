import { app, BrowserWindow, dialog, ipcMain, Menu } from 'electron'
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, mkdirSync, copyFileSync, writeFileSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import http from 'node:http'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const ELECTRON_ROOT = app.isPackaged ? process.resourcesPath : resolve(__dirname, '..')
const WB_ROOT = app.isPackaged ? process.resourcesPath : resolve(__dirname, '..', '..')
const FRONTEND_URL = process.env.ELECTRON_FRONTEND_URL || 'http://127.0.0.1:8080'
const API_HEALTH_URL = process.env.ELECTRON_API_HEALTH_URL || 'http://127.0.0.1:8000/api/v1/healthz'
const COMPOSE_PROJECT = process.env.ELECTRON_COMPOSE_PROJECT || 'unica-wb'
const COMPOSE_FILES_SOURCE = [
  join(WB_ROOT, 'docker-compose.yml'),
  ...(process.env.ELECTRON_COMPOSE_LOCAL_REPO === '1' ? [join(WB_ROOT, 'docker-compose.local-repo.yml')] : [])
]
let composeFiles = [...COMPOSE_FILES_SOURCE]
let composeEnvFile = join(WB_ROOT, '.env')
let composeCwd = WB_ROOT
const COMPOSE_SERVICES = (process.env.ELECTRON_COMPOSE_SERVICES || 'redis unica-wb-api unica-wb-worker unica-wb-frontend')
  .split(/\s+/)
  .filter(Boolean)
const MANIFEST_CANDIDATES = [
  join(ELECTRON_ROOT, 'seed-images', 'manifest.json'),
  join(ELECTRON_ROOT, 'seed-images', 'manifest.example.json')
]
const REQUIRE_ROOTFUL_DOCKER = process.env.ELECTRON_REQUIRE_ROOTFUL_DOCKER !== '0'
const PRIV_MODE = (process.env.ELECTRON_PRIV_MODE || 'session').toLowerCase()
const singleInstanceLock = app.requestSingleInstanceLock()
const STARTUP_STAGE_RANGE = {
  check: [0, 15],
  seed: [15, 30],
  pull: [30, 50],
  compose: [50, 75],
  health: [75, 99]
}

let splashWindow = null
let mainWindow = null
let startupRunning = false
let composeStarted = false
let shutdownInProgress = false
let quitAfterShutdown = false
let quitConfirmed = false
let quitRequested = false
let dockerMode = 'plain'
let dockerContext = process.env.ELECTRON_DOCKER_CONTEXT || ''
let dockerHost = process.env.ELECTRON_DOCKER_HOST || ''
let sudoKeepaliveTimer = null
let preferredLanguage = 'en'
let lastProgressPayload = null
let startupLogs = []
let i18nStrings = {
  exitConfirmTitle: 'Confirm exit',
  exitConfirmMessage: 'Are you sure you want to exit?',
  exitConfirmDetail: 'Build processes will be stopped if they are running',
  cancel: 'Cancel',
  exit: 'Exit'
}

if (!singleInstanceLock) {
  app.quit()
}

function emitProgress(payload) {
  if (shutdownInProgress && payload?.stage !== 'shutdown') return
  lastProgressPayload = payload
  if (payload?.message) {
    const ts = new Date().toISOString().slice(11, 19)
    startupLogs.push(`[${ts}] ${payload.message}`)
    if (startupLogs.length > 300) startupLogs = startupLogs.slice(-300)
  }
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('startup:progress', payload)
  }
}

function emitStartupProgress(stage, progress, message, extra = {}) {
  const [start, end] = STARTUP_STAGE_RANGE[stage] || [0, 100]
  const p = Math.max(0, Math.min(100, Number(progress || 0)))
  const total = Math.round(start + ((end - start) * (p / 100)))
  emitProgress({
    ...extra,
    stage,
    progress: p,
    totalProgress: total,
    message
  })
}

function emitError(message) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('startup:error', { message })
  }
}

function getExitDialogTexts() {
  const isRu = preferredLanguage === 'ru'
  return {
    buttons: [i18nStrings.cancel || (isRu ? 'Отмена' : 'Cancel'), i18nStrings.exit || (isRu ? 'Выйти' : 'Exit')],
    title: i18nStrings.exitConfirmTitle || (isRu ? 'Подтверждение выхода' : 'Confirm exit'),
    message: i18nStrings.exitConfirmMessage || (isRu ? 'Точно выйти?' : 'Are you sure you want to exit?'),
    detail: i18nStrings.exitConfirmDetail || (isRu
      ? 'Процессы сборки будут остановлены, если были запущены'
      : 'Build processes will be stopped if they are running')
  }
}

function confirmExit(activeWindow) {
  const t = getExitDialogTexts()
  const response = dialog.showMessageBoxSync(activeWindow, {
    type: 'warning',
    buttons: t.buttons,
    defaultId: 1,
    cancelId: 0,
    title: t.title,
    message: t.message,
    detail: t.detail
  })
  return response === 1
}

function attachWindowCloseConfirm(win) {
  win.on('close', (event) => {
    if (win.__allowCloseOnce) {
      win.__allowCloseOnce = false
      return
    }
    if (quitAfterShutdown || shutdownInProgress || quitConfirmed) return
    const activeWindow = BrowserWindow.getFocusedWindow() || mainWindow || splashWindow || win
    const approved = confirmExit(activeWindow)
    if (!approved) {
      event.preventDefault()
      return
    }
    quitConfirmed = true
    event.preventDefault()
    app.quit()
  })
}

function createSplashWindow(mode = 'startup') {
  splashWindow = new BrowserWindow({
    width: 760,
    height: 540,
    frame: false,
    transparent: true,
    roundedCorners: true,
    backgroundColor: '#00000000',
    resizable: false,
    maximizable: false,
    minimizable: false,
    title: 'UN1CA Web Builder - Starting',
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  splashWindow.setMenuBarVisibility(false)
  attachWindowCloseConfirm(splashWindow)
  splashWindow.webContents.on('did-finish-load', () => {
    if (mode === 'shutdown') {
      splashWindow.webContents.send('startup:progress', {
        stage: 'shutdown',
        progress: 0,
        totalProgress: 0,
        message: 'Stopping...'
      })
      return
    }
    if (lastProgressPayload) {
      splashWindow.webContents.send('startup:progress', lastProgressPayload)
    }
  })
  splashWindow.loadFile(join(__dirname, 'splash.html'), { query: { mode } })
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'UN1CA Web Builder',
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  mainWindow.setMenuBarVisibility(false)
  attachWindowCloseConfirm(mainWindow)
  mainWindow.loadURL(FRONTEND_URL)
}

function runCommand(command, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd || composeCwd || WB_ROOT,
      env: { ...process.env, ...(options.env || {}) },
      shell: false
    })

    let stdout = ''
    let stderr = ''
    let settled = false
    let timer = null

    if (options.timeoutMs && Number(options.timeoutMs) > 0) {
      timer = setTimeout(() => {
        if (settled) return
        settled = true
        child.kill('SIGKILL')
        const error = new Error(`${command} ${args.join(' ')} timed out after ${options.timeoutMs}ms`)
        error.stdout = stdout
        error.stderr = stderr
        rejectPromise(error)
      }, Number(options.timeoutMs))
    }

    child.stdout.on('data', (chunk) => {
      const text = chunk.toString()
      stdout += text
      if (options.onStdout) options.onStdout(text)
    })

    child.stderr.on('data', (chunk) => {
      const text = chunk.toString()
      stderr += text
      if (options.onStderr) options.onStderr(text)
    })

    child.on('error', (err) => {
      if (timer) clearTimeout(timer)
      if (settled) return
      settled = true
      rejectPromise(err)
    })

    child.on('close', (code) => {
      if (timer) clearTimeout(timer)
      if (settled) return
      settled = true
      if (code === 0) {
        resolvePromise({ stdout, stderr })
      } else {
        const error = new Error(`${command} ${args.join(' ')} failed with code ${code}`)
        error.stdout = stdout
        error.stderr = stderr
        rejectPromise(error)
      }
    })

    if (typeof options.stdinText === 'string') {
      try {
        child.stdin.write(options.stdinText)
      } catch {}
      try {
        child.stdin.end()
      } catch {}
    }
  })
}

function dockerArgsWithGlobal(args, context = dockerContext, host = dockerHost) {
  const prefix = []
  if (context) prefix.push('--context', context)
  if (host) prefix.push('-H', host)
  return [...prefix, ...args]
}

function dockerInvocation(args, mode = dockerMode, context = dockerContext, host = dockerHost) {
  const dockerArgs = dockerArgsWithGlobal(args, context, host)
  if (mode === 'sudo') {
    return { command: 'sudo', args: ['docker', ...dockerArgs] }
  }
  if (mode === 'pkexec') {
    return { command: 'pkexec', args: ['docker', ...dockerArgs] }
  }
  return { command: 'docker', args: dockerArgs }
}

async function runDocker(args, options = {}) {
  const inv = dockerInvocation(args)
  return runCommand(inv.command, inv.args, options)
}

async function commandExists(command) {
  try {
    await runCommand('which', [command])
    return true
  } catch {
    return false
  }
}

async function requestSudoPasswordFromSplash() {
  if (!splashWindow || splashWindow.isDestroyed()) return null

  return new Promise((resolvePromise) => {
    const onSubmit = (_event, payload) => {
      cleanup()
      const password = typeof payload?.password === 'string' ? payload.password : ''
      resolvePromise(password)
    }
    const onCancel = () => {
      cleanup()
      resolvePromise(null)
    }
    const cleanup = () => {
      ipcMain.removeListener('startup:sudo-password-submit', onSubmit)
      ipcMain.removeListener('startup:sudo-password-cancel', onCancel)
    }

    ipcMain.on('startup:sudo-password-submit', onSubmit)
    ipcMain.on('startup:sudo-password-cancel', onCancel)

    splashWindow.webContents.send('startup:sudo-request', {
      title: 'Rootful Docker access',
      message: 'Enter your sudo password to start privileged build containers'
    })
  })
}

async function sudoValidateSession() {
  // если sudo ticket уже валиден, UI не показываем
  // if sudo ticket is already valid, do not show UI prompt
  const cached = await runCommand('sudo', ['-n', '-v']).then(() => true).catch(() => false)
  if (cached) return true

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const password = await requestSudoPasswordFromSplash()
    if (password === null) return false
    const ok = await runCommand('sudo', ['-S', '-v'], { stdinText: `${password}\n` }).then(() => true).catch(() => false)
    if (ok) return true
    emitProgress({
      stage: 'check',
      progress: 35,
      message: `Sudo authentication failed (${attempt}/3), try again`
    })
  }

  return false
}

function startSudoKeepalive() {
  if (sudoKeepaliveTimer) return
  // Обновляем sudo ticket, чтобы во время старта не спрашивал пароль снова
  // Refresh sudo ticket so startup does not ask password multiple times
  sudoKeepaliveTimer = setInterval(() => {
    runCommand('sudo', ['-n', '-v']).catch(() => {})
  }, 50_000)
}

function stopSudoKeepalive() {
  if (!sudoKeepaliveTimer) return
  clearInterval(sudoKeepaliveTimer)
  sudoKeepaliveTimer = null
}

async function dockerIsRootless(mode = 'plain', context = dockerContext, host = dockerHost) {
  const inv = dockerInvocation(['info', '--format', '{{json .SecurityOptions}}'], mode, context, host)
  const res = await runCommand(inv.command, inv.args)
  const text = (res.stdout || '').toLowerCase()
  return text.includes('rootless')
}

async function configureDockerAccess() {
  if (process.platform !== 'linux' || !REQUIRE_ROOTFUL_DOCKER) return

  // Сначала пробуем обычный docker или явный context/host из env.
  // First try plain docker or explicit context/host from env.
  const isRootlessNow = await dockerIsRootless('plain', dockerContext, dockerHost).catch(() => false)
  if (!isRootlessNow) return

  // Авто-переключение на context default часто переводит в rootful daemon.
  // Auto switch to context default often moves to rootful daemon.
  if (!dockerContext) {
    const defaultRootless = await dockerIsRootless('plain', 'default', dockerHost).catch(() => true)
    if (!defaultRootless) {
      dockerContext = 'default'
      emitProgress({ stage: 'check', progress: 40, message: 'Switched to docker context: default' })
      return
    }
  }

  const canSudo = await commandExists('sudo')
  const canPkexec = await commandExists('pkexec')

  // session mode = one sudo prompt + keepalive, avoids many pkexec dialogs
  if ((PRIV_MODE === 'session' || PRIV_MODE === 'sudo') && canSudo) {
    const authed = await sudoValidateSession()
    if (!authed) {
      throw new Error('Sudo authentication was cancelled or failed')
    }
    const sudoRootless = await dockerIsRootless('sudo', dockerContext, dockerHost).catch(() => true)
    if (!sudoRootless) {
      dockerMode = 'sudo'
      startSudoKeepalive()
      emitProgress({ stage: 'check', progress: 40, message: 'Using rootful Docker session via sudo' })
      return
    }
  }

  // pkexec mode (or fallback) may ask many times because auth is per command
  if ((PRIV_MODE === 'pkexec' || PRIV_MODE === 'auto' || PRIV_MODE === 'session' || PRIV_MODE === 'sudo') && canPkexec) {
    const pkexecRootless = await dockerIsRootless('pkexec', dockerContext, dockerHost).catch(() => true)
    if (!pkexecRootless) {
      dockerMode = 'pkexec'
      emitProgress({ stage: 'check', progress: 40, message: 'Using rootful Docker via pkexec' })
      return
    }
  }

  throw new Error(
    'Rootful Docker is required for privileged worker. Could not switch from rootless mode automatically.'
  )
}

function toBytes(value, unit) {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return 0
  const u = String(unit || 'B').toUpperCase()
  const map = {
    B: 1,
    KB: 1024,
    MB: 1024 ** 2,
    GB: 1024 ** 3,
    TB: 1024 ** 4,
    KIB: 1024,
    MIB: 1024 ** 2,
    GIB: 1024 ** 3,
    TIB: 1024 ** 4
  }
  return n * (map[u] || 1)
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / (1024 ** idx)
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

function loadSeedManifest() {
  const found = MANIFEST_CANDIDATES.find((p) => existsSync(p))
  if (!found) return { images: [] }
  try {
    const data = JSON.parse(readFileSync(found, 'utf8'))
    return { images: Array.isArray(data.images) ? data.images : [] }
  } catch {
    return { images: [] }
  }
}

async function dockerImageExists(tag) {
  try {
    await runDocker(['image', 'inspect', tag])
    return true
  } catch {
    return false
  }
}

async function dockerImageId(tag) {
  try {
    const out = await runDocker(['image', 'inspect', '--format', '{{.Id}}', tag])
    const id = String(out.stdout || '').trim()
    return id || ''
  } catch {
    return ''
  }
}

function repoFromImageRef(ref) {
  const input = String(ref || '').trim()
  if (!input) return ''
  const noDigest = input.split('@')[0]
  const slash = noDigest.lastIndexOf('/')
  const colon = noDigest.lastIndexOf(':')
  if (colon > slash) return noDigest.slice(0, colon)
  return noDigest
}

function resolvePullRemoteRef(item) {
  const defaultRemote = String(item?.remote || '').trim()
  const remoteLatest = String(item?.remote_latest || '').trim()
  const pullTag = String(process.env.ELECTRON_PULL_TAG || 'latest').trim()

  if (!pullTag) return defaultRemote || remoteLatest
  if (pullTag === 'latest' && remoteLatest) return remoteLatest

  const baseRepo = repoFromImageRef(defaultRemote || remoteLatest)
  if (!baseRepo) return defaultRemote || remoteLatest
  return `${baseRepo}:${pullTag}`
}

async function dockerLocalRepoDigest(ref, repoHint = '') {
  try {
    const out = await runDocker(['image', 'inspect', '--format', '{{json .RepoDigests}}', ref])
    const arr = JSON.parse(String(out.stdout || '[]').trim() || '[]')
    if (!Array.isArray(arr)) return ''
    const repo = repoHint || repoFromImageRef(ref)
    const hit = arr.find((x) => {
      const s = String(x || '')
      return repo ? s.startsWith(`${repo}@sha256:`) : s.includes('@sha256:')
    })
    if (!hit) return ''
    const idx = String(hit).indexOf('@')
    return idx >= 0 ? String(hit).slice(idx + 1) : ''
  } catch {
    return ''
  }
}

function pickDigestFromManifestVerbose(payload) {
  if (!payload) return ''
  const preferPlatform = (items) => {
    if (!Array.isArray(items) || items.length === 0) return ''
    const preferred = items.find((x) => {
      const os = String(x?.Descriptor?.platform?.os || x?.Platform?.os || '').toLowerCase()
      const arch = String(x?.Descriptor?.platform?.architecture || x?.Platform?.architecture || '').toLowerCase()
      return os === 'linux' && arch === 'amd64'
    })
    const selected = preferred || items[0]
    return String(selected?.Descriptor?.digest || selected?.digest || '')
  }

  if (Array.isArray(payload)) {
    return preferPlatform(payload)
  }
  if (payload?.Descriptor?.digest) return String(payload.Descriptor.digest)
  if (Array.isArray(payload?.manifests)) {
    return preferPlatform(payload.manifests)
  }
  return ''
}

async function dockerRemoteDigest(remoteRef) {
  try {
    const out = await runDocker(['manifest', 'inspect', '--verbose', remoteRef], { timeoutMs: 30000 })
    const raw = String(out.stdout || '').trim()
    if (!raw) return ''
    const parsed = JSON.parse(raw)
    return pickDigestFromManifestVerbose(parsed)
  } catch {
    return ''
  }
}

async function ensureSeedImages(manifest) {
  emitStartupProgress('seed', 0, 'Checking embedded seed images')
  if (!manifest.images.length) {
    emitStartupProgress('seed', 100, 'No seed images to load')
    return
  }
  for (let i = 0; i < manifest.images.length; i += 1) {
    const item = manifest.images[i]
    const localTag = item.local_tag
    const archivePath = join(ELECTRON_ROOT, 'seed-images', item.archive || '')
    const progress = Math.round(((i + 1) / manifest.images.length) * 100)

    emitStartupProgress('seed', progress, `Checking seed image ${localTag}`)

    if (!localTag) continue
    if (await dockerImageExists(localTag)) continue
    if (!existsSync(archivePath)) {
      emitStartupProgress('seed', progress, `Seed archive missing for ${localTag}, skip`)
      continue
    }

    emitStartupProgress('seed', progress, `Loading seed image ${localTag}`)

    await runDocker(['load', '-i', archivePath], {
      onStdout: (line) => {
        emitStartupProgress('seed', progress, line.trim() || `Loading ${localTag}`)
      }
    })
  }
  emitStartupProgress('seed', 100, 'Seed images are ready')
}

async function pullAndRetagImage(item, index, total, remoteRef) {
  const pullRef = String(remoteRef || '').trim()
  if (!pullRef || !item.local_tag) return

  const layerMap = new Map()
  let lastBytes = 0
  let lastTs = Date.now()

  function publishPullMessage(line) {
    const match = line.match(/^([a-f0-9]{6,12}):\s+Downloading\s+\[.*?\]\s+([\d.]+)([KMGTP]?B)\/([\d.]+)([KMGTP]?B)/i)
    if (match) {
      const layerId = match[1]
      const current = toBytes(match[2], match[3])
      const totalBytes = toBytes(match[4], match[5])
      layerMap.set(layerId, { current, total: totalBytes })

      let downloaded = 0
      let size = 0
      for (const entry of layerMap.values()) {
        downloaded += Math.min(entry.current, entry.total || entry.current)
        size += entry.total || entry.current
      }

      const now = Date.now()
      const dt = Math.max((now - lastTs) / 1000, 0.2)
      const speed = Math.max((downloaded - lastBytes) / dt, 0)
      lastTs = now
      lastBytes = downloaded

      emitProgress({
        stage: 'pull',
        progress: Math.round(((index + 1) / total) * 100),
        message: `Pulling ${pullRef}`,
        downloaded,
        total: size,
        speed
      })
      return
    }

    if (line.trim()) {
      emitProgress({
        stage: 'pull',
        progress: Math.round(((index + 1) / total) * 100),
        message: line.trim()
      })
    }
  }

  await runDocker(['pull', pullRef], {
    onStdout: publishPullMessage,
    onStderr: publishPullMessage
  })

  if (pullRef !== item.local_tag) {
    await runDocker(['tag', pullRef, item.local_tag])
  }
}

async function maybeUpdateImages(manifest) {
  if (process.env.ELECTRON_PULL_ON_START === '0') return
  if (!manifest.images.length) {
    emitStartupProgress('pull', 100, 'No docker images to pull')
    return
  }

  const strictPull = process.env.ELECTRON_PULL_STRICT === '1'
  let failedPulls = 0

  emitStartupProgress('pull', 0, 'Checking updates for Docker images')
  for (let i = 0; i < manifest.images.length; i += 1) {
    const item = manifest.images[i]
    const localTag = item?.local_tag || 'local image'
    const remoteRef = resolvePullRemoteRef(item)
    const expectedId = String(item?.image_id || '').trim()
    if (localTag && expectedId) {
      const localId = await dockerImageId(localTag)
      if (localId && localId === expectedId) {
        emitStartupProgress(
          'pull',
          Math.round(((i + 1) / manifest.images.length) * 100),
          `Image ${localTag} already matches embedded seed, skip pull`
        )
        continue
      }
    }
    if (remoteRef) {
      const remoteRepo = repoFromImageRef(remoteRef)
      const remoteDigest = await dockerRemoteDigest(remoteRef)
      if (remoteDigest) {
        const localDigestFromRemote = await dockerLocalRepoDigest(remoteRef, remoteRepo)
        const localDigestFromLocalTag = await dockerLocalRepoDigest(localTag, remoteRepo)
        const localDigest = localDigestFromRemote || localDigestFromLocalTag
        if (localDigest && localDigest === remoteDigest) {
          emitStartupProgress(
            'pull',
            Math.round(((i + 1) / manifest.images.length) * 100),
            `Image ${localTag} already matches remote digest, skip pull`
          )
          continue
        }
      }
    }
      emitStartupProgress(
        'pull',
        Math.round((i / manifest.images.length) * 100),
        `Pulling docker image ${remoteRef || item.local_tag || 'unknown'}`
      )
    try {
      await pullAndRetagImage(item, i, manifest.images.length, remoteRef)
    } catch (error) {
      failedPulls += 1
      const errText = (error?.message || '').trim()
      emitStartupProgress(
        'pull',
        Math.round(((i + 1) / manifest.images.length) * 100),
        `Pull failed, using local/seed image for ${localTag}${errText ? ` (${errText})` : ''}`
      )
      if (strictPull) {
        throw error
      }
    }
  }
  if (failedPulls > 0) {
    emitStartupProgress('pull', 100, `Pull finished with ${failedPulls} warning(s), continuing with local images`)
  } else {
    emitStartupProgress('pull', 100, 'Docker images are up to date')
  }
}

function composeArgs(action, extra = []) {
  const envFileArgs = composeEnvFile ? ['--env-file', composeEnvFile] : []
  return [
    'compose',
    '-p',
    COMPOSE_PROJECT,
    ...envFileArgs,
    ...composeFiles.flatMap((file) => ['-f', file]),
    action,
    ...extra
  ]
}

function prepareComposeRuntimeFiles() {
  // В AppImage resources лежат в FUSE mount, root-команды не всегда читают их.
  // In AppImage resources are on FUSE mount, root commands may fail to read them.
  const passthroughEnvKeys = [
    'LOCAL_UN1CA_PATH',
    'GIT_URL',
    'GIT_REF',
    'GHCR_OWNER',
    'IMAGE_API',
    'IMAGE_WORKER',
    'IMAGE_FRONTEND'
  ]
  const renderEnvLine = (key, value) => {
    const raw = String(value ?? '')
    if (!raw) return ''
    // Minimal .env escaping for spaces/quotes/backslashes.
    const escaped = raw.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    return `${key}="${escaped}"`
  }

  if (!app.isPackaged) {
    composeFiles = [...COMPOSE_FILES_SOURCE]
    composeCwd = WB_ROOT
    const lines = []
    const srcEnv = join(WB_ROOT, '.env')
    if (existsSync(srcEnv)) {
      lines.push(readFileSync(srcEnv, 'utf8').trimEnd())
    }
    for (const key of passthroughEnvKeys) {
      const v = process.env[key]
      if (!v) continue
      lines.push(renderEnvLine(key, v))
    }
    if (lines.length) {
      const runtimeEnv = join(WB_ROOT, '.env.runtime')
      writeFileSync(runtimeEnv, `${lines.filter(Boolean).join('\n')}\n`, 'utf8')
      composeEnvFile = runtimeEnv
    } else {
      composeEnvFile = ''
    }
    return
  }

  const runtimeDir = join(app.getPath('userData'), 'runtime-compose')
  mkdirSync(runtimeDir, { recursive: true })

  composeFiles = []
  for (const src of COMPOSE_FILES_SOURCE) {
    if (!existsSync(src)) continue
    const base = src.endsWith('docker-compose.local-repo.yml') ? 'docker-compose.local-repo.yml' : 'docker-compose.yml'
    const dst = join(runtimeDir, base)
    copyFileSync(src, dst)
    composeFiles.push(dst)
  }

  const srcEnv = join(WB_ROOT, '.env')
  const dstEnv = join(runtimeDir, '.env')
  const lines = []
  if (existsSync(srcEnv)) {
    lines.push(readFileSync(srcEnv, 'utf8').trimEnd())
  }
  for (const key of passthroughEnvKeys) {
    const v = process.env[key]
    if (!v) continue
    lines.push(renderEnvLine(key, v))
  }
  if (lines.length) {
    writeFileSync(dstEnv, `${lines.filter(Boolean).join('\n')}\n`, 'utf8')
    composeEnvFile = dstEnv
  } else {
    composeEnvFile = ''
  }

  composeCwd = runtimeDir
}

function composeContainerWeight(statusText) {
  const text = String(statusText || '').toLowerCase()
  if (!text) return 0
  if (text.includes('healthy')) return 1.0
  if (text.includes('up')) return text.includes('health: starting') ? 0.85 : 0.95
  if (text.includes('starting')) return 0.75
  if (text.includes('created')) return 0.5
  if (text.includes('restarting')) return 0.45
  if (text.includes('exited')) return 0.15
  return 0.2
}

async function getComposeProgressSnapshot() {
  const out = await runDocker([
    'ps',
    '-a',
    '--filter',
    `label=com.docker.compose.project=${COMPOSE_PROJECT}`,
    '--format',
    '{{.Names}}\t{{.Status}}'
  ], { timeoutMs: 10000 }).catch(() => ({ stdout: '' }))

  const lines = String(out.stdout || '').split('\n').map((s) => s.trim()).filter(Boolean)
  const weights = new Map(COMPOSE_SERVICES.map((svc) => [svc, 0]))
  const serviceStatus = new Map(COMPOSE_SERVICES.map((svc) => [svc, 'not created yet']))
  const prefix = `${COMPOSE_PROJECT}-`

  for (const line of lines) {
    const [name, ...statusParts] = line.split('\t')
    if (!name) continue
    let service = name
    if (name.startsWith(prefix)) {
      service = name.slice(prefix.length).replace(/-\d+$/, '')
    }
    if (!weights.has(service)) continue
    const status = statusParts.join('\t')
    const w = composeContainerWeight(status)
    if (w > (weights.get(service) || 0)) {
      weights.set(service, w)
      serviceStatus.set(service, status || 'created')
    }
  }

  const vals = Array.from(weights.values())
  const total = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
  const pct = Math.max(0, Math.min(100, Math.round(total * 100)))
  const detail = COMPOSE_SERVICES
    .map((svc) => `${svc}: ${serviceStatus.get(svc) || 'unknown'}`)
    .join(' | ')
  return { pct, detail }
}

async function composeUp() {
  emitStartupProgress('compose', 3, 'Starting...')
  // Помечаем что compose уже трогали, чтобы при выходе точно сделать cleanup
  // Mark compose as touched so we always try cleanup on app quit
  composeStarted = true
  let composePct = 5

  let pollStopped = false
  const poll = async () => {
    if (pollStopped) return
    const snap = await getComposeProgressSnapshot()
    composePct = Math.max(5, snap.pct)
    emitStartupProgress('compose', composePct, `Starting containers... ${snap.pct}%`, { detail: snap.detail })
  }
  const timer = setInterval(() => {
    poll().catch(() => {})
  }, 1200)
  await poll().catch(() => {})

  try {
    await runDocker(composeArgs('up', ['-d', ...COMPOSE_SERVICES]), {
      onStdout: (line) => {
        const text = String(line || '').trim()
        if (text) emitStartupProgress('compose', 10, text)
      },
      onStderr: (line) => {
        const text = String(line || '').trim()
        if (text) emitStartupProgress('compose', 10, text)
      }
    })
    await poll().catch(() => {})
    emitStartupProgress('compose', 100, 'Containers are started')
  } finally {
    pollStopped = true
    clearInterval(timer)
  }
}

async function composeDown() {
  if (!composeStarted) {
    emitProgress({ stage: 'shutdown', progress: 100, totalProgress: 100, message: 'No running compose services' })
    return
  }
  const cmdTimeoutMs = Number(process.env.ELECTRON_COMPOSE_DOWN_CMD_TIMEOUT_MS || 120000)
  emitProgress({ stage: 'shutdown', progress: 10, totalProgress: 10, message: 'Stopping docker compose services' })
  await runDocker(composeArgs('down', ['--remove-orphans', '--timeout', '20']), { timeoutMs: cmdTimeoutMs }).catch(() => {})
  emitProgress({ stage: 'shutdown', progress: 70, totalProgress: 70, message: 'Cleaning up leftover containers' })
  // Fallback: иногда compose down не прибирает все контейнеры, чистим по compose label
  // Fallback: sometimes compose down misses containers, cleanup by compose label
  const listed = await runDocker([
    'ps',
    '-aq',
    '--filter',
    `label=com.docker.compose.project=${COMPOSE_PROJECT}`
  ], { timeoutMs: 15000 }).catch(() => ({ stdout: '' }))
  const ids = (listed.stdout || '').split(/\s+/).map((s) => s.trim()).filter(Boolean)
  if (ids.length) {
    emitProgress({
      stage: 'shutdown',
      progress: 85,
      totalProgress: 85,
      message: `Removing ${ids.length} leftover container(s)`
    })
    await runDocker(['rm', '-f', ...ids], { timeoutMs: 30000 }).catch(() => {})
  }
  emitProgress({ stage: 'shutdown', progress: 100, totalProgress: 100, message: 'Docker services stopped' })
}

async function composeForceKill() {
  const listed = await runDocker([
    'ps',
    '-aq',
    '--filter',
    `label=com.docker.compose.project=${COMPOSE_PROJECT}`
  ], { timeoutMs: 10000 }).catch(() => ({ stdout: '' }))
  const ids = (listed.stdout || '').split(/\s+/).map((s) => s.trim()).filter(Boolean)
  if (!ids.length) return
  emitProgress({
    stage: 'shutdown',
    progress: 95,
    totalProgress: 95,
    message: `Shutdown timeout reached, force-killing ${ids.length} container(s)`
  })
  await runDocker(['kill', ...ids], { timeoutMs: 15000 }).catch(() => {})
  await runDocker(['rm', '-f', ...ids], { timeoutMs: 15000 }).catch(() => {})
}

function waitHttpOk(url, timeoutMs, onTick) {
  return new Promise((resolvePromise, rejectPromise) => {
    const started = Date.now()

    function tick() {
      if (onTick) onTick(Date.now() - started, timeoutMs)
      const req = http.get(url, (res) => {
        const ok = res.statusCode && res.statusCode >= 200 && res.statusCode < 500
        res.resume()
        if (ok) {
          resolvePromise()
          return
        }
        retry()
      })
      req.on('error', retry)
      req.setTimeout(3000, () => {
        req.destroy()
        retry()
      })
    }

    function retry() {
      if (Date.now() - started > timeoutMs) {
        rejectPromise(new Error(`Timed out waiting for ${url}`))
        return
      }
      setTimeout(tick, 1500)
    }

    tick()
  })
}

async function waitUntilReady() {
  const apiTimeout = 8 * 60 * 1000
  emitStartupProgress('health', 2, 'Waiting for API health')
  await waitHttpOk(API_HEALTH_URL, apiTimeout, (elapsed, total) => {
    const p = Math.min(65, Math.max(2, Math.round((elapsed / total) * 65)))
    emitStartupProgress('health', p, 'Waiting for API health')
  })
  const feTimeout = 3 * 60 * 1000
  emitStartupProgress('health', 70, 'Waiting for frontend')
  await waitHttpOk(FRONTEND_URL, feTimeout, (elapsed, total) => {
    const p = Math.min(95, Math.max(70, 70 + Math.round((elapsed / total) * 25)))
    emitStartupProgress('health', p, 'Waiting for frontend')
  })
  emitStartupProgress('health', 100, 'Services are ready')
}

async function startup() {
  if (startupRunning) return
  startupRunning = true

  try {
    prepareComposeRuntimeFiles()
    emitStartupProgress('check', 5, 'Preparing startup sequence')
    emitStartupProgress('check', 20, 'Checking Docker daemon')
    await configureDockerAccess()
    await runDocker(['version'])
    emitStartupProgress('check', 100, 'Docker is available')

    const manifest = loadSeedManifest()

    await ensureSeedImages(manifest)
    await maybeUpdateImages(manifest)
    await composeUp()
    await waitUntilReady()
    emitProgress({ stage: 'health', progress: 100, totalProgress: 100, message: 'Startup complete' })

    createMainWindow()
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.__allowCloseOnce = true
      splashWindow.close()
    }
  } catch (error) {
    emitProgress({ stage: 'shutdown', progress: 0, totalProgress: 0, message: 'Startup failed, cleaning up compose services...' })
    await composeDown().catch(() => {})
    const text = `${error.message}\n\n${error.stderr || ''}`.trim()
    emitError(text)
    dialog.showErrorBox('Startup failed', text)
  } finally {
    startupRunning = false
  }
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null)
  createSplashWindow()
  await startup()

  app.on('activate', () => {
    if (quitRequested || shutdownInProgress || quitAfterShutdown) return
    if (BrowserWindow.getAllWindows().length === 0) {
      createSplashWindow()
      startup()
    }
  })
})

app.on('second-instance', () => {
  const win = mainWindow && !mainWindow.isDestroyed() ? mainWindow : splashWindow
  if (!win || win.isDestroyed()) return
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
})

ipcMain.handle('startup:retry', async () => {
  await startup()
  return { ok: true }
})

ipcMain.handle('startup:get-last-progress', async () => {
  return lastProgressPayload
})

ipcMain.handle('startup:get-log-tail', async () => {
  return startupLogs.slice(-120)
})

ipcMain.on('app:set-language', (_event, lang) => {
  preferredLanguage = String(lang || '').toLowerCase().startsWith('ru') ? 'ru' : 'en'
})

ipcMain.on('app:set-i18n-strings', (_event, payload) => {
  const data = payload && typeof payload === 'object' ? payload : {}
  i18nStrings = {
    ...i18nStrings,
    ...Object.fromEntries(
      Object.entries(data).filter(([, value]) => typeof value === 'string' && value.trim().length > 0)
    )
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', (event) => {
  quitRequested = true
  if (quitAfterShutdown || shutdownInProgress || process.env.ELECTRON_COMPOSE_DOWN_ON_QUIT === '0') {
    return
  }

  event.preventDefault()
  shutdownInProgress = true
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.hide()
  }
  if (!splashWindow || splashWindow.isDestroyed()) {
    createSplashWindow('shutdown')
  } else {
    splashWindow.show()
    splashWindow.focus()
  }
  emitProgress({ stage: 'shutdown', progress: 0, totalProgress: 0, message: 'Stopping...' })
  const hardTimeoutMs = Number(process.env.ELECTRON_SHUTDOWN_FORCE_KILL_TIMEOUT_MS || 30000)
  Promise.race([
    Promise.resolve(composeDown()),
    new Promise((resolve) => {
      setTimeout(resolve, hardTimeoutMs, 'timeout')
    })
  ])
    .then(async (result) => {
      if (result === 'timeout') {
        await composeForceKill().catch(() => {})
      }
    })
    .catch(() => {})
    .finally(() => {
      stopSudoKeepalive()
      quitAfterShutdown = true
      app.quit()
    })
})
