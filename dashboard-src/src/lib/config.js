// Reads window.DASHBOARD_CONFIG (set by dashboard/config.js) and checks it before we
// ever talk to Supabase, so a bad setting shows a plain-English message instead of a
// blank page.

const PLACEHOLDER = /PASTE_|YOUR_PROJECT|YOUR_ANON|your-project-ref/i

function decodeJwtPayload(key) {
  const parts = key.split('.')
  if (parts.length !== 3) return null
  try {
    let b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    while (b64.length % 4) b64 += '='
    return JSON.parse(atob(b64))
  } catch {
    return null
  }
}

export function readConfig() {
  if (window.__DASHBOARD_CONFIG_LOAD_ERROR) {
    return { ok: false, problem: 'syntax', detail: String(window.__DASHBOARD_CONFIG_LOAD_ERROR) }
  }

  const c = window.DASHBOARD_CONFIG
  if (!c || typeof c !== 'object') return { ok: false, problem: 'missing' }

  const url = String(c.supabaseUrl || '')
    .trim()
    .replace(/\/+$/, '')
    .replace(/\/rest\/v1$/, '')
  const key = String(c.supabaseAnonKey || '').trim()
  const dealershipName = String(c.dealershipName || '').trim()

  if (!url || PLACEHOLDER.test(url)) return { ok: false, problem: 'url-missing' }
  if (!/^https?:\/\/[^\s/]+$/.test(url)) return { ok: false, problem: 'url-bad', value: url }
  if (!key || PLACEHOLDER.test(key)) return { ok: false, problem: 'key-missing' }

  // New-style Supabase keys
  if (key.startsWith('sb_secret_')) return { ok: false, problem: 'service-key' }
  if (key.startsWith('sb_publishable_')) {
    return { ok: true, url, key, dealershipName: PLACEHOLDER.test(dealershipName) ? '' : dealershipName }
  }

  // Classic keys are JWTs. Check which role the key carries, and which project.
  const payload = decodeJwtPayload(key)
  if (!payload) return { ok: false, problem: 'key-bad' }
  if (payload.role === 'service_role') return { ok: false, problem: 'service-key' }

  const hostRef = (url.match(/^https?:\/\/([^.]+)\.supabase\.co$/) || [])[1]
  if (hostRef && payload.ref && hostRef !== payload.ref) {
    return { ok: false, problem: 'key-mismatch', urlRef: hostRef, keyRef: payload.ref }
  }

  return { ok: true, url, key, dealershipName }
}
