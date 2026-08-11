import { computed, nextTick, ref } from 'vue'
import {
  ApiError,
  activeWorkspaceId,
  apiFetch,
  authEnabled,
  authToken,
  buildWsUrl,
  createReconnectingSocket,
  setActiveWorkspaceId,
  setAuthToken,
  unauthorizedOpen
} from './api.js'
import { dismissToast, showToast } from './toast.js'
import { confirm } from './confirm.js'
import { language, t } from '../lang/index.js'

const STORAGE_SELECTED_JOB = 'un1ca:selectedJobId'
const STORAGE_LOG_TAIL_KB = 'un1ca:logTailKb'
const STORAGE_FOLLOW_LOGS = 'un1ca:followLogs'

const TERMINAL_STATUSES = ['succeeded', 'failed', 'reused', 'canceled']

export function isTerminalStatus(status) {
  return TERMINAL_STATUSES.includes(String(status || ''))
}

// ---------------------------------------------------------------- state

export const workspaces = ref([])
export const workspacesLoading = ref(false)
export const workspacesRoot = ref('')
export const sharedCacheRoot = ref('')
export const fwScope = ref('shared')

export const target = ref('')
export const targetOptions = ref([])
export const sourceFirmware = ref('')
export const targetFirmware = ref('')
export const latestArtifactAvailable = ref(false)
export const versionMajor = ref(0)
export const versionMinor = ref(0)
export const versionPatch = ref(0)
export const versionSuffix = ref('')
export const force = ref(false)
export const noRomZip = ref(false)
export const skipTargetFiles = ref(false)
export const incrementalBaseForBuild = ref('')
export const capabilities = ref({ incremental_zip: true, rom_zip: true, skip_target_files: true })

export const jobs = ref([])
export const jobsLoading = ref(false)
export const jobsFilterBuildOnly = ref(false)
export const jobsFilterSucceededOnly = ref(false)
export const jobsFilterDevice = ref('')
export const selectedJob = ref(null)

export const logs = ref('')
export const logTailKb = ref(64)
export const followLogs = ref(true)
export const activeLogJobId = ref('')

export const loading = ref(false)
// Every section of the build screen loads on its own, so a slow firmware lookup
// never holds up the form
export const targetsLoading = ref(false)
export const defaultsLoading = ref(false)
export const firmwareStatusLoading = ref(false)
export const repoInfoLoading = ref(false)

export const repoInfo = ref({ git_url: '', git_ref: '', repo_path: '', repo_exists: false, repo_size_bytes: 0 })
export const repoSync = ref({ state: 'unknown', ahead_by: 0, behind_by: 0, remote_ref: '' })
export const repoActionBusy = ref(false)
export const currentCommit = ref('unknown')
export const currentCommitSubject = ref('')
export const currentCommitDetails = ref({
  branch: '',
  short_hash: 'unknown',
  full_hash: '',
  subject: '',
  body: '',
  author_name: '',
  author_email: '',
  committer_name: '',
  committer_email: ''
})

export const firmwareStatus = ref({})
export const targetFirmwareStatus = ref({})
export const samsungFwItems = ref([])
export const samsungFwLoading = ref(false)
export const firmwareDeleteBusyKey = ref('')
export const firmwareExtractBusyKey = ref('')

// Live progress, keyed the same way the backend keys it
export const firmwareProgress = ref({})
export const repoProgress = ref({})
export const buildProgress = ref({})

export const modsEntries = ref([])
export const modsDisabledIds = ref([])
export const modsLoading = ref(false)
export const modsTouched = ref(false)

export const debloatEntries = ref([])
export const debloatDisabledIds = ref([])
export const debloatAddSystemText = ref('')
export const debloatAddProductText = ref('')
export const debloatLoading = ref(false)

export const ffEntries = ref([])
export const ffOverrides = ref({})
export const ffLoading = ref(false)

export const uploadFile = ref(null)
export const uploadBusy = ref(false)
export const uploadError = ref('')
export const uploadedMods = ref([])
export const uploadedModsId = ref('')
// Uploaded modules land in unica/mods for one build, which is the same place the
// disable mechanism scans, so turning one off needs nothing but its directory
export const uploadedModsDisabled = ref([])

export function toggleUploadedMod(moduleDir) {
  const key = String(moduleDir || '')
  if (!key) return
  const current = new Set(uploadedModsDisabled.value)
  if (current.has(key)) current.delete(key)
  else current.add(key)
  uploadedModsDisabled.value = [...current]
}

export const artifacts = ref([])
export const artifactsLoading = ref(false)
export const buildHints = ref([])
export const buildHintsLoading = ref(false)

export const resources = ref(null)
export const resourcesLoading = ref(false)

export const advancedLoading = ref(false)
export const advancedBusy = ref(false)
export const advancedSettings = ref({
  source_config_candidates: [],
  source_config_override: '',
  source_config_auto: '',
  source_firmware_auto: '',
  source_config_preferred: [],
  targets_override: '',
  targets_detected: [],
  targets_effective: []
})
export const advancedSourceOverrideInput = ref('')
export const advancedTargetsOverrideInput = ref('')

export const authBusy = ref(false)
export const authPassword = ref('')
export const authPasswordConfirm = ref('')
export const authLoginPassword = ref('')
export const repoUsernameInput = ref('')
export const repoTokenInput = ref('')

export const stopModalJob = ref(null)
export const stopSignalType = ref('sigterm')

export { activeWorkspaceId, authEnabled, authToken, unauthorizedOpen }

// ---------------------------------------------------------------- computed

export const activeWorkspace = computed(
  () => workspaces.value.find((x) => x.id === activeWorkspaceId.value) || workspaces.value[0] || null
)

export const filteredJobs = computed(() =>
  jobs.value.filter((job) => {
    if (jobsFilterBuildOnly.value && String(job?.job_kind || 'build') !== 'build') return false
    if (jobsFilterSucceededOnly.value && String(job?.status || '') !== 'succeeded') return false
    if (jobsFilterDevice.value && String(job?.target || '') !== jobsFilterDevice.value) return false
    return true
  })
)

export const runningJobsCount = computed(
  () => jobs.value.filter((job) => job.status === 'running' || job.status === 'queued').length
)

export const ffOverridesCount = computed(() => Object.keys(ffOverrides.value || {}).length)

export const debloatAddedCount = computed(
  () => pathsTextToList(debloatAddSystemText.value).length + pathsTextToList(debloatAddProductText.value).length
)

// ---------------------------------------------------------------- helpers

function reportError(key, error) {
  if (error instanceof ApiError && error.status === 401) return
  // Losing the network is shown once by the connectivity toast, not once per
  // request that happened to be in flight
  if (error instanceof ApiError && error.offline) return
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return
  // A restarting backend fails every section at once, and one banner about the
  // backend beats a stack of identical complaints about each of them
  if (error instanceof ApiError && error.unavailable) {
    showToast(t('serverUnavailableText'), 'error', 0, {
      id: 'connectivity',
      title: t('serverUnavailableTitle')
    })
    return
  }
  showToast(`${t(key)}: ${error?.message || error}`, 'error')
}

export const online = ref(typeof navigator === 'undefined' || navigator.onLine !== false)

// The banner about an unreachable backend has no timeout, so anything that
// proves the backend answers again has to take it down
function serverAnswered() {
  if (online.value) dismissToast('connectivity')
}

