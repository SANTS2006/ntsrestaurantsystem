import { API_ORIGIN, API_URL } from './config'

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
  /** Flatten DRF field errors ({field: ["msg"]}) into a field -> message map for forms. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    if (this.details && typeof this.details === 'object') {
      for (const [k, v] of Object.entries(this.details as Record<string, unknown>)) {
        out[k] = Array.isArray(v) ? String(v[0]) : String(v)
      }
    }
    return out
  }
}

// Tokens live in sessionStorage (cleared when the tab closes). The backend, not the token, decides roles.
const KEY = 'nts.tokens'
type Tokens = { access: string; refresh: string }

export const tokenStore = {
  get(): Tokens | null {
    try {
      return JSON.parse(sessionStorage.getItem(KEY) ?? 'null')
    } catch {
      return null
    }
  },
  set(t: Tokens | null) {
    try {
      if (t) sessionStorage.setItem(KEY, JSON.stringify(t))
      else sessionStorage.removeItem(KEY)
    } catch {
      /* storage unavailable: session will not persist */
    }
  },
}

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const t = tokenStore.get()
  if (!t) return false
  refreshing ??= fetch(`${API_URL}/api/v1/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: t.refresh }),
  })
    .then(async (r) => {
      if (!r.ok) return false
      const body = await r.json()
      tokenStore.set({ access: body.data.access, refresh: body.data.refresh ?? t.refresh })
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

type Opts = { method?: string; body?: unknown; params?: Record<string, string | number | undefined>; auth?: boolean; headers?: Record<string, string> }

export async function api<T = unknown>(path: string, opts: Opts = {}, retry = true): Promise<T> {
  const url = new URL(`${API_ORIGIN}/api/v1${path}`)
  for (const [k, v] of Object.entries(opts.params ?? {})) if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
  const headers: Record<string, string> = { ...(opts.headers ?? {}) }
  const isForm = opts.body instanceof FormData
  if (opts.body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  const tokens = tokenStore.get()
  if (opts.auth !== false && tokens) headers.Authorization = `Bearer ${tokens.access}`

  let res: Response
  try {
    res = await fetch(url, {
      method: opts.method ?? (opts.body !== undefined ? 'POST' : 'GET'),
      headers,
      body: opts.body === undefined ? undefined : isForm ? (opts.body as FormData) : JSON.stringify(opts.body),
    })
  } catch {
    throw new ApiError(0, 'network', 'Cannot reach the server. Check your connection and try again.')
  }
  if (res.status === 401 && retry && tokens && opts.auth !== false && (await refreshTokens())) {
    return api<T>(path, opts, false)
  }
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok || !body?.success) {
    if (res.status === 401 && tokens) tokenStore.set(null)
    const e = body?.error
    throw new ApiError(res.status, e?.code ?? 'error', e?.message ?? 'Something went wrong.', e?.details ?? null)
  }
  return body.data as T
}

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] }

/** Download a protected file (e.g. a PDF receipt) using the bearer token. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const t = tokenStore.get()
  const res = await fetch(`${API_URL}/api/v1${path}`, { headers: t ? { Authorization: `Bearer ${t.access}` } : {} })
  if (!res.ok) throw new ApiError(res.status, 'download', 'Download failed.')
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
