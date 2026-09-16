// Full-page messages for when there is nothing to chart yet: settings missing, keys
// wrong, tables not built, or a connected-but-empty database. Each one says what
// happened and exactly what to do next. The dashboard never shows a blank screen.

import { useState } from 'react'
import { AlertOctagon, Check, Copy, Database, KeyRound, Loader2, RefreshCw, WifiOff } from 'lucide-react'
import { fmtDateTime } from '../lib/format'

function Frame({ icon: Icon, tone = 'neutral', title, children }) {
  const iconStyle = tone === 'bad'
    ? { background: '#EDD5CF', color: '#6B2418' }
    : tone === 'good'
      ? { background: '#D6EAD9', color: '#2D5E38' }
      : { background: '#E6EFEE', color: '#2D7A74' }
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-10">
      <div className="animate-fade-in w-full max-w-2xl rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm">
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl" style={iconStyle}>
          <Icon className="h-7 w-7" />
        </div>
        <h1 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900">{title}</h1>
        <div className="space-y-4 text-lg leading-relaxed text-zinc-600">{children}</div>
      </div>
    </div>
  )
}

export function SayThis({ children }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(children)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked: the text is still on screen */ }
  }
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Paste this into Claude Code</span>
        <button onClick={copy} className="flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-zinc-600 hover:bg-white">
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <p className="font-medium text-zinc-900">{children}</p>
    </div>
  )
}

function RetryButton({ onClick, label = 'Try again' }) {
  return (
    <button
      onClick={onClick || (() => window.location.reload())}
      className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-5 py-2.5 text-base font-medium text-white hover:bg-zinc-700"
    >
      <RefreshCw className="h-4 w-4" />
      {label}
    </button>
  )
}

export function LoadingScreen() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-3 text-zinc-500">
      <Loader2 className="h-8 w-8 animate-spin text-home" />
      <p className="text-lg">Loading your market...</p>
    </div>
  )
}

const FIX_CONFIG = 'Fix my dashboard config: put my Supabase Project URL and anon key in dashboard/config.js, using dashboard/config.example.js as the template.'

export function ConfigProblem({ problem }) {
  const messages = {
    missing: {
      title: 'The dashboard has no settings yet',
      body: <p>The file <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code> is missing. It tells the dashboard where your database is. It is created from <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.example.js</code>.</p>,
    },
    syntax: {
      title: 'The settings file has a typo',
      body: <p><code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code> exists but could not be read. Usually a missing quote or comma around a pasted key. ({problem.detail})</p>,
    },
    'url-missing': {
      title: 'Your Supabase Project URL is not filled in',
      body: <p>In <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code>, <b>supabaseUrl</b> is still empty or a placeholder. It comes from Supabase: Project Settings, Data API, Project URL.</p>,
    },
    'url-bad': {
      title: 'The Project URL does not look right',
      body: <p><b>supabaseUrl</b> is set to <code className="break-all rounded bg-zinc-100 px-1.5 py-0.5 text-base">{problem.value}</code>. It should look like <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">https://abcdefghijklmnop.supabase.co</code> with nothing after it.</p>,
    },
    'key-missing': {
      title: 'Your anon key is not filled in',
      body: <p>In <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code>, <b>supabaseAnonKey</b> is still empty or a placeholder. It comes from Supabase: Project Settings, API Keys, the <b>anon</b> key.</p>,
    },
    'key-bad': {
      title: 'The anon key looks cut off',
      body: <p>The key in <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code> is not a complete Supabase key. It is a long string starting with <b>eyJ</b> with two dots in it. Copy it again from Project Settings, API Keys.</p>,
    },
    'key-mismatch': {
      title: 'The key belongs to a different Supabase project',
      body: <p>Your URL points at project <b>{problem.urlRef}</b>, but the anon key is for project <b>{problem.keyRef}</b>. Copy both from the same project.</p>,
    },
    'service-key': {
      title: 'That is the service_role key. The dashboard refuses to use it.',
      body: (
        <>
          <p>The service_role key can change or delete everything in your database, and anything a web page loads can be seen by whoever opens it. The dashboard only needs the <b>anon</b> key, which is read-only.</p>
          <p>Replace it with the <b>anon</b> key from Project Settings, API Keys. The service_role key belongs only in your <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">.env</code> file.</p>
        </>
      ),
    },
  }
  const m = messages[problem.problem] || messages.missing
  return (
    <Frame icon={KeyRound} tone="bad" title={m.title}>
      {m.body}
      <SayThis>{FIX_CONFIG}</SayThis>
      <p className="text-base text-zinc-500">When it is fixed, reload this page.</p>
      <RetryButton label="Reload" />
    </Frame>
  )
}

