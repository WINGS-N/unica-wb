<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { I18N, SUPPORTED_LANGS } from './lang/index.js'
import ToastStack from './components/ToastStack.vue'
import TopStatusBar from './components/TopStatusBar.vue'
import JobsPanel from './components/JobsPanel.vue'
import LogsPanel from './components/LogsPanel.vue'
import StopJobModal from './components/StopJobModal.vue'
import JobModsModal from './components/JobModsModal.vue'
import UploadModsModal from './components/UploadModsModal.vue'
import SamsungFwModal from './components/SamsungFwModal.vue'
import CommitModal from './components/CommitModal.vue'
import DebloatModal from './components/DebloatModal.vue'
import BuildQueuePanel from './components/BuildQueuePanel.vue'

// App держит общее состояние, сеть и WS, а UI раскладывается по компонентам
// App keep global state, api calls and ws streams, UI split to child components
const API_BASE = import.meta.env.VITE_API_BASE || ''
const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api/v1'
const STORAGE_SELECTED_JOB = 'un1ca:selectedJobId'
const STORAGE_LOG_TAIL_KB = 'un1ca:logTailKb'
const STORAGE_LANGUAGE = 'un1ca:lang'

const target = ref('')
const targetOptions = ref([])
const sourceFirmware = ref('')
const targetFirmware = ref('')
const latestArtifactAvailable = ref(false)
const versionMajor = ref(0)
const versionMinor = ref(0)
const versionPatch = ref(0)
const versionSuffix = ref('')
const force = ref(false)
const noRomZip = ref(false)
const jobs = ref([])
const selectedJob = ref(null)
const logs = ref('')
const loading = ref(false)
const defaultsLoading = ref(false)
const jobsLoading = ref(false)
const logTailKb = ref(64)
const stopModalOpen = ref(false)
const stopTargetJob = ref(null)
const stopSignalType = ref('sigterm')
const jobModsModalOpen = ref(false)
const jobModsModalJob = ref(null)
const jobModsModalModules = ref([])
const debloatModalOpen = ref(false)
const debloatEntries = ref([])
const debloatDisabledIds = ref([])
const debloatAddSystemText = ref('')
const debloatAddProductText = ref('')
const debloatLoading = ref(false)
const uploadModalOpen = ref(false)
const uploadFile = ref(null)
const uploadBusy = ref(false)
const uploadError = ref('')
const uploadedMods = ref([])
const uploadedModsId = ref('')
const language = ref('en')
const currentCommit = ref('unknown')
const currentCommitSubject = ref('')
const currentCommitDetails = ref({
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
const repoSync = ref({
  state: 'unknown',
  ahead_by: 0,
  behind_by: 0,
  remote_ref: ''
})
const repoPullBusy = ref(false)
const commitModalOpen = ref(false)
const firmwareStatus = ref({
  source_model: '',
  source_csc: '',
  latest_version: '',
  downloaded_version: '',
  extracted_version: '',
  up_to_date: false
})
const targetFirmwareStatus = ref({
  source_model: '',
  source_csc: '',
  latest_version: '',
  downloaded_version: '',
  extracted_version: '',
  up_to_date: false
})
const samsungFwModalOpen = ref(false)
const samsungFwLoading = ref(false)
const samsungFwItems = ref([])
const firmwareDeleteBusyKey = ref('')
const firmwareExtractBusyKey = ref('')
const firmwareProgress = ref({})
const activeLogJobId = ref('')
const toasts = ref([])
let toastSeq = 0
let evtSource = null
let firmwareProgressWs = null
let firmwareProgressReconnect = null
let firmwareProgressShouldReconnect = true
let timer = null

function t(key) {
  // Фолбэк на английский, если в выбранной локали нет ключа
  // Fallback to english when selected locale have no key
  return I18N[language.value]?.[key] || I18N.en[key] || key
}

function pushToast(message, type = 'info', timeoutMs = 4500) {
  // Не блокируем alert, показываем toast и авто-убираем по таймауту
  // No blocking alert, show toast and auto remove by timeout
  const id = `${Date.now()}-${++toastSeq}`
  toasts.value.push({ id, message, type })
  if (timeoutMs > 0) {
    setTimeout(() => {
      toasts.value = toasts.value.filter((x) => x.id !== id)
    }, timeoutMs)
  }
}

function dismissToast(id) {
  toasts.value = toasts.value.filter((x) => x.id !== id)
}

function toastClass(type) {
  if (type === 'success') return 'border-emerald-500/70 bg-emerald-500/15 text-emerald-200'
  if (type === 'warning') return 'border-amber-500/70 bg-amber-500/15 text-amber-100'
  if (type === 'error') return 'border-red-500/70 bg-red-500/15 text-red-200'
  return 'border-cyan-500/70 bg-cyan-500/15 text-cyan-100'
}

function stripAnsi(input) {
  // В браузерных логах ANSI-коды не нужны, чистим их
  // Browser log view no need terminal ANSI escape codes, we strip them
  return input.replace(
    // Регулярка для ESC-последовательностей терминала
    // Regex for terminal ESC sequences
    // eslint-disable-next-line no-control-regex
    /\u001b\[[0-?]*[ -/]*[@-~]/g,
    ''
  )
}

function parseJobMods(job) {
  if (!job?.extra_mods_modules_json) return []
  try {
    const arr = JSON.parse(job.extra_mods_modules_json)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function parseJobDebloatDisabled(job) {
  if (!job?.debloat_disabled_json) return []
  try {
    const arr = JSON.parse(job.debloat_disabled_json)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
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

function parseJobDebloatAddSystem(job) {
  return parseJsonList(job?.debloat_add_system_json)
}

function parseJobDebloatAddProduct(job) {
  return parseJsonList(job?.debloat_add_product_json)
}

function hasJobDebloatChanges(job) {
  return (
    parseJobDebloatDisabled(job).length > 0 ||
    parseJobDebloatAddSystem(job).length > 0 ||
    parseJobDebloatAddProduct(job).length > 0
  )
}

function pathsTextToList(text) {
  return Array.from(new Set((text || '').split('\n').map((x) => x.trim()).filter(Boolean)))
}

function listToPathsText(items) {
  return (Array.isArray(items) ? items : []).join('\n')
}

function loadDebloatFromJob(job, event) {
  // Быстрый импорт debloat-настроек из выбранной job в текущую форму
  // Fast import debloat settings from selected job into current form
  if (event) event.stopPropagation()
  if (!debloatEntries.value.length) {
    loadDebloatEntries()
  }
  const disabled = parseJobDebloatDisabled(job)
  const addSystem = parseJobDebloatAddSystem(job)
  const addProduct = parseJobDebloatAddProduct(job)
  debloatDisabledIds.value = Array.from(new Set(disabled))
  debloatAddSystemText.value = listToPathsText(addSystem)
  debloatAddProductText.value = listToPathsText(addProduct)
  debloatModalOpen.value = true
}

function debloatAddedCount() {
  return pathsTextToList(debloatAddSystemText.value).length + pathsTextToList(debloatAddProductText.value).length
}

function logsPlaceholder() {
  if (selectedJob.value && !selectedJob.value.log_path && (selectedJob.value.status === 'queued' || selectedJob.value.status === 'running')) {
    return t('waitingForWorkerLog')
  }
  return t('selectJobToStream')
}

function formatBytes(bytes) {
  const value = Number(bytes || 0)
  if (value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const scaled = value / (1024 ** idx)
  return `${scaled.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

function firmwareStatusToneClass(statusObj) {
  if (statusObj?.up_to_date) {
    return 'border-emerald-500/70 bg-emerald-500/10'
  }
  const hasLocal = Boolean(statusObj?.downloaded_version || statusObj?.extracted_version)
  if (hasLocal) {
    return 'border-amber-500/70 bg-amber-500/10'
  }
  return 'border-red-500/70 bg-red-500/10'
}

function repoSyncToneClass() {
  const state = repoSync.value?.state || 'unknown'
  if (state === 'up_to_date') return 'border-emerald-500/70 bg-emerald-500/10'
  if (state === 'behind' || state === 'ahead' || state === 'diverged') return 'border-amber-500/70 bg-amber-500/10'
  return 'border-red-500/70 bg-red-500/10'
}

function repoSyncText() {
  const state = repoSync.value?.state || 'unknown'
  if (state === 'up_to_date') return t('repoSyncUpToDate')
  if (state === 'behind') return `${t('repoSyncBehind')} (${repoSync.value?.behind_by || 0})`
  if (state === 'ahead') return `${t('repoSyncAhead')} (${repoSync.value?.ahead_by || 0})`
  if (state === 'diverged') return t('repoSyncDiverged')
  return t('repoSyncUnknown')
}

function deviceImageSvgData(code) {
  const label = (code || target.value || 'device').slice(0, 8)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72"><rect x="18" y="6" width="36" height="60" rx="8" fill="#111827" stroke="#334155" stroke-width="3"/><rect x="24" y="14" width="24" height="40" rx="3" fill="#0f172a"/><circle cx="36" cy="60" r="3" fill="#64748b"/><text x="36" y="40" text-anchor="middle" font-size="9" fill="#22d3ee" font-family="monospace">${label}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

function normalizeModelForImage(model) {
  const src = String(model || '').toUpperCase()
  const m = src.match(/^([A-Z]+-[A-Z]*\d+)/)
  return m ? m[1] : src
}

function targetDisplay(code) {
  const value = String(code || '').trim()
  if (!value) return 'unknown'
  const found = targetOptions.value.find((x) => x?.code === value)
  return found?.name ? `${value} - ${found.name}` : value
}

function jobTitle(job) {
  if (job?.operation_name) return job.operation_name
  return targetDisplay(job?.target)
}

function jobArtifactUrl(job) {
  return `${API_BASE}${API_PREFIX}/jobs/${job.id}/artifact`
}

function latestArtifactForTargetUrl() {
  // URL для кнопки Latest ZIP по выбранному target
  // URL endpoint for Latest ZIP button by selected target
  if (!target.value) return '#'
  return `${API_BASE}${API_PREFIX}/artifacts/latest/${encodeURIComponent(target.value)}`
}

function openLatestArtifactForTarget() {
  if (!target.value || !latestArtifactAvailable.value) return
  window.location.href = latestArtifactForTargetUrl()
}

function firmwareProgressKeyFromStatus(statusObj) {
  const model = String(statusObj?.source_model || '').trim().toUpperCase()
  const csc = String(statusObj?.source_csc || '').trim().toUpperCase()
  if (!model || !csc) return ''
  return `${model}_${csc}`
}

function firmwareProgressForStatus(statusObj) {
  // Маппим верхние статус-карточки к live progress по fw_key
  // Map top status cards to live progress by fw_key
  const key = firmwareProgressKeyFromStatus(statusObj)
  if (!key) return null
  return firmwareProgress.value[key] || null
}

function progressPct(progress) {
  const val = Number(progress?.percent ?? 0)
  if (!Number.isFinite(val)) return 0
  return Math.max(0, Math.min(100, Math.round(val)))
}

function progressTitle(progress) {
  return progress?.phase === 'extract' ? t('extractProgressLabel') : t('downloadProgressLabel')
}

function progressBarWidth(progress) {
  const pct = progressPct(progress)
  if ((progress?.status === 'running') && pct <= 0) return 8
  return pct
}

function openStopModalForProgress(progress, event) {
  // Stop из progress bar: пробуем найти job в списке, fallback по id если list ещё не обновился
  // Stop from progress bar: try find job in list, fallback by id if list not updated yet
  if (event) event.stopPropagation()
  const jobId = progress?.job_id
  if (!jobId) return
  const found = jobs.value.find((x) => x.id === jobId)
  openStopModal(found || { id: jobId, status: 'running' })
}

function formatDuration(sec) {
  const n = Number(sec || 0)
  if (!Number.isFinite(n) || n <= 0) return '0:00'
  const s = Math.floor(n)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  return `${m}:${String(r).padStart(2, '0')}`
}

function formatSpeed(bps) {
  const value = Number(bps || 0)
  if (!Number.isFinite(value) || value <= 0) return '0 B/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  const idx = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const scaled = value / (1024 ** idx)
  return `${scaled.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

async function fetchJobs() {
  jobsLoading.value = true
  try {
    const r = await fetch(`${API_BASE}${API_PREFIX}/jobs`)
    if (!r.ok) return
    jobs.value = await r.json()
    const selectedId = selectedJob.value?.id || localStorage.getItem(STORAGE_SELECTED_JOB)
    if (selectedId) {
      const found = jobs.value.find((x) => x.id === selectedId)
      if (found) {
        selectedJob.value = found
        ensureSelectedJobLogsAttached()
        return
      }
    }
    if (!selectedJob.value && jobs.value.length) {
      selectedJob.value = jobs.value[0]
    }
    ensureSelectedJobLogsAttached()
  } finally {
    jobsLoading.value = false
  }
}

async function fetchDefaults(selectedTarget) {
  // Единая точка для дефолтов формы, статусов и commit-инфо
  // Single endpoint load form defaults, statuses and commit info
  defaultsLoading.value = true
  try {
    const qs = selectedTarget ? `?target=${encodeURIComponent(selectedTarget)}` : ''
    const r = await fetch(`${API_BASE}${API_PREFIX}/defaults${qs}`)
    if (!r.ok) return
    const data = await r.json()
    targetOptions.value = data.target_options || []
    target.value = data.target || (targetOptions.value[0]?.code || '')
    sourceFirmware.value = data.defaults?.source_firmware || ''
    targetFirmware.value = data.defaults?.target_firmware || ''
    versionMajor.value = data.defaults?.version_major ?? 0
    versionMinor.value = data.defaults?.version_minor ?? 0
    versionPatch.value = data.defaults?.version_patch ?? 0
    versionSuffix.value = data.defaults?.version_suffix || ''
  currentCommit.value = data.current_commit || 'unknown'
  currentCommitSubject.value = data.current_commit_subject || ''
  currentCommitDetails.value = data.current_commit_details || currentCommitDetails.value
  repoSync.value = data.repo_sync || repoSync.value
    latestArtifactAvailable.value = Boolean(data.latest_artifact_available)
    firmwareStatus.value = data.firmware_status || firmwareStatus.value
    targetFirmwareStatus.value = data.target_firmware_status || targetFirmwareStatus.value
  } finally {
    defaultsLoading.value = false
  }
}

async function submitJob() {
  loading.value = true
  try {
    const r = await fetch(`${API_BASE}${API_PREFIX}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target: target.value,
        source_firmware: sourceFirmware.value,
        target_firmware: targetFirmware.value,
        version_major: Number(versionMajor.value),
        version_minor: Number(versionMinor.value),
        version_patch: Number(versionPatch.value),
        version_suffix: versionSuffix.value || null,
        extra_mods_upload_id: uploadedModsId.value || null,
        debloat_disabled: debloatDisabledIds.value,
        debloat_add_system: pathsTextToList(debloatAddSystemText.value),
        debloat_add_product: pathsTextToList(debloatAddProductText.value),
        force: force.value,
        no_rom_zip: noRomZip.value
      })
    })
    if (!r.ok) throw new Error(await r.text())
    const job = await r.json()
    selectedJob.value = job
    logs.value = ''
    await fetchJobs()
    if (job.log_path) {
      openLogs(job.id)
      pushToast(t('buildTaskQueued'), 'warning')
    } else if (job.status === 'reused') {
      logs.value = `${t('reusedArtifact')}: ${job.reused_from_job_id || 'unknown'}`
      pushToast(t('reusedArtifact'), 'success')
    } else {
      pushToast(t('buildTaskQueued'), 'warning')
    }
    uploadedModsId.value = ''
    uploadedMods.value = []
  } catch (e) {
    pushToast(`${t('failedSubmit')}: ${e.message}`, 'error')
  } finally {
    loading.value = false
  }
}

function openUploadModal() {
  uploadModalOpen.value = true
  uploadError.value = ''
}

function closeUploadModal() {
  uploadModalOpen.value = false
  uploadFile.value = null
  uploadError.value = ''
}

function onUploadFileChanged(event) {
  const f = event?.target?.files?.[0]
  uploadFile.value = f || null
}

function clearUploadedMods() {
  uploadedModsId.value = ''
  uploadedMods.value = []
}

async function loadDebloatEntries() {
  debloatLoading.value = true
  try {
    const r = await fetch(`${API_BASE}${API_PREFIX}/debloat/options`)
    if (!r.ok) throw new Error(await r.text())
    const data = await r.json()
    debloatEntries.value = data.entries || []
  } catch (e) {
    pushToast(`${t('failedDebloatLoad')}: ${e.message}`, 'error')
  } finally {
    debloatLoading.value = false
  }
}

async function fetchSamsungFw() {
  // Отдельно подгружаем Samsung FW cache для модалки
  // Separate load samsung fw cache for modal window
  samsungFwLoading.value = true
  try {
    const r = await fetch(`${API_BASE}${API_PREFIX}/firmware/samsung`)
    if (!r.ok) throw new Error(await r.text())
    const data = await r.json()
    samsungFwItems.value = Array.isArray(data.items) ? data.items : []
  } catch (e) {
    pushToast(`${t('failedSamsungFwLoad')}: ${e.message}`, 'error')
  } finally {
    samsungFwLoading.value = false
  }
}

async function openSamsungFwModal() {
  samsungFwModalOpen.value = true
  await fetchSamsungFw()
}

function closeSamsungFwModal() {
  samsungFwModalOpen.value = false
}

function openCommitModal() {
  commitModalOpen.value = true
}

function closeCommitModal() {
  commitModalOpen.value = false
}

async function pullRepository() {
  // Pull запускается из модалки Current Commit
  // Pull action start from Current Commit modal
  repoPullBusy.value = true
  try {
    const r = await fetch(`${API_BASE}${API_PREFIX}/repo/pull`, { method: 'POST' })
    if (!r.ok) throw new Error(await r.text())
    const data = await r.json()
    if (data?.commit) currentCommitDetails.value = data.commit
    currentCommit.value = data?.commit?.short_hash || currentCommit.value
    currentCommitSubject.value = data?.commit?.subject || currentCommitSubject.value
    if (data?.repo_sync) repoSync.value = data.repo_sync
    pushToast(t('repoPullSuccess'), 'success')
    await fetchDefaults(target.value || undefined)
  } catch (e) {
    pushToast(`${t('repoPullFailed')}: ${e.message}`, 'error')
  } finally {
    repoPullBusy.value = false
  }
}

async function deleteSamsungFwEntry(fwType, fwKey) {
  const busy = `${fwType}:${fwKey}`
  firmwareDeleteBusyKey.value = busy
  try {
    const r = await fetch(
      `${API_BASE}${API_PREFIX}/firmware/samsung/${fwType}/${encodeURIComponent(fwKey)}?target=${encodeURIComponent(target.value)}`,
      {
      method: 'DELETE'
      }
    )
    if (!r.ok) throw new Error(await r.text())
    pushToast(t('deleteTaskQueued'), 'warning')
    await fetchSamsungFw()
    await fetchDefaults(target.value || undefined)
  } catch (e) {
    pushToast(`${t('failedSamsungFwDelete')}: ${e.message}`, 'error')
  } finally {
    firmwareDeleteBusyKey.value = ''
  }
}

async function extractSamsungFwEntry(fwKey) {
  firmwareExtractBusyKey.value = fwKey
  try {
    const r = await fetch(`${API_BASE}${API_PREFIX}/firmware/samsung/${encodeURIComponent(fwKey)}/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target.value })
    })
    if (!r.ok) throw new Error(await r.text())
    await fetchSamsungFw()
    pushToast(t('extractQueued'), 'warning')
  } catch (e) {
    pushToast(`${t('failedFirmwareExtract')}: ${e.message}`, 'error')
  } finally {
    firmwareExtractBusyKey.value = ''
  }
}

async function openDebloatModal() {
  if (!debloatEntries.value.length) {
    await loadDebloatEntries()
  }
  debloatModalOpen.value = true
}

function closeDebloatModal() {
  debloatModalOpen.value = false
}

function toggleDebloat(id) {
  if (debloatDisabledIds.value.includes(id)) {
    debloatDisabledIds.value = debloatDisabledIds.value.filter((x) => x !== id)
  } else {
    debloatDisabledIds.value = [...debloatDisabledIds.value, id]
  }
}

function openJobModsModal(job, event) {
  if (event) event.stopPropagation()
  jobModsModalJob.value = job
  jobModsModalModules.value = parseJobMods(job)
  jobModsModalOpen.value = true
}

function closeJobModsModal() {
  jobModsModalOpen.value = false
  jobModsModalJob.value = null
  jobModsModalModules.value = []
}

async function uploadModsArchive() {
  if (!uploadFile.value) {
    uploadError.value = t('chooseArchiveFirst')
    return
  }
  uploadBusy.value = true
  uploadError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    const r = await fetch(`${API_BASE}${API_PREFIX}/mods/upload`, {
      method: 'POST',
      body: fd
    })
    if (!r.ok) {
      let msg = await r.text()
      try {
        const j = JSON.parse(msg)
        msg = j.detail || msg
      } catch {}
      throw new Error(msg)
    }
    const data = await r.json()
    uploadedModsId.value = data.upload_id || ''
    uploadedMods.value = data.modules || []
  } catch (e) {
    uploadError.value = `${t('uploadFailed')}: ${e.message}`
  } finally {
    uploadBusy.value = false
  }
}

function openStopModal(job, event) {
  if (event) event.stopPropagation()
  stopTargetJob.value = job
  stopSignalType.value = 'sigterm'
  stopModalOpen.value = true
}

function closeStopModal() {
  stopModalOpen.value = false
  stopTargetJob.value = null
}

async function stopJobConfirmed() {
  if (!stopTargetJob.value) return
  const jobId = stopTargetJob.value.id
  const r = await fetch(`${API_BASE}${API_PREFIX}/jobs/${jobId}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ signal_type: stopSignalType.value })
  })
  if (!r.ok) {
    pushToast(`${t('failedStop')}: ${await r.text()}`, 'error')
    return
  }
  pushToast(t('stopSignalQueued'), 'warning')
  closeStopModal()
  await fetchJobs()
  const updated = jobs.value.find((x) => x.id === jobId)
  if (updated) {
    selectedJob.value = updated
    if (updated.status === 'canceled') {
      logs.value += `\n${t('canceledByUser')}\n`
    }
  }
}

function selectJob(job) {
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

function closeLogs() {
  if (evtSource && typeof evtSource.close === 'function') {
    evtSource.close()
  }
  evtSource = null
  activeLogJobId.value = ''
}

function connectFirmwareProgressWs() {
  // Живой прогресс firmware через WS с авто-переподключением
  // Live firmware progress by ws with auto reconnect
  firmwareProgressShouldReconnect = true
  if (firmwareProgressWs && (firmwareProgressWs.readyState === WebSocket.OPEN || firmwareProgressWs.readyState === WebSocket.CONNECTING)) {
    return
  }
  const path = `${API_PREFIX}/firmware/progress/ws`
  let wsUrl = ''
  if (!API_BASE) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    wsUrl = `${proto}//${window.location.host}${path}`
  } else if (API_BASE.startsWith('http://') || API_BASE.startsWith('https://')) {
    const url = new URL(API_BASE)
    const proto = url.protocol === 'https:' ? 'wss:' : 'ws:'
    wsUrl = `${proto}//${url.host}${path}`
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    wsUrl = `${proto}//${window.location.host}${API_BASE}${path}`
  }
  firmwareProgressWs = new WebSocket(wsUrl)
  firmwareProgressWs.onmessage = (event) => {
    // Сначала принимаем snapshot, потом инкрементальные события
    // First receive snapshot, then incremental events
    let payload = null
    try {
      payload = JSON.parse(event.data)
    } catch {
      return
    }
    if (!payload) return
    if (payload.type === 'snapshot' && Array.isArray(payload.items)) {
      const next = {}
      for (const item of payload.items) {
        const key = item?.fw_key
        if (key) next[key] = item
      }
      firmwareProgress.value = next
      return
    }
    const key = payload?.fw_key
    if (payload.type === 'removed' && key) {
      const next = { ...firmwareProgress.value }
      delete next[key]
      firmwareProgress.value = next
      return
    }
    if (key) {
      firmwareProgress.value = {
        ...firmwareProgress.value,
        [key]: payload
      }
    }
  }
  firmwareProgressWs.onclose = () => {
    firmwareProgressWs = null
    if (!firmwareProgressShouldReconnect) return
    if (firmwareProgressReconnect) clearTimeout(firmwareProgressReconnect)
    firmwareProgressReconnect = setTimeout(() => connectFirmwareProgressWs(), 1500)
  }
}

function closeFirmwareProgressWs() {
  firmwareProgressShouldReconnect = false
  if (firmwareProgressReconnect) {
    clearTimeout(firmwareProgressReconnect)
    firmwareProgressReconnect = null
  }
  if (firmwareProgressWs && typeof firmwareProgressWs.close === 'function') {
    firmwareProgressWs.close()
  }
  firmwareProgressWs = null
}

function getWebSocketUrl(jobId) {
  // Строим WS URL из API_BASE и текущего протокола браузера
  // Build ws url from API_BASE and current browser protocol
  const path = `${API_PREFIX}/jobs/${jobId}/ws`
  if (!API_BASE) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${path}`
  }
  if (API_BASE.startsWith('http://') || API_BASE.startsWith('https://')) {
    const url = new URL(API_BASE)
    const proto = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${url.host}${path}`
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${API_BASE}${path}`
}

function openLogs(jobId) {
  // Лог читается по WS, \r обновляет текущую строку прогресса без лишних переносов
  // Logs stream by ws, \r rewrite current progress line and avoid fake new lines
  closeLogs()
  activeLogJobId.value = jobId
  evtSource = new WebSocket(`${getWebSocketUrl(jobId)}?tail_kb=${logTailKb.value}`)
  evtSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'chunk') {
        const chunk = stripAnsi(payload.chunk || '')
        for (const ch of chunk) {
          if (ch === '\r') {
            logs.value = logs.value.replace(/[^\n]*$/, '')
          } else {
            logs.value += ch
          }
        }
        if (logs.value.length > 2_000_000) {
          logs.value = logs.value.slice(-1_500_000)
        }
      }
    } catch {
      logs.value += stripAnsi(event.data || '') + '\n'
    }
    const el = document.getElementById('logs')
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }
  evtSource.onclose = () => {
    evtSource = null
    activeLogJobId.value = ''
  }
}

function ensureSelectedJobLogsAttached() {
  const job = selectedJob.value
  if (!job) return
  if (job.log_path && activeLogJobId.value !== job.id) {
    logs.value = ''
    openLogs(job.id)
  }
}

function onLogTailChange() {
  localStorage.setItem(STORAGE_LOG_TAIL_KB, String(logTailKb.value))
  if (selectedJob.value?.log_path) {
    logs.value = ''
    openLogs(selectedJob.value.id)
  }
}

function setLanguage(nextLang) {
  const safe = SUPPORTED_LANGS.includes(nextLang) ? nextLang : 'en'
  language.value = safe
  localStorage.setItem(STORAGE_LANGUAGE, safe)
  try {
    window.desktopApi?.setLanguage?.(safe)
    window.desktopApi?.setI18nStrings?.({
      exitConfirmTitle: I18N[safe]?.exitConfirmTitle || I18N.en.exitConfirmTitle,
      exitConfirmMessage: I18N[safe]?.exitConfirmMessage || I18N.en.exitConfirmMessage,
      exitConfirmDetail: I18N[safe]?.exitConfirmDetail || I18N.en.exitConfirmDetail,
      cancel: I18N[safe]?.cancel || I18N.en.cancel,
      exit: I18N[safe]?.exit || I18N.en.exit
    })
  } catch {}
}

onMounted(async () => {
  const storedLang = localStorage.getItem(STORAGE_LANGUAGE)
  if (storedLang) {
    setLanguage(storedLang)
  } else {
    setLanguage(language.value)
  }
  const storedTail = Number(localStorage.getItem(STORAGE_LOG_TAIL_KB))
  if ([64, 128, 256, 512, 1024].includes(storedTail)) {
    logTailKb.value = storedTail
  }
  await fetchDefaults()
  await fetchJobs()
  connectFirmwareProgressWs()
  if (selectedJob.value) {
    selectJob(selectedJob.value)
  }
  timer = setInterval(fetchJobs, 5000)
})

onUnmounted(() => {
  closeLogs()
  closeFirmwareProgressWs()
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-zinc-900 p-4 sm:p-6 lg:p-8">
    <ToastStack :toasts="toasts" :toast-class="toastClass" @dismiss="dismissToast" />
    <TopStatusBar
      :t="t"
      :defaults-loading="defaultsLoading"
      :repo-sync-class="repoSyncToneClass()"
      :repo-sync-text="repoSyncText()"
      :current-commit-details="currentCommitDetails"
      :current-commit="currentCommit"
      :current-commit-subject="currentCommitSubject"
      :firmware-status="firmwareStatus"
      :target-firmware-status="targetFirmwareStatus"
      :target="target"
      :language="language"
      :firmware-status-tone-class="firmwareStatusToneClass"
      :normalize-model-for-image="normalizeModelForImage"
      :device-image-svg-data="deviceImageSvgData"
      :firmware-progress-for-status="firmwareProgressForStatus"
      :progress-title="progressTitle"
      :progress-pct="progressPct"
      :progress-bar-width="progressBarWidth"
      :format-speed="formatSpeed"
      :format-duration="formatDuration"
      @open-commit="openCommitModal"
      @open-samsung-fw="openSamsungFwModal"
      @stop-progress="openStopModalForProgress"
      @set-language="setLanguage"
    />
    <div class="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-3">
      <BuildQueuePanel
        :t="t"
        v-model:target="target"
        :target-options="targetOptions"
        :latest-artifact-available="latestArtifactAvailable"
        v-model:source-firmware="sourceFirmware"
        v-model:target-firmware="targetFirmware"
        v-model:version-major="versionMajor"
        v-model:version-minor="versionMinor"
        v-model:version-patch="versionPatch"
        v-model:version-suffix="versionSuffix"
        v-model:force="force"
        v-model:no-rom-zip="noRomZip"
        :loading="loading"
        :debloat-disabled-count="debloatDisabledIds.length"
        :uploaded-mods-id="uploadedModsId"
        :uploaded-mods-count="uploadedMods.length"
        @target-change="fetchDefaults"
        @submit="submitJob"
        @open-upload="openUploadModal"
        @open-debloat="openDebloatModal"
        @open-latest="openLatestArtifactForTarget"
        @clear-uploaded-mods="clearUploadedMods"
      />

      <JobsPanel
        :t="t"
        :jobs-loading="jobsLoading"
        :jobs="jobs"
        :selected-job="selectedJob"
        :job-title="jobTitle"
        :parse-job-mods="parseJobMods"
        :parse-job-debloat-disabled="parseJobDebloatDisabled"
        :parse-job-debloat-add-system="parseJobDebloatAddSystem"
        :parse-job-debloat-add-product="parseJobDebloatAddProduct"
        :has-job-debloat-changes="hasJobDebloatChanges"
        :job-artifact-url="jobArtifactUrl"
        @select-job="selectJob"
        @open-stop="openStopModal"
        @open-mods="openJobModsModal"
        @load-debloat="loadDebloatFromJob"
      />

      <LogsPanel
        v-model:log-tail-kb="logTailKb"
        :t="t"
        :selected-job="selectedJob"
        :logs="logs"
        :logs-placeholder="logsPlaceholder()"
        :api-base="API_BASE"
        :api-prefix="API_PREFIX"
        @log-tail-change="onLogTailChange"
      />
    </div>
    <StopJobModal
      :open="stopModalOpen"
      :t="t"
      :stop-target-job="stopTargetJob"
      v-model:stop-signal-type="stopSignalType"
      @close="closeStopModal"
      @confirm="stopJobConfirmed"
    />
    <JobModsModal
      :open="jobModsModalOpen"
      :t="t"
      :job="jobModsModalJob"
      :modules="jobModsModalModules"
      @close="closeJobModsModal"
    />
    <UploadModsModal
      :open="uploadModalOpen"
      :t="t"
      :upload-error="uploadError"
      :uploaded-mods="uploadedMods"
      :upload-busy="uploadBusy"
      @close="closeUploadModal"
      @file-change="onUploadFileChanged"
      @upload="uploadModsArchive"
    />
    <SamsungFwModal
      :open="samsungFwModalOpen"
      :t="t"
      :samsung-fw-loading="samsungFwLoading"
      :samsung-fw-items="samsungFwItems"
      :target="target"
      :firmware-progress="firmwareProgress"
      :firmware-delete-busy-key="firmwareDeleteBusyKey"
      :firmware-extract-busy-key="firmwareExtractBusyKey"
      :normalize-model-for-image="normalizeModelForImage"
      :device-image-svg-data="deviceImageSvgData"
      :progress-title="progressTitle"
      :progress-pct="progressPct"
      :progress-bar-width="progressBarWidth"
      :format-speed="formatSpeed"
      :format-duration="formatDuration"
      :format-bytes="formatBytes"
      @close="closeSamsungFwModal"
      @stop-progress="openStopModalForProgress"
      @extract-entry="extractSamsungFwEntry"
      @delete-entry="deleteSamsungFwEntry"
    />
    <CommitModal
      :open="commitModalOpen"
      :t="t"
      :repo-pull-busy="repoPullBusy"
      :defaults-loading="defaultsLoading"
      :repo-sync-text="repoSyncText()"
      :repo-sync="repoSync"
      :current-commit-details="currentCommitDetails"
      :current-commit="currentCommit"
      @close="closeCommitModal"
      @pull="pullRepository"
    />
    <DebloatModal
      :open="debloatModalOpen"
      :t="t"
      :debloat-loading="debloatLoading"
      :debloat-entries="debloatEntries"
      :debloat-disabled-ids="debloatDisabledIds"
      :debloat-added-count="debloatAddedCount()"
      v-model:debloat-add-system-text="debloatAddSystemText"
      v-model:debloat-add-product-text="debloatAddProductText"
      @close="closeDebloatModal"
      @toggle="toggleDebloat"
    />
  </div>
</template>