function handleOffline() {
  online.value = false
  showToast(t('offlineText'), 'warning', 0, { id: 'connectivity', title: t('offlineTitle') })
}

function handleOnline() {
  online.value = true
  dismissToast('connectivity')
  showToast(t('backOnline'), 'success', 3000, { id: 'connectivity-back' })
  refreshAll()
}

export function pathsTextToList(text) {
  return Array.from(
    new Set(
      (text || '')
        .split('\n')
        .map((x) => x.trim())
        .filter(Boolean)
    )
  )
}

export function listToPathsText(items) {
  return (Array.isArray(items) ? items : []).join('\n')
}

export function formatBytes(bytes) {
  const value = Number(bytes || 0)
  if (value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** idx).toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

export function formatSpeed(bps) {
  const value = Number(bps || 0)
  if (!Number.isFinite(value) || value <= 0) return '-'
  return `${formatBytes(value)}/s`
}

export function formatDuration(sec) {
  const n = Number(sec || 0)
  if (!Number.isFinite(n) || n <= 0) return '0:00'
  const s = Math.floor(n)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  return `${m}:${String(r).padStart(2, '0')}`
}

const DATE_TIME_FORMAT = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23'
}

export function formatDateTime(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString(language.value === 'ru' ? 'ru-RU' : 'en-GB', DATE_TIME_FORMAT)
}

export function targetDisplay(code) {
  const value = String(code || '').trim()
  if (!value) return 'unknown'
  const found = targetOptions.value.find((x) => x?.code === value)
  return found?.name ? `${value} - ${found.name}` : value
}

export function jobTitle(job) {
  return job?.operation_name || targetDisplay(job?.target)
}

export function normalizeModelForImage(model) {
  const src = String(model || '').toUpperCase()
  const m = src.match(/^([A-Z]+-[A-Z]*\d+)/)
  return m ? m[1] : src
}

