import { computed, ref } from 'vue'
import { apiFetch, downloadUrl } from './api.js'
import { idbDelete, idbGet, idbSet } from './idb.js'

// Blocks the server marks as changed are pulled with range requests, and several
// neighbours travel together up to this much at a time
const MAX_RANGE_BYTES = 64 * 1024 * 1024
const DIGEST_CHARS = 64
const RANGE_ATTEMPTS = 4

export const localUpdateRow = ref(null)
export const localUpdateFile = ref(null)
export const localUpdatePhase = ref('idle')
export const localUpdateError = ref('')
export const localUpdateBlocks = ref({ done: 0, total: 0, reused: 0, fetched: 0 })
export const localUpdateBytes = ref({ fetched: 0, total: 0 })
export const localUpdateResult = ref(null)
export const localUpdateResumable = ref(null)

let canceller = null
let baseHandle = null

const sessionKey = (jobId) => `localUpdate:${jobId}`

export const localUpdateBusy = computed(() => ['hashing', 'fetching', 'writing'].includes(localUpdatePhase.value))

export const localUpdatePercent = computed(() => {
  const { done, total } = localUpdateBlocks.value
  return total ? Math.round((done / total) * 100) : 0
})

export function openLocalUpdate(row) {
  localUpdateRow.value = row
  localUpdateFile.value = null
  localUpdatePhase.value = 'idle'
  localUpdateError.value = ''
  localUpdateBlocks.value = { done: 0, total: 0, reused: 0, fetched: 0 }
  localUpdateBytes.value = { fetched: 0, total: 0 }
  localUpdateResult.value = null
}

export function cancelLocalUpdate() {
  if (canceller) canceller.abort()
}

export function setLocalUpdateFile(file, handle = null) {
  localUpdateFile.value = file || null
  baseHandle = handle
  localUpdateResult.value = null
  localUpdateError.value = ''
}

export async function pickLocalBase() {
  if (typeof window.showOpenFilePicker !== 'function') return false
  const [handle] = await window.showOpenFilePicker({ multiple: false })
  setLocalUpdateFile(await handle.getFile(), handle)
  return true
}

// A tab that was closed halfway leaves the output file and the plan behind, and
// both handles come back only after the user grants them again
export async function findResumable(row) {
  localUpdateResumable.value = null
  const jobId = row?.id || row?.job_id
  if (!jobId) return
  const saved = await idbGet(sessionKey(jobId))
  if (saved && saved.done > 0 && saved.done < saved.total) localUpdateResumable.value = saved
}

async function allowed(handle, mode) {
  if (!handle) return false
  const options = { mode }
  if ((await handle.queryPermission?.(options)) === 'granted') return true
  return (await handle.requestPermission?.(options)) === 'granted'
}

async function digestOf(buffer) {
  const hash = await crypto.subtle.digest('SHA-512', buffer)
  const hex = Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('')
  return hex.slice(0, DIGEST_CHARS)
}

// Chromium hands out a real file, everyone else writes into the origin private
// area and gets the result as a download afterwards
async function openWriter(name, resumeHandle = null, position = 0) {
  const keep = { keepExistingData: position > 0 }
  if (resumeHandle) {
    const stream = await resumeHandle.createWritable(keep)
    if (position) await stream.seek(position)
    return { stream, kind: resumeHandle.kind === 'opfs' ? 'opfs' : 'disk', handle: resumeHandle }
  }
  if (typeof window.showSaveFilePicker === 'function') {
    const handle = await window.showSaveFilePicker({ suggestedName: name })
    const stream = await handle.createWritable(keep)
    if (position) await stream.seek(position)
    return { stream, kind: 'disk', handle }
  }
  const root = await navigator.storage.getDirectory()
  const handle = await root.getFileHandle(name, { create: true })
  const stream = await handle.createWritable(keep)
  if (position) await stream.seek(position)
  return { stream, kind: 'opfs', handle }
}

// A dropped connection mid transfer is the normal case on a long download, and
// a range request is cheap to repeat
async function fetchRange(url, start, end, signal) {
  let lastError = null
  for (let attempt = 0; attempt < RANGE_ATTEMPTS; attempt += 1) {
    if (signal.aborted) throw new Error('canceled')
    try {
      const response = await fetch(url, { headers: { Range: `bytes=${start}-${end - 1}` }, signal })
      if (!response.ok && response.status !== 206) {
        throw new Error(`range request failed with ${response.status}`)
      }
      return new Uint8Array(await response.arrayBuffer())
    } catch (error) {
      if (signal.aborted) throw error
      lastError = error
      await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt))
    }
  }
  throw lastError
}

function planRanges(missing, blockSize, totalSize) {
  const groups = []
  for (const index of missing) {
    const last = groups[groups.length - 1]
    const start = index * blockSize
    const end = Math.min(start + blockSize, totalSize)
    if (last && last.lastIndex === index - 1 && end - last.start <= MAX_RANGE_BYTES) {
      last.end = end
      last.lastIndex = index
      last.indexes.push(index)
      continue
    }
    groups.push({ start, end, firstIndex: index, lastIndex: index, indexes: [index] })
  }
  return groups
}

