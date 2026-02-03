import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('startupApi', {
  onProgress(callback) {
    ipcRenderer.on('startup:progress', (_event, payload) => callback(payload))
  },
  onError(callback) {
    ipcRenderer.on('startup:error', (_event, payload) => callback(payload))
  },
  onSudoRequest(callback) {
    ipcRenderer.on('startup:sudo-request', (_event, payload) => callback(payload))
  },
  submitSudoPassword(password) {
    ipcRenderer.send('startup:sudo-password-submit', { password })
  },
  cancelSudoPassword() {
    ipcRenderer.send('startup:sudo-password-cancel')
  },
  getLastProgress() {
    return ipcRenderer.invoke('startup:get-last-progress')
  },
  getLogTail() {
    return ipcRenderer.invoke('startup:get-log-tail')
  },
  retry() {
    return ipcRenderer.invoke('startup:retry')
  }
})

contextBridge.exposeInMainWorld('desktopApi', {
  setLanguage(lang) {
    ipcRenderer.send('app:set-language', lang)
  },
  setI18nStrings(payload) {
    ipcRenderer.send('app:set-i18n-strings', payload)
  }
})
