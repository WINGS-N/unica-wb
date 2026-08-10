import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const pkg = JSON.parse(readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf8'))

// Releases are tagged vX.Y.Z and the tag is the only source of truth for the
// version. APP_VERSION covers the container build, where the checkout is copied
// without .git, and package.json only carries a placeholder
function resolveVersion() {
  const fromEnv = (process.env.APP_VERSION || '').trim()
  if (fromEnv) return fromEnv.replace(/^v/, '')
  try {
    const tag = execSync('git describe --tags --abbrev=0', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
    if (tag) return tag.replace(/^v/, '')
  } catch {
    // No git or no tags yet
  }
  return pkg.version
}

const version = resolveVersion()

export default defineConfig({
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
    // Stamps the service worker url, so a worker is only ever activated for the
    // build that registered it
    __APP_BUILD__: JSON.stringify(`${version}-${Date.now().toString(36)}`)
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api/v1': 'http://localhost:8000'
    }
  }
})
