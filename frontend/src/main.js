import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router/index.js'
import { bootServiceWorker } from './stores/pwa.js'
import './style.css'

createApp(App).use(router).mount('#app')

// Dev is served straight from vite, a worker there only caches stale modules
bootServiceWorker({ enabled: import.meta.env.PROD })