export function deviceImageSvgData(code) {
  const label = (code || target.value || 'device').slice(0, 8)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72"><rect x="18" y="6" width="36" height="60" rx="9" fill="#1c1c1e" stroke="rgba(255,255,255,0.14)" stroke-width="2"/><rect x="23" y="13" width="26" height="42" rx="4" fill="#000"/><circle cx="36" cy="61" r="2.5" fill="rgba(255,255,255,0.35)"/><text x="36" y="38" text-anchor="middle" font-size="8" fill="#8bb8ff" font-family="monospace">${label}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

function parseJsonList(value) {
  if (!value) return []
  try {
    const arr = JSON.parse(value)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

export function parseJobMods(job) {
  return parseJsonList(job?.extra_mods_modules_json)
}

export function parseJobModsDisabled(job) {
  return job?.mods_disabled_json == null ? [] : parseJsonList(job.mods_disabled_json)
}

export function hasJobModsConfig(job) {
  return job?.mods_disabled_json != null
}

export function parseJobDebloatDisabled(job) {
  return parseJsonList(job?.debloat_disabled_json)
}

export function parseJobDebloatAddSystem(job) {
  return parseJsonList(job?.debloat_add_system_json)
}

export function parseJobDebloatAddProduct(job) {
  return parseJsonList(job?.debloat_add_product_json)
}

export function hasJobDebloatChanges(job) {
  return (
    parseJobDebloatDisabled(job).length > 0 ||
    parseJobDebloatAddSystem(job).length > 0 ||
    parseJobDebloatAddProduct(job).length > 0
  )
}

export function parseJobFFOverrides(job) {
  if (!job?.ff_overrides_json) return {}
  try {
    const parsed = JSON.parse(job.ff_overrides_json)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function hasJobFFOverrides(job) {
  return Object.keys(parseJobFFOverrides(job)).length > 0
}

export function firmwareProgressKey(fwKey) {
  return `${fwScope.value || 'shared'}:${fwKey}`
}

export function firmwareProgressFor(fwKey) {
  if (!fwKey) return null
  return firmwareProgress.value[firmwareProgressKey(fwKey)] || null
}

export function firmwareProgressForStatus(statusObj) {
  const model = String(statusObj?.source_model || '')
    .trim()
    .toUpperCase()
  const csc = String(statusObj?.source_csc || '')
    .trim()
    .toUpperCase()
  if (!model || !csc) return null
  return firmwareProgressFor(`${model}_${csc}`)
}

export function progressPct(progress) {
  const val = Number(progress?.percent ?? 0)
  if (!Number.isFinite(val)) return 0
  return Math.max(0, Math.min(100, Math.round(val)))
}

export function isProgressActive(progress) {
  return String(progress?.status || '') === 'running'
}

export function stripAnsi(input) {
  // Browser log view has no use for terminal escape codes
  // eslint-disable-next-line no-control-regex
  return input.replace(/\[[0-?]*[ -/]*[@-~]/g, '')
}

// ---------------------------------------------------------------- workspaces

export async function fetchWorkspaces() {
  workspacesLoading.value = true
  try {
    const data = await apiFetch('/workspaces', { skipWorkspace: true })
    workspaces.value = Array.isArray(data.items) ? data.items : []
    workspacesRoot.value = data.workspaces_root || ''
    sharedCacheRoot.value = data.shared_cache_root || ''
    const known = workspaces.value.some((x) => x.id === activeWorkspaceId.value)
    if (!known) setActiveWorkspaceId(workspaces.value[0]?.id || '')
    fwScope.value = activeWorkspace.value?.fw_scope || 'shared'
  } catch (e) {
    reportError('workspacesLoadFailed', e)
  } finally {
    workspacesLoading.value = false
  }
}

// Switching workspace resets everything derived from the old one, otherwise the
// previous repo's targets and jobs linger for a frame and can be acted on
export async function selectWorkspace(id) {
  if (!id || id === activeWorkspaceId.value) return
  setActiveWorkspaceId(id)
  closeLogs()
  logs.value = ''
  selectedJob.value = null
  localStorage.removeItem(STORAGE_SELECTED_JOB)
  jobs.value = []
  targetOptions.value = []
  target.value = ''
  modsEntries.value = []
  modsDisabledIds.value = []
  modsTouched.value = false
  debloatEntries.value = []
  debloatDisabledIds.value = []
  debloatAddSystemText.value = ''
  debloatAddProductText.value = ''
  ffEntries.value = []
  ffOverrides.value = {}
  uploadedModsId.value = ''
  uploadedMods.value = []
  uploadedModsDisabled.value = []
  artifacts.value = []
  samsungFwItems.value = []
  fwScope.value = workspaces.value.find((x) => x.id === id)?.fw_scope || 'shared'
  await loadModsEntries()
  if (requestSections(null, 'subscribe')) return
  await fetchTargets()
  await Promise.all([fetchBuildSections(), fetchJobs()])
}

export async function createWorkspace(payload) {
  const data = await apiFetch('/workspaces', { method: 'POST', json: payload, skipWorkspace: true })
  await fetchWorkspaces()
  if (data?.id) await selectWorkspace(data.id)
  showToast(t('workspaceCreated'), 'success')
  return data
}

export async function updateWorkspace(id, payload) {
  const data = await apiFetch(`/workspaces/${id}`, { method: 'PATCH', json: payload, skipWorkspace: true })
  await fetchWorkspaces()
  if (id === activeWorkspaceId.value) {
    fwScope.value = data?.fw_scope || fwScope.value
    await fetchBuildSections()
  }
  showToast(t('workspaceUpdated'), 'success')
  return data
}

export async function deleteWorkspace(id, deleteFiles) {
  await apiFetch(`/workspaces/${id}`, {
    method: 'DELETE',
    params: { delete_files: deleteFiles ? 'true' : 'false' },
    skipWorkspace: true
  })
  const wasActive = id === activeWorkspaceId.value
  await fetchWorkspaces()
  if (wasActive) {
    const next = workspaces.value[0]?.id || ''
    setActiveWorkspaceId('')
    if (next) await selectWorkspace(next)
  }
  showToast(t('workspaceDeleteQueued'), 'warning')
}

// ---------------------------------------------------------------- auth

export async function fetchAuthStatus() {
  try {
    const data = await apiFetch('/auth/status', { skipWorkspace: true })
    authEnabled.value = Boolean(data?.enabled)
  } catch {
    // status endpoint is best-effort; a failure just leaves auth as-is
  }
}

export async function loginWithPassword() {
  authBusy.value = true
  try {
    const data = await apiFetch('/auth/login', {
      method: 'POST',
      json: { password: authLoginPassword.value },
      skipWorkspace: true
    })
    setAuthToken(data?.token || '')
    authLoginPassword.value = ''
    unauthorizedOpen.value = false
    await fetchAuthStatus()
    restartSockets()
    await refreshAll()
    showToast(t('authLoggedIn'), 'success')
  } catch (e) {
    showToast(`${t('authLoginFailed')}: ${e?.message || e}`, 'error')
  } finally {
    authBusy.value = false
  }
}

export async function setPassword() {
  if (!authPassword.value) return
  if (authPassword.value !== authPasswordConfirm.value) {
    showToast(t('authPasswordMismatch'), 'error')
    return
  }
  authBusy.value = true
  try {
    const data = await apiFetch('/auth/password', {
      method: 'POST',
      json: { password: authPassword.value },
      skipWorkspace: true
    })
    authEnabled.value = Boolean(data?.enabled)
    if (data?.token) setAuthToken(data.token)
    authPassword.value = ''
    authPasswordConfirm.value = ''
    showToast(t('authPasswordSet'), 'success')
  } catch (e) {
    reportError('authPasswordSetFailed', e)
  } finally {
    authBusy.value = false
  }
}

export async function clearPassword() {
  const ok = await confirm({
    title: t('authClearPassword'),
    message: t('authClearPasswordConfirm'),
    confirmText: t('authClearPassword'),
    danger: true
  })
  if (!ok) return
  authBusy.value = true
  try {
    await apiFetch('/auth/password', { method: 'POST', json: { password: '' }, skipWorkspace: true })
    authEnabled.value = false
    setAuthToken('')
    showToast(t('authPasswordCleared'), 'warning')
  } catch (e) {
    reportError('authPasswordClearFailed', e)
  } finally {
    authBusy.value = false
  }
}

// ---------------------------------------------------------------- defaults

export async function fetchTargets() {
  targetsLoading.value = true
  try {
    const data = await apiFetch('/build/targets')
    targetOptions.value = data.target_options || []
    fwScope.value = data.fw_scope || fwScope.value
    const known = targetOptions.value.some((x) => x.code === target.value)
    if (!known) target.value = data.target || targetOptions.value[0]?.code || ''
    return target.value
  } catch (e) {
    reportError('defaultsLoadFailed', e)
    return target.value
  } finally {
    targetsLoading.value = false
  }
}

export function applyDefaults(data) {
  const nextTarget = data.target || target.value
  const targetChanged = nextTarget !== target.value
  target.value = nextTarget
  sourceFirmware.value = data.defaults?.source_firmware || ''
  targetFirmware.value = data.defaults?.target_firmware || ''
  versionMajor.value = data.defaults?.version_major ?? 0
  versionMinor.value = data.defaults?.version_minor ?? 0
  versionPatch.value = data.defaults?.version_patch ?? 0
  versionSuffix.value = data.defaults?.version_suffix || ''
  latestArtifactAvailable.value = Boolean(data.latest_artifact_available)
  if (data.capabilities) capabilities.value = data.capabilities
  // Floating-feature defaults are per target; only drop the user's overrides
  // when the target actually changed under them
  if (targetChanged) {
    ffEntries.value = []
    ffOverrides.value = {}
  }
}

export async function fetchBuildDefaults(selectedTarget) {
  defaultsLoading.value = true
  try {
    applyDefaults(await apiFetch('/build/defaults', { params: { target: selectedTarget || target.value } }))
  } catch (e) {
    reportError('defaultsLoadFailed', e)
  } finally {
    defaultsLoading.value = false
  }
}

export async function fetchFirmwareStatus(selectedTarget) {
  firmwareStatusLoading.value = true
  try {
    const data = await apiFetch('/firmware/status', { params: { target: selectedTarget || target.value } })
    fwScope.value = data.fw_scope || fwScope.value
    firmwareStatus.value = data.firmware_status || {}
    targetFirmwareStatus.value = data.target_firmware_status || {}
  } catch (e) {
    reportError('defaultsLoadFailed', e)
  } finally {
    firmwareStatusLoading.value = false
  }
}

export function applyRepoInfo(data) {
  repoInfo.value = { ...repoInfo.value, ...data }
  repoSync.value = data.repo_sync || repoSync.value
  const commit = data.commit || {}
  currentCommitDetails.value = commit
  currentCommit.value = commit.short_hash || 'unknown'
  currentCommitSubject.value = commit.subject || ''
  if (data.progress) {
    repoProgress.value = { ...repoProgress.value, [activeWorkspaceId.value]: data.progress }
  }
}

export async function fetchRepoInfo() {
  repoInfoLoading.value = true
  try {
    applyRepoInfo(await apiFetch('/repo/info'))
  } catch (e) {
    reportError('repoActionFailed', e)
  } finally {
    repoInfoLoading.value = false
  }
}

// The build screen as a whole, with each section on its own request
export async function fetchBuildSections(selectedTarget) {
  const resolved = selectedTarget || target.value
  await Promise.all([fetchBuildDefaults(resolved), fetchFirmwareStatus(resolved), fetchRepoInfo()])
}

export async function changeTarget(code) {
  target.value = code
  if (requestSections(['defaults', 'firmware'], 'subscribe')) return
  await Promise.all([fetchBuildDefaults(code), fetchFirmwareStatus(code)])
}

// ---------------------------------------------------------------- jobs

export function applyJobs(list) {
  serverAnswered()
  jobs.value = Array.isArray(list) ? list : []
  const selectedId = selectedJob.value?.id || localStorage.getItem(STORAGE_SELECTED_JOB)
  if (selectedId) {
    const found = jobs.value.find((x) => x.id === selectedId)
    if (found) {
      selectedJob.value = found
      ensureSelectedJobLogsAttached()
      return
    }
  }
  if (!selectedJob.value && jobs.value.length) selectedJob.value = jobs.value[0]
  ensureSelectedJobLogsAttached()
}

export async function fetchJobs() {
  jobsLoading.value = true
  try {
    applyJobs(await apiFetch('/jobs'))
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) {
      // Polling failures are noisy by nature; surface them only once in a while
      console.warn('jobs poll failed', e)
    }
  } finally {
    jobsLoading.value = false
  }
}

export async function submitJob() {
  loading.value = true
  try {
    const job = await apiFetch('/jobs', {
      method: 'POST',
      json: {
        target: target.value,
        source_firmware: sourceFirmware.value,
        target_firmware: targetFirmware.value,
        version_major: Number(versionMajor.value),
        version_minor: Number(versionMinor.value),
        version_patch: Number(versionPatch.value),
        version_suffix: versionSuffix.value || null,
        extra_mods_upload_id: uploadedModsId.value || null,
        mods_disabled: buildModsDisabled(),
        debloat_disabled: debloatDisabledIds.value,
        debloat_add_system: pathsTextToList(debloatAddSystemText.value),
        debloat_add_product: pathsTextToList(debloatAddProductText.value),
        ff_overrides: ffOverridesCount.value ? ffOverrides.value : null,
        force: force.value,
        no_rom_zip: noRomZip.value,
        skip_target_files: skipTargetFiles.value,
        incremental_base_job_id: incrementalBaseForBuild.value || null
      }
    })
    selectedJob.value = job
    logs.value = ''
    await fetchJobs()
    if (job.log_path) {
      openLogs(job.id)
      showToast(t('buildTaskQueued'), 'warning')
    } else if (job.status === 'reused') {
      logs.value = `${t('reusedArtifact')}: ${job.reused_from_job_id || 'unknown'}`
      showToast(t('reusedArtifact'), 'success')
    } else {
      showToast(t('buildTaskQueued'), 'warning')
    }
    uploadedModsId.value = ''
    uploadedMods.value = []
  } catch (e) {
    reportError('failedSubmit', e)
  } finally {
    loading.value = false
  }
}

export function selectJob(job) {
  selectedJob.value = job
  localStorage.setItem(STORAGE_SELECTED_JOB, job.id)
  logs.value = ''
  if (job.log_path) {
    openLogs(job.id)
  } else if (job.status === 'reused') {
    closeLogs()
    logs.value = `${t('reusedArtifact')}: ${job.reused_from_job_id || 'unknown'}`
  } else {
    closeLogs()
  }
}

export async function stopJobConfirmed() {
  const job = stopModalJob.value
  if (!job) return
  try {
    await apiFetch(`/jobs/${job.id}/stop`, {
      method: 'POST',
      json: { signal_type: stopSignalType.value },
      skipWorkspace: true
    })
    showToast(t('stopSignalQueued'), 'warning')
    stopModalJob.value = null
    await fetchJobs()
  } catch (e) {
    reportError('failedStop', e)
  }
}

export function openStopModal(job) {
  stopModalJob.value = job
  stopSignalType.value = 'sigterm'
}

export function openStopModalForProgress(progress) {
  const jobId = progress?.job_id
  if (!jobId) return
  openStopModal(jobs.value.find((x) => x.id === jobId) || { id: jobId, status: 'running' })
}

export async function loadBuildHints(job) {
  buildHintsLoading.value = true
  buildHints.value = []
  try {
    const data = await apiFetch(`/jobs/${job.id}/hints`, { skipWorkspace: true })
    buildHints.value = Array.isArray(data.hints) ? data.hints : []
  } catch (e) {
    reportError('hintsLoadFailed', e)
  } finally {
    buildHintsLoading.value = false
  }
}

// ---------------------------------------------------------------- logs

let logSocket = null
// Whether a reader is on the log screen. Survives the socket being reopened for
// another job, because the reader has not gone anywhere
let logsWanted = false
// The tail that arrives first has to land at the end, and the reader has not
// scrolled anywhere yet to be preserved
let firstChunk = true

export function closeLogs() {
  if (logSocket && typeof logSocket.close === 'function') logSocket.close()
  logSocket = null
  activeLogJobId.value = ''
}

function sendToLogSocket(payload) {
  if (!logSocket || logSocket.readyState !== WebSocket.OPEN) return false
  logSocket.send(JSON.stringify(payload))
  return true
}

/** Start the feed. The socket carries nothing until a reader is on the screen */
export function attachLogs() {
  logsWanted = true
  firstChunk = true
  const jobId = selectedJob.value?.id
  // Opening the screen must not depend on a socket somebody else opened first:
  // without one there is nothing to attach to and the log waits forever
  if (jobId && (!logSocket || activeLogJobId.value !== jobId)) {
    openLogs(jobId)
    return
  }
  sendToLogSocket({ action: 'attach', tail_kb: logTailKb.value })
}

/** Leave the socket open but silent while the reader is elsewhere */
export function detachLogs() {
  logsWanted = false
  sendToLogSocket({ action: 'detach' })
}

/** Pins the view to the newest line, whatever the reader was looking at before */
export async function scrollLogsToBottom() {
  await nextTick()
  const el = document.getElementById('logs')
  if (el) el.scrollTop = el.scrollHeight
}

export function openLogs(jobId) {
  // Logs stream over ws; \r rewrites the current progress line instead of
  // spawning a new one, exactly like a terminal would
  closeLogs()
  activeLogJobId.value = jobId
  logSocket = new WebSocket(buildWsUrl(`/jobs/${jobId}/ws`, { tail_kb: logTailKb.value }))
  logSocket.onopen = () => {
    // A reader already on the log screen when the socket opened
    if (logsWanted) attachLogs()
  }
  logSocket.onmessage = async (event) => {
    const el = document.getElementById('logs')
    const wasNearBottom = el ? el.scrollHeight - el.scrollTop - el.clientHeight < 24 : true
    const keepBottomOffset = el ? el.scrollHeight - el.scrollTop : 0
    const before = logs.value
    let next = logs.value
    let changed = false
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'chunk') {
        const chunk = stripAnsi(payload.chunk || '')
        for (const ch of chunk) {
          if (ch === '\r') next = next.replace(/[^\n]*$/, '')
          else next += ch
        }
        changed = next !== before
        if (next.length > 2_000_000) {
          next = next.slice(-1_500_000)
          changed = true
        }
      }
    } catch {
      const text = stripAnsi(String(event.data || ''))
      if (text) {
        next += `${text}\n`
        changed = true
      }
    }
    if (!changed) return
    logs.value = next
    await nextTick()
    const updated = document.getElementById('logs')
    if (!updated) return
    if (firstChunk || (followLogs.value && wasNearBottom)) {
      firstChunk = false
      updated.scrollTop = updated.scrollHeight
    } else {
      updated.scrollTop = Math.max(0, updated.scrollHeight - keepBottomOffset)
    }
  }
  logSocket.onclose = () => {
    logSocket = null
    const selected = selectedJob.value
    // Keep the marker for a finished job so polling does not reopen the socket
    if (selected?.id === jobId && isTerminalStatus(selected.status)) {
      activeLogJobId.value = jobId
      return
    }
    activeLogJobId.value = ''
  }
}

function ensureSelectedJobLogsAttached() {
  const job = selectedJob.value
  if (!job) return
  if (job.log_path && activeLogJobId.value !== job.id) {
    if (isTerminalStatus(job.status) && logs.value) return
    openLogs(job.id)
  }
}

export function setLogTailKb(value) {
  logTailKb.value = Number(value) || 64
  localStorage.setItem(STORAGE_LOG_TAIL_KB, String(logTailKb.value))
  if (!selectedJob.value?.log_path) return
  logs.value = ''
  // The feed restarts from the tail on every attach, so a live socket only
  // needs to be told the new size
  if (logSocket && logsWanted) attachLogs()
  else openLogs(selectedJob.value.id)
}

export function setFollowLogs(value) {
  followLogs.value = Boolean(value)
  localStorage.setItem(STORAGE_FOLLOW_LOGS, followLogs.value ? '1' : '0')
}

export function logsPlaceholder() {
  const job = selectedJob.value
  if (!job) return t('selectJobToStream')
  const finished = isTerminalStatus(job.status)
  if (!job.log_path) return finished ? t('noLogForJob') : t('waitingForWorkerLog')
  return finished ? t('logIsEmpty') : t('waitingForOutput')
}

// ---------------------------------------------------------------- repo

async function queueRepoAction(path, method, okToastKey, params) {
  repoActionBusy.value = true
  try {
    await apiFetch(path, { method, params })
    await Promise.all([fetchJobs(), fetchBuildSections()])
    showToast(t(okToastKey), 'warning')
  } catch (e) {
    reportError('repoActionFailed', e)
  } finally {
    repoActionBusy.value = false
  }
}

export function cloneRepository() {
  return queueRepoAction('/repo/clone', 'POST', 'repoCloneQueued')
}

export async function recloneRepository() {
  const ok = await confirm({
    title: t('repoReclone'),
    message: t('repoRecloneConfirm'),
    confirmText: t('repoReclone'),
    danger: true
  })
  if (!ok) return
  return queueRepoAction('/repo/clone', 'POST', 'repoRecloneQueued', { fresh: 'true' })
}

export function pullRepository() {
  return queueRepoAction('/repo/pull', 'POST', 'repoPullQueued')
}

export function updateRepoSubmodules() {
  return queueRepoAction('/repo/submodules', 'POST', 'repoSubmodulesQueued')
}

export async function deleteRepository(mode = 'repo_only') {
  const ok = await confirm({
    title: mode === 'repo_with_out' ? t('deleteRepoWithOut') : t('deleteRepoKeepOut'),
    message: mode === 'repo_with_out' ? t('deleteRepoWithOutConfirm') : t('deleteRepoKeepOutConfirm'),
    confirmText: t('delete'),
    danger: true
  })
  if (!ok) return
  return queueRepoAction('/repo', 'DELETE', mode === 'repo_with_out' ? 'repoDeleteWithOutQueued' : 'repoDeleteQueued', {
    mode
  })
}

let repoConfigTimer = null

export function updateRepoUrlInput(value) {
  repoInfo.value = { ...repoInfo.value, git_url: value }
  if (repoConfigTimer) clearTimeout(repoConfigTimer)
  repoConfigTimer = setTimeout(() => saveRepoConfig({ git_url: value }), 600)
}

export async function saveRepoConfig(patch) {
  try {
    const data = await apiFetch('/repo/config', {
      method: 'PATCH',
      json: { git_url: repoInfo.value.git_url || '', ...patch }
    })
    repoInfo.value = { ...repoInfo.value, ...data }
    if (data?.repo_sync) repoSync.value = data.repo_sync
    await fetchWorkspaces()
  } catch (e) {
    reportError('repoUrlSaveFailed', e)
  }
}

export async function saveRepoCredentials() {
  authBusy.value = true
  try {
    await saveRepoConfig({
      git_username: repoUsernameInput.value || '',
      git_token: repoTokenInput.value || ''
    })
    repoTokenInput.value = ''
    showToast(t('repoCredsSaved'), 'success')
  } finally {
    authBusy.value = false
  }
}

export function repoSyncText() {
  const state = repoSync.value?.state || 'unknown'
  if (state === 'up_to_date') return t('repoSyncUpToDate')
  if (state === 'behind') return `${t('repoSyncBehind')} (${repoSync.value?.behind_by || 0})`
  if (state === 'ahead') return `${t('repoSyncAhead')} (${repoSync.value?.ahead_by || 0})`
  if (state === 'diverged') return t('repoSyncDiverged')
  return t('repoSyncUnknown')
}

export function repoSyncTone() {
  const state = repoSync.value?.state || 'unknown'
  if (state === 'up_to_date') return 'success'
  if (state === 'behind' || state === 'ahead' || state === 'diverged') return 'warning'
  return 'danger'
}

/** Nothing downloaded is a different state from having an old copy */
const FIRMWARE_PHASE_KEYS = {
  download: 'downloadProgressLabel',
  decrypt: 'decryptProgressLabel',
  verify: 'verifyProgressLabel',
  extract: 'extractProgressLabel'
}

export function firmwarePhaseLabel(progress) {
  return t(FIRMWARE_PHASE_KEYS[progress?.phase] || 'downloadProgressLabel')
}

export function firmwareStatusLabel(statusObj) {
  if (statusObj?.up_to_date) return 'upToDate'
  if (statusObj?.downloaded_version || statusObj?.extracted_version) return 'outdated'
  return 'notDownloaded'
}

export function firmwareStatusTone(statusObj) {
  if (statusObj?.up_to_date) return 'success'
  if (statusObj?.downloaded_version || statusObj?.extracted_version) return 'warning'
  return 'danger'
}

export const activeRepoProgress = computed(() => {
  const entry = repoProgress.value[activeWorkspaceId.value] || null
  // The last frame of a finished operation lingers under its ttl, and the card
  // has nothing to say about work that already ended
  return entry && entry.status === 'running' ? entry : null
})

// ---------------------------------------------------------------- firmware

export async function fetchSamsungFw() {
  samsungFwLoading.value = true
  try {
    const data = await apiFetch('/firmware/samsung')
    samsungFwItems.value = Array.isArray(data.items) ? data.items : []
    fwScope.value = data.fw_scope || fwScope.value
  } catch (e) {
    reportError('failedSamsungFwLoad', e)
  } finally {
    samsungFwLoading.value = false
  }
}

export const firmwareDownloadBusyKind = ref('')

/** Fetch a firmware ahead of a build: on a first run it is the slow part */
export async function downloadSamsungFw(kind = 'both') {
  firmwareDownloadBusyKind.value = kind
  try {
    await apiFetch('/firmware/download', {
      method: 'POST',
      params: { target: target.value, kind }
    })
    await Promise.all([fetchSamsungFw(), fetchJobs()])
    showToast(t('downloadQueued'), 'warning')
  } catch (e) {
    reportError('failedFirmwareDownload', e)
  } finally {
    firmwareDownloadBusyKind.value = ''
  }
}

export const incrementalBases = ref([])
export const incrementalBase = ref('')
export const incrementalBusy = ref(false)
export const incrementalLoading = ref(false)
export const incrementalForJob = ref(null)

// Only builds of the same target that still have their target-files archive can
// serve as a base for the difference
export const retention = ref({ rom_zips: 0, target_files: 0 })
export const retentionBusy = ref(false)

export async function fetchRetention() {
  try {
    retention.value = await apiFetch('/settings/retention', { skipWorkspace: true })
  } catch (e) {
    reportError('retentionLoadFailed', e)
  }
}

export async function saveRetention(patch) {
  retentionBusy.value = true
  try {
    const data = await apiFetch('/settings/retention', { method: 'PATCH', json: patch, skipWorkspace: true })
    retention.value = { rom_zips: data.rom_zips, target_files: data.target_files }
    const removed = (data.removed?.rom_zips || 0) + (data.removed?.target_files || 0)
    showToast(removed ? `${t('retentionApplied')}: ${removed}` : t('saved'), 'success')
    await fetchArtifacts()
  } catch (e) {
    reportError('retentionSaveFailed', e)
  } finally {
    retentionBusy.value = false
  }
}

export async function queueDsuPackage(row) {
  const id = row.id || row.job_id
  try {
    const created = await apiFetch(`/jobs/${id}/dsu`, { method: 'POST' })
    showToast(t('dsuQueued'), 'success')
    await fetchJobs()
    if (created) selectJob(created)
  } catch (e) {
    reportError('failedDsu', e)
  }
}

export async function loadIncrementalBasesForTarget() {
  incrementalBases.value = []
  if (!capabilities.value.incremental_zip || !target.value) return
  incrementalLoading.value = true
  try {
    const data = await apiFetch('/artifacts/target/files', { params: { target: target.value } })
    incrementalBases.value = data.items || []
    if (!incrementalBases.value.some((x) => x.job_id === incrementalBaseForBuild.value)) {
      incrementalBaseForBuild.value = ''
    }
  } catch (e) {
    reportError('failedIncremental', e)
  } finally {
    incrementalLoading.value = false
  }
}

export async function openIncrementalModal(job) {
  incrementalForJob.value = job
  incrementalBases.value = []
  incrementalBase.value = ''
  incrementalLoading.value = true
  try {
    const data = await apiFetch('/artifacts/target/files', { params: { target: job.target } })
    incrementalBases.value = (data.items || []).filter((x) => x.job_id !== job.id)
    incrementalBase.value = incrementalBases.value[0]?.job_id || ''
  } catch (e) {
    reportError('failedIncremental', e)
  } finally {
    incrementalLoading.value = false
  }
}

export const deleteArtifactJob = ref(null)
export const deleteArtifactPick = ref({ rom: true, targetFiles: false })
export const deleteArtifactBusy = ref(false)

export function openDeleteArtifactModal(row) {
  const hasRom = Boolean(row.artifact_path || row.exists)
  const hasTargetFiles = Boolean(row.target_files_path || row.target_files_exists)
  deleteArtifactJob.value = {
    id: row.id || row.job_id,
    hasRom,
    hasTargetFiles,
    romSize: row.size_bytes || 0,
    targetFilesSize: row.target_files_size || 0
  }
  deleteArtifactPick.value = { rom: hasRom, targetFiles: !hasRom && hasTargetFiles }
}

export async function deleteArtifactConfirmed() {
  const row = deleteArtifactJob.value
  const pick = deleteArtifactPick.value
  if (!row || (!pick.rom && !pick.targetFiles)) return
  const kind = pick.rom && pick.targetFiles ? 'both' : pick.rom ? 'rom' : 'target_files'
  deleteArtifactBusy.value = true
  try {
    await apiFetch(`/jobs/${row.id}/artifact`, { method: 'DELETE', params: { kind } })
    deleteArtifactJob.value = null
    showToast(t('artifactDeleted'), 'success')
    await Promise.all([fetchJobs(), fetchArtifacts()])
    if (incrementalForJob.value) await openIncrementalModal(incrementalForJob.value)
  } catch (e) {
    reportError('artifactDeleteFailed', e)
  } finally {
    deleteArtifactBusy.value = false
  }
}

export async function queueIncrementalZip() {
  const job = incrementalForJob.value
  const base = incrementalBase.value
  if (!job || !base) return
  incrementalBusy.value = true
  try {
    const created = await apiFetch(`/jobs/${job.id}/incremental`, { method: 'POST', params: { base_job_id: base } })
    incrementalForJob.value = null
    showToast(t('incrementalQueued'), 'success')
    await fetchJobs()
    return created
  } catch (e) {
    reportError('failedIncremental', e)
  } finally {
    incrementalBusy.value = false
  }
}

export async function extractSamsungFwEntry(fwKey) {
  firmwareExtractBusyKey.value = fwKey
  try {
    await apiFetch(`/firmware/samsung/${encodeURIComponent(fwKey)}/extract`, {
      method: 'POST',
      params: { target: target.value }
    })
    await Promise.all([fetchSamsungFw(), fetchJobs()])
    showToast(t('extractQueued'), 'warning')
  } catch (e) {
    reportError('failedFirmwareExtract', e)
  } finally {
    firmwareExtractBusyKey.value = ''
  }
}

export async function deleteSamsungFwEntry(fwType, fwKey) {
  const ok = await confirm({
    title: t('delete'),
    message: t('firmwareDeleteConfirm', { type: fwType.toUpperCase(), key: fwKey }),
    confirmText: t('delete'),
    danger: true
  })
  if (!ok) return
  firmwareDeleteBusyKey.value = `${fwType}:${fwKey}`
  try {
    await apiFetch(`/firmware/samsung/${fwType}/${encodeURIComponent(fwKey)}`, {
      method: 'DELETE',
      params: { target: target.value }
    })
    showToast(t('deleteTaskQueued'), 'warning')
    await Promise.all([fetchSamsungFw(), fetchJobs(), fetchFirmwareStatus()])
  } catch (e) {
    reportError('failedSamsungFwDelete', e)
  } finally {
    firmwareDeleteBusyKey.value = ''
  }
}

// ---------------------------------------------------------------- mods / debloat / ff

export async function loadModsEntries() {
  modsLoading.value = true
  try {
    const data = await apiFetch('/mods/options')
    const entries = Array.isArray(data.entries) ? data.entries : []
    modsEntries.value = entries
    if (!modsTouched.value) {
      modsDisabledIds.value = entries.filter((x) => Boolean(x.default_disabled)).map((x) => x.id)
    }
  } catch (e) {
    reportError('failedModsLoad', e)
  } finally {
    modsLoading.value = false
  }
}

export function toggleMod(id) {
  modsTouched.value = true
  modsDisabledIds.value = modsDisabledIds.value.includes(id)
    ? modsDisabledIds.value.filter((x) => x !== id)
    : [...modsDisabledIds.value, id]
}

export function resetMods() {
  modsTouched.value = false
  modsDisabledIds.value = modsEntries.value.filter((x) => Boolean(x.default_disabled)).map((x) => x.id)
}

export async function loadModsFromJob(job) {
  if (!modsEntries.value.length) await loadModsEntries()
  modsDisabledIds.value = Array.from(new Set(parseJobModsDisabled(job)))
  modsTouched.value = true
  showToast(t('modsLoadedFromJob'), 'success')
}

export async function loadDebloatEntries() {
  debloatLoading.value = true
  try {
    const data = await apiFetch('/debloat/options')
    debloatEntries.value = data.entries || []
  } catch (e) {
    reportError('failedDebloatLoad', e)
  } finally {
    debloatLoading.value = false
  }
}

export function toggleDebloat(id) {
  debloatDisabledIds.value = debloatDisabledIds.value.includes(id)
    ? debloatDisabledIds.value.filter((x) => x !== id)
    : [...debloatDisabledIds.value, id]
}

export async function loadDebloatFromJob(job) {
  if (!debloatEntries.value.length) await loadDebloatEntries()
  debloatDisabledIds.value = Array.from(new Set(parseJobDebloatDisabled(job)))
  debloatAddSystemText.value = listToPathsText(parseJobDebloatAddSystem(job))
  debloatAddProductText.value = listToPathsText(parseJobDebloatAddProduct(job))
  showToast(t('debloatLoadedFromJob'), 'success')
}

export async function loadFFEntries() {
  if (!target.value) return
  ffLoading.value = true
  try {
    const data = await apiFetch('/floating/features', { params: { target: target.value } })
    ffEntries.value = data.entries || []
  } catch (e) {
    reportError('failedFFLoad', e)
  } finally {
    ffLoading.value = false
  }
}

export function effectiveFFValue(entry) {
  const override = ffOverrides.value?.[entry.key]
  return override === undefined || override === null || override === '' ? entry.value : String(override)
}

export function toggleFF(entry) {
  const current = effectiveFFValue(entry).toUpperCase()
  const next = current === 'TRUE' ? 'FALSE' : 'TRUE'
  const normalizedDefault = String(entry.value || '').toUpperCase()
  const nextOverrides = { ...(ffOverrides.value || {}) }
  if (next === normalizedDefault) delete nextOverrides[entry.key]
  else nextOverrides[entry.key] = next
  ffOverrides.value = nextOverrides
}

export function updateFFValue(entry, value) {
  const raw = String(value ?? '')
  const defaultValue = String(entry.value || '')
  const nextOverrides = { ...(ffOverrides.value || {}) }
  if (!raw && defaultValue) nextOverrides[entry.key] = ''
  else if (raw === defaultValue) delete nextOverrides[entry.key]
  else nextOverrides[entry.key] = raw
  ffOverrides.value = nextOverrides
}

export function useFFDefault(entry) {
  const nextOverrides = { ...(ffOverrides.value || {}) }
  delete nextOverrides[entry.key]
  ffOverrides.value = nextOverrides
}

export function clearFFOverrides() {
  ffOverrides.value = {}
}

export async function loadFFFromJob(job) {
  if (!ffEntries.value.length) await loadFFEntries()
  ffOverrides.value = { ...parseJobFFOverrides(job) }
  showToast(t('ffLoadedFromJob'), 'success')
}

// ---------------------------------------------------------------- uploads

// Repo mods and uploaded mods share one list: both are directories under
// unica/mods by the time the build applies them
function buildModsDisabled() {
  const repo = modsTouched.value ? modsDisabledIds.value : []
  const merged = [...repo, ...uploadedModsDisabled.value]
  if (!merged.length) return modsTouched.value ? [] : null
  return [...new Set(merged)]
}

export function setUploadFile(file) {
  uploadFile.value = file || null
  uploadError.value = ''
}

export function onUploadFileChanged(event) {
  uploadFile.value = event?.target?.files?.[0] || null
  uploadError.value = ''
}

export async function uploadModsArchive() {
  if (!uploadFile.value) {
    uploadError.value = t('chooseArchiveFirst')
    return
  }
  uploadBusy.value = true
  uploadError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    const data = await apiFetch('/mods/upload', { method: 'POST', body: fd })
    uploadedModsId.value = data.upload_id || ''
    uploadedMods.value = data.modules || []
  } catch (e) {
    uploadError.value = `${t('uploadFailed')}: ${e?.message || e}`
  } finally {
    uploadBusy.value = false
  }
}

export function clearUploadedMods() {
  uploadedModsId.value = ''
  uploadedMods.value = []
  uploadedModsDisabled.value = []
  uploadFile.value = null
}

// ---------------------------------------------------------------- artifacts

export async function fetchArtifacts() {
  artifactsLoading.value = true
  try {
    const data = await apiFetch('/artifacts/history', { params: { target: target.value } })
    artifacts.value = Array.isArray(data.items) ? data.items : []
  } catch (e) {
    reportError('artifactsLoadFailed', e)
  } finally {
    artifactsLoading.value = false
  }
}

// ---------------------------------------------------------------- settings

export async function fetchResources() {
  resourcesLoading.value = true
  try {
    resources.value = await apiFetch('/system/resources')
  } catch (e) {
    reportError('resourcesLoadFailed', e)
  } finally {
    resourcesLoading.value = false
  }
}

// The settings screen subscribes while it is visible; the server ticks, so the
// client never polls
let resourcesSocket = null
let resourcesFallbackTimer = null

export function watchResources() {
  if (resourcesSocket) return
  if (resourcesFallbackTimer) {
    clearInterval(resourcesFallbackTimer)
    resourcesFallbackTimer = null
  }
  resourcesSocket = createReconnectingSocket({
    path: '/system/resources/ws',
    params: { workspace: activeWorkspaceId.value },
    onOpen() {
      if (resourcesFallbackTimer) {
        clearInterval(resourcesFallbackTimer)
        resourcesFallbackTimer = null
      }
    },
    onClose() {
      if (resourcesFallbackTimer) return
      resourcesFallbackTimer = setInterval(fetchResources, 5000)
    },
    onMessage(payload) {
      resources.value = payload
      resourcesLoading.value = false
    }
  })
}

export function unwatchResources() {
  if (resourcesSocket) resourcesSocket.close()
  resourcesSocket = null
  if (resourcesFallbackTimer) clearInterval(resourcesFallbackTimer)
  resourcesFallbackTimer = null
}

export async function fetchAdvancedSettings() {
  advancedLoading.value = true
  try {
    const data = await apiFetch('/settings/advanced', { params: { target: target.value } })
    advancedSettings.value = { ...advancedSettings.value, ...data }
    advancedSourceOverrideInput.value = data.source_config_override || ''
    advancedTargetsOverrideInput.value = data.targets_override || ''
  } catch (e) {
    reportError('advancedLoadFailed', e)
  } finally {
    advancedLoading.value = false
  }
}

export async function saveAdvancedSettings(notify = true) {
  advancedBusy.value = true
  try {
    const data = await apiFetch('/settings/advanced', {
      method: 'PATCH',
      params: { target: target.value },
      json: {
        source_config_override: advancedSourceOverrideInput.value || '',
        targets_override: advancedTargetsOverrideInput.value || ''
      }
    })
    advancedSettings.value = { ...advancedSettings.value, ...data }
    advancedSourceOverrideInput.value = data.source_config_override || ''
    advancedTargetsOverrideInput.value = data.targets_override || ''
    if (notify) showToast(t('advancedSaved'), 'success')
    await fetchBuildSections()
  } catch (e) {
    reportError('advancedSaveFailed', e)
  } finally {
    advancedBusy.value = false
  }
}

let advancedSaveTimer = null

export function requestAdvancedSave() {
  if (advancedSaveTimer) clearTimeout(advancedSaveTimer)
  advancedSaveTimer = setTimeout(() => {
    advancedSaveTimer = null
    saveAdvancedSettings(true)
  }, 700)
}

export function toggleTargetOverride(code) {
  const set = new Set(pathsTextToList(advancedTargetsOverrideInput.value.replaceAll(/[\s,]+/g, '\n')))
  if (set.has(code)) set.delete(code)
  else set.add(code)
  advancedTargetsOverrideInput.value = Array.from(set).join('\n')
  requestAdvancedSave()
}

// ---------------------------------------------------------------- live streams

let sockets = []
let stateSocket = null
let restFallbackTimer = null

// A finished entry expires on the server by ttl, and that expiry is silent: no
// event ever says the bar can go. Dropping it here keeps a completed bar from
// hanging around until the page is reloaded
const TERMINAL_PROGRESS_LINGER_MS = 12000
const terminalTimers = new Map()

function dropProgress(store, key) {
  const next = { ...store.value }
  delete next[key]
  store.value = next
}

function applyHashUpdate(store, key, payload) {
  const timerKey = `${key}`
  clearTimeout(terminalTimers.get(timerKey))
  terminalTimers.delete(timerKey)

  if (payload.type === 'removed') {
    dropProgress(store, key)
    return
  }
  store.value = { ...store.value, [key]: payload }

  if (isTerminalProgress(payload)) {
    terminalTimers.set(
      timerKey,
      setTimeout(() => {
        terminalTimers.delete(timerKey)
        dropProgress(store, key)
      }, TERMINAL_PROGRESS_LINGER_MS)
    )
  }
}

function isTerminalProgress(payload) {
  return ['completed', 'failed', 'canceled'].includes(String(payload?.status || ''))
}

const SECTION_LOADING = {
  targets: targetsLoading,
  defaults: defaultsLoading,
  firmware: firmwareStatusLoading,
  repo: repoInfoLoading,
  jobs: jobsLoading
}

function markLoading(sections, value) {
  for (const name of sections) {
    const flag = SECTION_LOADING[name]
    if (flag) flag.value = value
  }
}

// Each section arrives on its own message, so the screen fills in as the server
// finishes each piece rather than all at once
function applySection(section, data) {
  serverAnswered()
  if (section === 'targets') {
    targetOptions.value = data.target_options || []
    fwScope.value = data.fw_scope || fwScope.value
    if (!targetOptions.value.some((x) => x.code === target.value)) {
      target.value = data.target || targetOptions.value[0]?.code || ''
    }
  } else if (section === 'defaults') {
    applyDefaults(data)
  } else if (section === 'firmware') {
    fwScope.value = data.fw_scope || fwScope.value
    firmwareStatus.value = data.firmware_status || {}
    targetFirmwareStatus.value = data.target_firmware_status || {}
  } else if (section === 'repo') {
    applyRepoInfo(data)
  } else if (section === 'jobs') {
    applyJobs(Array.isArray(data.items) ? data.items : [])
  }
  markLoading([section], false)
}

// The websocket is the normal transport; this only runs when it cannot connect
function startRestFallback() {
  if (restFallbackTimer) return
  refreshAllOverRest()
  restFallbackTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    refreshAllOverRest()
  }, 5000)
}

