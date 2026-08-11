// File handles survive a closed tab only inside IndexedDB, so the resume record
// lives here rather than in localStorage
const DB_NAME = 'un1ca'
const STORE = 'sessions'

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function run(mode, action) {
  return open().then(
    (db) =>
      new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, mode)
        const request = action(tx.objectStore(STORE))
        tx.oncomplete = () => {
          db.close()
          resolve(request?.result)
        }
        tx.onerror = () => {
          db.close()
          reject(tx.error)
        }
      })
  )
}

export function idbGet(key) {
  return run('readonly', (store) => store.get(key)).catch(() => undefined)
}

export function idbSet(key, value) {
  return run('readwrite', (store) => store.put(value, key)).catch(() => undefined)
}

export function idbDelete(key) {
  return run('readwrite', (store) => store.delete(key)).catch(() => undefined)
}
