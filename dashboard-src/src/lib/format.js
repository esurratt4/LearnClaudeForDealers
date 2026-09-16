export function fmt$(v) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  const n = Number(v)
  const s = '$' + Math.abs(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
  return n < 0 ? '-' + s : s
}

export function fmt$Short(v) {
  if (v == null) return '--'
  const n = Number(v)
  if (Math.abs(n) >= 1_000_000) return '$' + (n / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(n) >= 10_000) return '$' + Math.round(n / 1000) + 'K'
  return fmt$(n)
}

export function fmtNum(v, digits = 0) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtDate(d) {
  if (!d) return '--'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtDateTime(d) {
  if (!d) return '--'
  return new Date(d).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function fmtAgo(d) {
  if (!d) return 'never'
  const mins = Math.round((Date.now() - new Date(d).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} hr ago`
  const days = Math.round(hrs / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

export function avg(nums) {
  const clean = nums.filter(n => n != null && !Number.isNaN(n))
  return clean.length ? clean.reduce((a, b) => a + b, 0) / clean.length : null
}

// Save rows as a CSV file the user can open in Excel.
export function downloadCSV(filename, columns, rows) {
  const esc = (val) => {
    if (val == null) return ''
    const s = String(val)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [columns.map(c => esc(c.label)).join(',')]
  for (const r of rows) lines.push(columns.map(c => esc(c.csv ? c.csv(r) : r[c.key])).join(','))
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