export function ConnectionProblem({ error, retry }) {
  if (error.kind === 'network') {
    return (
      <Frame icon={WifiOff} tone="bad" title="Could not reach your database">
        <p>The page could not connect to Supabase. Either the internet connection dropped, or the Project URL in <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code> has a typo.</p>
        <p>Also check the address bar says <b>http://localhost:8000</b>. Opening the file by double-clicking it does not work.</p>
        <RetryButton onClick={retry} />
      </Frame>
    )
  }
  if (error.kind === 'key') {
    return (
      <Frame icon={KeyRound} tone="bad" title="Supabase did not accept the key">
        <p>Your database answered, so the URL is right, but it rejected the anon key in <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">dashboard/config.js</code>. It was probably copied incompletely or from another project.</p>
        <SayThis>{FIX_CONFIG}</SayThis>
        <RetryButton label="Reload" />
      </Frame>
    )
  }
  if (error.kind === 'no-tables') {
    return (
      <Frame icon={Database} tone="bad" title="Your database has no tables yet">
        <p>The dashboard connected, but the tables it reads are not there. They are built by running <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">sql/schema.sql</code> in Supabase.</p>
        <ol className="list-decimal space-y-1 pl-6">
          <li>In Claude Code, say: <b>Copy the contents of sql/schema.sql to my clipboard.</b></li>
          <li>In Supabase, click <b>SQL Editor</b>, then <b>New query</b>.</li>
          <li>Paste, click <b>Run</b>, and wait for <b>Success. No rows returned.</b></li>
        </ol>
        <RetryButton onClick={retry} />
      </Frame>
    )
  }
  if (error.kind === 'permission') {
    return (
      <Frame icon={KeyRound} tone="bad" title="The database will not let the dashboard read">
        <p>The tables exist, but the read-only key has not been given permission to read them. Running <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-base">sql/schema.sql</code> again in the Supabase SQL Editor sets those permissions. It is safe to run twice and does not delete any vehicles.</p>
        <RetryButton onClick={retry} />
      </Frame>
    )
  }
  return (
    <Frame icon={AlertOctagon} tone="bad" title="Something went wrong loading your data">
      <p>Supabase returned an error the dashboard did not expect:</p>
      <pre className="whitespace-pre-wrap break-words rounded-lg bg-zinc-100 p-3 text-sm text-zinc-700">{error.message}</pre>
      <SayThis>{`My dashboard shows this error, please fix it: ${error.message}`}</SayThis>
      <RetryButton onClick={retry} />
    </Frame>
  )
}

export function EmptyDatabase({ runs, refresh, refreshing }) {
  const last = runs[0]
  return (
    <Frame icon={Database} tone="good" title="Connected. Your database is empty so far.">
      <p>The dashboard reached your Supabase database and everything is set up correctly. There are just no vehicles in it yet. The scraper puts them there.</p>
      <SayThis>Run the scraper on all my dealers with a limit of 10 and tell me how many vehicles were found and saved.</SayThis>
      {last && (
        <div className="rounded-xl border border-zinc-200 p-4 text-base">
          <p className="font-semibold text-zinc-800">Last scraper run</p>
          <p>{last.dealer_name || last.dealer_key}: <b>{last.status}</b> on {fmtDateTime(last.started_at)}, {last.vehicles_found ?? 0} vehicles found.</p>
          {last.error_message && <p className="mt-1 text-sm text-red-700">{last.error_message}</p>}
        </div>
      )}
      <p className="text-base text-zinc-500">When the scraper finishes, click Refresh.</p>
      <button
        onClick={refresh}
        disabled={refreshing}
        className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-5 py-2.5 text-base font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
      >
        <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        Refresh
      </button>
    </Frame>
  )
}
