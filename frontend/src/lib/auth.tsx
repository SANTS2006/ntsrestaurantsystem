import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, tokenStore } from './api'
import { LogoutOverlay } from '../ui/Loaders'

export type Me = { id: number; email: string; full_name: string; phone?: string; avatar?: string | null; role: string | null; branch_ids: number[]; must_change_password: boolean; mfa?: { enabled: boolean; required: boolean; enforced: boolean; challenge?: boolean; switched_on?: boolean } }
export type MfaChallenge = { mfa_token: string }
type Ctx = {
  me: Me | null
  loading: boolean
  login: (email: string, password: string, remember?: boolean) => Promise<Me | MfaChallenge>
  completeMfa: (mfaToken: string, code: string, recovery?: boolean, remember?: boolean) => Promise<Me>
  adoptTokens: (t: { access: string; refresh: string }, remember?: boolean) => Promise<Me>
  logout: () => void
  /** Sign out with the branded animation; resolves when the session has been ended. */
  signOut: () => Promise<void>
  reload: () => Promise<void>
}
const AuthContext = createContext<Ctx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    if (!tokenStore.get()) {
      setMe(null)
      setLoading(false)
      return
    }
    try {
      setMe(await api<Me>('/auth/me/'))
    } catch {
      setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const login = useCallback(async (email: string, password: string, remember = false) => {
    const t = await api<{ access: string; refresh: string } | { mfa_required: true; mfa_token: string }>('/auth/login/', { body: { email, password }, auth: false })
    if ('mfa_required' in t) return { mfa_token: t.mfa_token } // a second factor is needed before any session exists
    tokenStore.set(t, remember)
    const profile = await api<Me>('/auth/me/')
    setMe(profile)
    return profile
  }, [])

  const adoptTokens = useCallback(async (t: { access: string; refresh: string }, remember?: boolean) => {
    tokenStore.set(t, remember)
    const profile = await api<Me>('/auth/me/')
    setMe(profile)
    return profile
  }, [])

  const completeMfa = useCallback(async (mfaToken: string, code: string, recovery = false, remember = false) => {
    const t = await api<{ access: string; refresh: string }>('/auth/mfa/verify/', { body: recovery ? { mfa_token: mfaToken, recovery_code: code } : { mfa_token: mfaToken, code }, auth: false })
    return adoptTokens(t, remember)
  }, [adoptTokens])

  const logout = useCallback(() => {
    tokenStore.set(null)
    setMe(null)
  }, [])

  const [leaving, setLeaving] = useState(false)
  const signOut = useCallback(async () => {
    setLeaving(true)
    await new Promise((r) => setTimeout(r, 1600)) // let the person see that something is happening, then end the session
    tokenStore.set(null)
    setMe(null)
    setLeaving(false)
  }, [])

  const value = useMemo(() => ({ me, loading, login, completeMfa, adoptTokens, logout, signOut, reload }), [me, loading, login, completeMfa, adoptTokens, logout, signOut, reload])
  return <AuthContext.Provider value={value}>{children}{leaving && <LogoutOverlay />}</AuthContext.Provider>
}

/** The signed-in person, or null: for shared widgets that also render where there is no sign-in context. */
export const useMaybeMe = (): Me | null => useContext(AuthContext)?.me ?? null

export function useAuth(): Ctx {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