export async function runLocalUpdate(resume = null) {
  const row = localUpdateRow.value
  if (!row) return
  const jobId = row.id || row.job_id

  localUpdateError.value = ''
  localUpdateResult.value = null
  canceller = new AbortController()

  try {
    let file = localUpdateFile.value
    let writer = null
    let startBlock = 0

    if (resume) {
      if (!(await allowed(resume.base, 'read')) || !(await allowed(resume.out, 'readwrite'))) {
        throw new Error('access to the saved files was not granted')
      }
      file = await resume.base.getFile()
      baseHandle = resume.base
      startBlock = resume.done
    }
    if (!file) return

    localUpdatePhase.value = 'hashing'
    const map = await apiFetch(`/jobs/${jobId}/artifact/blockmap`)
    const blockSize = Number(map.block_size)
    const wanted = map.blocks || []
    if (resume && (resume.total !== wanted.length || resume.size !== Number(map.size))) {
      await idbDelete(sessionKey(jobId))
      throw new Error('the artifact changed since the interrupted run')
    }

    localUpdateBlocks.value = { done: startBlock, total: wanted.length, reused: 0, fetched: 0 }
    localUpdateBytes.value = { fetched: 0, total: Number(map.size) }

    const missing = []
    const reusable = new Set()
    for (let i = startBlock; i < wanted.length; i += 1) {
      if (canceller.signal.aborted) throw new Error('canceled')
      const start = i * blockSize
      if (start < file.size) {
        const slice = await file.slice(start, Math.min(start + blockSize, file.size)).arrayBuffer()
        if ((await digestOf(slice)) === wanted[i]) {
          reusable.add(i)
          localUpdateBlocks.value = { ...localUpdateBlocks.value, reused: localUpdateBlocks.value.reused + 1 }
          continue
        }
      }
      missing.push(i)
    }

    localUpdatePhase.value = 'fetching'
    writer = await openWriter(map.name, resume?.out || null, startBlock * blockSize)
    const url = downloadUrl(`/jobs/${jobId}/artifact`)
    const groups = planRanges(missing, blockSize, Number(map.size))
    const pending = new Map(groups.map((g) => [g.firstIndex, g]))

    const remember = (done) =>
      idbSet(sessionKey(jobId), {
        jobId,
        done,
        total: wanted.length,
        size: Number(map.size),
        name: map.name,
        base: baseHandle,
        out: writer.handle
      })

    try {
      for (let i = startBlock; i < wanted.length; i += 1) {
        let data
        if (reusable.has(i)) {
          const start = i * blockSize
          data = new Uint8Array(await file.slice(start, Math.min(start + blockSize, file.size)).arrayBuffer())
        } else {
          const group = pending.get(i)
          if (group) {
            group.buffer = await fetchRange(url, group.start, group.end, canceller.signal)
            localUpdateBytes.value = {
              ...localUpdateBytes.value,
              fetched: localUpdateBytes.value.fetched + group.buffer.byteLength
            }
          }
          const owner = groups.find((g) => i >= g.firstIndex && i <= g.lastIndex)
          const offset = i * blockSize - owner.start
          data = owner.buffer.subarray(offset, Math.min(offset + blockSize, owner.buffer.byteLength))
          if (i === owner.lastIndex) owner.buffer = null
          localUpdateBlocks.value = { ...localUpdateBlocks.value, fetched: localUpdateBlocks.value.fetched + 1 }
        }

        if ((await digestOf(data)) !== wanted[i]) {
          throw new Error(`block ${i} does not match the block map`)
        }
        await writer.stream.write(data)
        localUpdateBlocks.value = { ...localUpdateBlocks.value, done: i + 1 }
        if ((i + 1) % 4 === 0) await remember(i + 1)
      }

      localUpdatePhase.value = 'writing'
      await writer.stream.close()
      await idbDelete(sessionKey(jobId))
      localUpdateResumable.value = null
    } catch (error) {
      try {
        await writer?.stream.close()
      } catch {
        // Closing a stream that already failed changes nothing
      }
      throw error
    }

    if (writer.kind === 'opfs') {
      const stored = await writer.handle.getFile()
      localUpdateResult.value = { name: map.name, size: stored.size, url: URL.createObjectURL(stored) }
    } else {
      localUpdateResult.value = { name: map.name, size: Number(map.size), url: '' }
    }
    localUpdatePhase.value = 'done'
  } catch (error) {
    const canceled = canceller?.signal.aborted || String(error?.message || '') === 'canceled'
    localUpdateError.value = canceled ? '' : String(error?.message || error)
    localUpdatePhase.value = canceled ? 'idle' : 'error'
    if (canceled) await findResumable(row)
  } finally {
    canceller = null
  }
}
