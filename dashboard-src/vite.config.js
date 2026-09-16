// Build settings for the dashboard.
//
// `npm run build` writes the finished site into ../dashboard (index.html + assets/),
// which is what `python3 -m http.server 8000 --directory dashboard` serves.
//
// Three settings matter:
//   base: './'          every asset path is relative, so the site works from any folder
//   emptyOutDir: false  ../dashboard also holds config.js, config.example.js and
//                       README.md, which the build must never delete
//   clean-old-assets    deletes ONLY ../dashboard/assets before each build, so old
//                       bundles do not pile up
//
// Your Supabase URL and key are NOT baked in here. The page reads them at runtime
// from dashboard/config.js.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { rmSync, readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const outDir = fileURLToPath(new URL('../dashboard', import.meta.url))
const assetsDir = fileURLToPath(new URL('../dashboard/assets', import.meta.url))
const configFile = fileURLToPath(new URL('../dashboard/config.js', import.meta.url))

export default defineConfig({
  base: './',
  publicDir: false,
  plugins: [
    react(),
    tailwindcss(),
    {
      // `npm run dev` only: serve the real ../dashboard/config.js so the dev server
      // talks to the same database as the built site.
      name: 'serve-dashboard-config',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (!req.url || !req.url.split('?')[0].endsWith('/config.js')) return next()
          if (!existsSync(configFile)) { res.statusCode = 404; return res.end() }
          res.setHeader('Content-Type', 'text/javascript')
          res.end(readFileSync(configFile))
        })
      },
    },
    {
      name: 'clean-old-assets',
      apply: 'build',
      buildStart() {
        rmSync(assetsDir, { recursive: true, force: true })
      },
    },
  ],
  build: {
    outDir,
    emptyOutDir: false,
    assetsDir: 'assets',
    chunkSizeWarningLimit: 2000,
  },
})