function stopRestFallback() {
  if (!restFallbackTimer) return
  clearInterval(restFallbackTimer)
  restFallbackTimer = null
}

async function refreshAllOverRest() {
  await Promise.all([fetchJobs(), fetchBuildSections()])
}

export function requestSections(sections, action = 'refresh') {
  const list = sections && sections.length ? sections : Object.keys(SECTION_LOADING)
  markLoading(list, true)
  const sent = stateSocket?.send({ action, sections: list, workspace: activeWorkspaceId.value, target: target.value })
  if (!sent) {
    markLoading(list, false)
    return false
  }
  return true
}

function connectSockets() {
  stateSocket = createReconnectingSocket({
    path: '/state/ws',
    params: { workspace: activeWorkspaceId.value, target: target.value },
    onOpen() {
      serverAnswered()
      stopRestFallback()
      markLoading(Object.keys(SECTION_LOADING), true)
    },
    onClose() {
      markLoading(Object.keys(SECTION_LOADING), false)
      startRestFallback()
    },
    onMessage(payload) {
      if (payload.type === 'section') {
        applySection(payload.section, payload.data || {})
        return
      }
      if (payload.type === 'section_error') {
        markLoading([payload.section], false)
        return
      }
    }
  })

  sockets = [
    stateSocket,
    createReconnectingSocket({
      path: '/firmware/progress/ws',
      onMessage(payload) {
        if (payload.type === 'snapshot' && Array.isArray(payload.items)) {
          const next = {}
          for (const item of payload.items) if (item?.key) next[item.key] = item
          firmwareProgress.value = next
          return
        }
        const key = payload.key || (payload.scope && payload.fw_key ? `${payload.scope}:${payload.fw_key}` : '')
        if (key) applyHashUpdate(firmwareProgress, key, payload)
      }
    }),
    createReconnectingSocket({
      path: '/repo/progress/ws',
      onMessage(payload) {
        if (payload.type === 'snapshot' && Array.isArray(payload.items)) {
          const next = {}
          for (const item of payload.items) if (item?.workspace_id) next[item.workspace_id] = item
          repoProgress.value = next
          return
        }
        if (payload.type === 'reset') {
          repoProgress.value = {}
          return
        }
        if (payload.workspace_id) applyHashUpdate(repoProgress, payload.workspace_id, payload)
      }
    }),
    createReconnectingSocket({
      path: '/build/progress/ws',
      onMessage(payload) {
        if (payload.type === 'snapshot' && Array.isArray(payload.items)) {
          const next = {}
          for (const item of payload.items) if (item?.job_id) next[item.job_id] = item
          buildProgress.value = next
          return
        }
        if (payload.job_id) applyHashUpdate(buildProgress, payload.job_id, payload)
      }
    })
  ]
}

