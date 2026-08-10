import { execSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { brotliCompressSync, constants, gzipSync } from 'node:zlib'
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

// Fingerprint of everything the bundle is built from. A timestamp would
// change on every run, announcing an update after a rebuild that produced the
// same bytes; a digest of the inputs moves only when the output can
function sourceFingerprint() {
  const roots = ['src', 'public', 'index.html', 'package.json', 'vite.config.js', 'tailwind.config.js']
  const hash = createHash('md5')
  const visit = (entry) => {
    let info
    try {
      info = statSync(entry)
    } catch {
      return
    }
    if (info.isDirectory()) {
      for (const name of readdirSync(entry).sort()) visit(join(entry, name))
      return
    }
    hash.update(entry)
    hash.update(readFileSync(entry))
  }
  for (const root of roots) visit(root)
  return hash.digest('hex').slice(0, 7)
}

const version = resolveVersion()
const build = `${version}-${sourceFingerprint()}`

const COMPRESSIBLE = /\.(js|mjs|css|html|json|svg|webmanifest|txt|map|ico)$/i
// Below this the framing overhead eats the win and the request is one packet
// either way
const MIN_BYTES = 1024

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) yield* walk(full)
    else yield full
  }
}

// Compressing once at build time lets the server hand out the bytes as they
// are, at a level no on-the-fly compressor would spend the cpu on
function precompress() {
  return {
    name: 'precompress-assets',
    apply: 'build',
    closeBundle() {
      const outDir = fileURLToPath(new URL('./dist', import.meta.url))
      let saved = 0
      let count = 0
      for (const file of walk(outDir)) {
        if (!COMPRESSIBLE.test(file)) continue
        const raw = readFileSync(file)
        if (raw.length < MIN_BYTES) continue

        const br = brotliCompressSync(raw, {
          params: {
            [constants.BROTLI_PARAM_QUALITY]: constants.BROTLI_MAX_QUALITY,
            [constants.BROTLI_PARAM_SIZE_HINT]: raw.length,
            [constants.BROTLI_PARAM_LGWIN]: 24
          }
        })
        const gz = gzipSync(raw, { level: constants.Z_BEST_COMPRESSION })

        // A variant bigger than the source would only waste a round trip
        if (br.length < raw.length) {
          writeFileSync(`${file}.br`, br)
          saved += raw.length - br.length
          count += 1
        }
        if (gz.length < raw.length) writeFileSync(`${file}.gz`, gz)
      }
      // Stamped so a packaging step can refuse a build staged for another version
      writeFileSync(join(outDir, 'version.txt'), version)
      const kb = (n) => `${(n / 1024).toFixed(1)} kB`
      console.log(`precompress: ${count} files, ${kb(saved)} saved with brotli`)
    }
  }
}

export default defineConfig({
  plugins: [vue(), precompress()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
    // Stamps the service worker url, so a worker is only ever activated for the
    // build that registered it
    __APP_BUILD__: JSON.stringify(build)
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api/v1': 'http://localhost:8000'
    }
  }
})
