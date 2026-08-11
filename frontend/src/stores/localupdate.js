import { computed, ref } from 'vue'
import { apiFetch, downloadUrl } from './api.js'

// Blocks the server marks as changed are pulled with range requests, and several
// neighbours travel together up to this much at a time
const MAX_RANGE_BYTES = 64 * 1024 * 1024
const DIGEST_CHARS = 64

export const localUpdateRow = ref(null)
export const localUpdateFile = ref(null)
export const localUpdatePhase = ref('idle')
export const localUpdateError = ref('')
export const localUpdateBlocks = ref({ done: 0, total: 0, reused: 0, fetched: 0 })
export const localUpdateBytes = ref({ fetched: 0, total: 0 })
export const localUpdateResult = ref(null)

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

export function setLocalUpdateFile(file) {
  localUpdateFile.value = file || null
  localUpdateResult.value = null
  localUpdateError.value = ''
}

async function digestOf(buffer) {
  const hash = await crypto.subtle.digest('SHA-512', buffer)
  const hex = Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('')
  return hex.slice(0, DIGEST_CHARS)
}

// Chromium hands out a real file, everyone else writes into the origin private
// area and gets the result as a download afterwards
async function openWriter(name) {
  if (typeof window.showSaveFilePicker === 'function') {
    const handle = await window.showSaveFilePicker({ suggestedName: name })
    return { stream: await handle.createWritable(), kind: 'disk', handle }
  }
  const root = await navigator.storage.getDirectory()
  const handle = await root.getFileHandle(name, { create: true })
  return { stream: await handle.createWritable(), kind: 'opfs', handle }
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

export async function runLocalUpdate() {
  const row = localUpdateRow.value
  const file = localUpdateFile.value
  if (!row || !file) return

  localUpdateError.value = ''
  localUpdateResult.value = null
  const jobId = row.id || row.job_id

  try {
    localUpdatePhase.value = 'hashing'
    const map = await apiFetch(`/jobs/${jobId}/artifact/blockmap`)
    const blockSize = Number(map.block_size)
    const wanted = map.blocks || []
    localUpdateBlocks.value = { done: 0, total: wanted.length, reused: 0, fetched: 0 }
    localUpdateBytes.value = { fetched: 0, total: Number(map.size) }

    const missing = []
    const reusable = new Set()
    for (let i = 0; i < wanted.length; i += 1) {
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
    const writer = await openWriter(map.name)
    const url = downloadUrl(`/jobs/${jobId}/artifact`)
    const groups = planRanges(missing, blockSize, Number(map.size))
    const pending = new Map(groups.map((g) => [g.firstIndex, g]))

    try {
      for (let i = 0; i < wanted.length; i += 1) {
        let data
        if (reusable.has(i)) {
          const start = i * blockSize
          data = new Uint8Array(await file.slice(start, Math.min(start + blockSize, file.size)).arrayBuffer())
        } else {
          const group = pending.get(i)
          if (group) {
            const response = await fetch(url, { headers: { Range: `bytes=${group.start}-${group.end - 1}` } })
            if (!response.ok && response.status !== 206) {
              throw new Error(`range request failed with ${response.status}`)
            }
            group.buffer = new Uint8Array(await response.arrayBuffer())
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
      }

      localUpdatePhase.value = 'writing'
      await writer.stream.close()
    } catch (error) {
      try {
        await writer.stream.abort()
      } catch {
        // The stream is already gone, nothing left to undo
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
    localUpdateError.value = String(error?.message || error)
    localUpdatePhase.value = 'error'
  }
}