function closeSockets() {
  sockets.forEach((s) => s.close())
  sockets = []
  stateSocket = null
  stopRestFallback()
}

export function restartSockets() {
  closeSockets()
  connectSockets()
  if (selectedJob.value?.log_path) openLogs(selectedJob.value.id)
}

// Workspaces and the mod list are user-driven lists. Everything else is pushed
// by the state socket the moment it connects, so it is only fetched here when
// that socket is unavailable
export async function refreshAll() {
  await fetchWorkspaces()
  await loadModsEntries()
  if (stateSocket?.isOpen()) return
  await fetchTargets()
  await Promise.all([fetchBuildSections(), fetchJobs()])
}

// Terminal progress entries carry an expiry from the server; drop them locally
// too so a finished bar fades out instead of sitting at 100% forever
function pruneExpiredProgress() {
  const now = Date.now() / 1000
  for (const store of [firmwareProgress, buildProgress, repoProgress]) {
    let changed = false
    const next = {}
    for (const [key, value] of Object.entries(store.value)) {
      if (value?.expires_at && Number(value.expires_at) < now) {
        changed = true
        continue
      }
      next[key] = value
    }
    if (changed) store.value = next
  }
}

let pruneTimer = null

export async function startApp() {
  const storedTail = Number(localStorage.getItem(STORAGE_LOG_TAIL_KB))
  if ([64, 128, 256, 512, 1024].includes(storedTail)) logTailKb.value = storedTail
  if (localStorage.getItem(STORAGE_FOLLOW_LOGS) === '0') followLogs.value = false

  await fetchAuthStatus()
  window.addEventListener('offline', handleOffline)
  window.addEventListener('online', handleOnline)
  if (typeof navigator !== 'undefined' && navigator.onLine === false) handleOffline()
  connectSockets()
  await refreshAll()
  if (selectedJob.value) selectJob(selectedJob.value)
  pruneTimer = setInterval(pruneExpiredProgress, 2000)
}

export function stopApp() {
  window.removeEventListener('offline', handleOffline)
  window.removeEventListener('online', handleOnline)
  closeLogs()
  closeSockets()
  if (jobsRefreshTimer) clearTimeout(jobsRefreshTimer)
  if (pruneTimer) clearInterval(pruneTimer)
  if (repoConfigTimer) clearTimeout(repoConfigTimer)
  if (advancedSaveTimer) clearTimeout(advancedSaveTimer)
}
