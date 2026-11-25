import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from './api'
import { refreshAll } from './refresh'
import { useAuth } from './auth'
import { TENANT_BASE } from './config'
import { useStaffSocket } from './realtime'
import { playChime } from './sound'
import { useToast } from '../ui/kit'

export { refreshAll } from './refresh'

/* --------------------------------------------------------------------------------------- notifications */
export type AppNotification = { id: number; kind: string; title: string; body: string; link: string; created_at: string; read: boolean }
type Feed = { unread: number; items: AppNotification[] }
type Ctx = {
  items: AppNotification[]; unread: number; muted: boolean; setMuted: (m: boolean) => void
  markRead: (ids?: number[]) => Promise<void>; clearRead: () => Promise<void>; pull: () => Promise<void>
}
const NotifyCtx = createContext<Ctx>({ items: [], unread: 0, muted: false, setMuted: () => {}, markRead: async () => {}, clearRead: async () => {}, pull: async () => {} })
export const useNotifications = () => useContext(NotifyCtx)

const SOUND_KEY = 'nts.sound.muted'
const STAFF_SOCKET_ROLES = ['restaurant_admin', 'manager', 'cashier', 'platform_admin']
const POLL_MS = 10000

function LiveSocket({ onEvent }: { onEvent: () => void }) {
  useStaffSocket(onEvent)
  return null
}

/** Feeds the bell: fetches the user's notifications (every few seconds, and immediately when the live channel pushes),
 *  shows a toast and plays a sound for new ones, and refreshes the data on screen when something happened. */
export function NotificationProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const toast = useToast()
  const [feed, setFeed] = useState<Feed>({ unread: 0, items: [] })
  const [muted, setMutedState] = useState(() => { try { return localStorage.getItem(SOUND_KEY) === '1' } catch { return false } })
  const lastId = useRef<number | null>(null)
  const mutedRef = useRef(muted)
  mutedRef.current = muted
  const uid = me?.id

  const pull = useCallback(async () => {
    if (!uid) return
    try {
      const data = await api<Feed>('/notifications/')
      const newest = data.items[0]?.id ?? 0
      if (lastId.current === null) { lastId.current = newest; setFeed(data); return } // first load: show, do not alert
      const fresh = data.items.filter((n) => n.id > (lastId.current ?? 0) && !n.read)
      if (fresh.length) {
        lastId.current = newest
        fresh.slice(0, 3).forEach((n) => toast(n.title))
        if (!mutedRef.current) playChime(fresh.some((n) => n.kind === 'order_ready') ? 'ready' : fresh.some((n) => n.kind === 'order_new') ? 'new' : 'soft')
        refreshAll() // something changed: reload the tables and cards on screen
      }
      setFeed(data)
    } catch { /* offline or signed out: try again on the next tick */ }
  }, [uid, toast])

  useEffect(() => {
    lastId.current = null
    setFeed({ unread: 0, items: [] })
    if (!uid) return
    void pull()
    const t = setInterval(() => { if (document.visibilityState === 'visible') void pull() }, POLL_MS)
    const vis = () => document.visibilityState === 'visible' && void pull()
    document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', vis) }
  }, [uid, pull])

  const setMuted = useCallback((m: boolean) => {
    setMutedState(m)
    try { localStorage.setItem(SOUND_KEY, m ? '1' : '0') } catch { /* not remembered */ }
  }, [])
  const markRead = useCallback(async (ids?: number[]) => {
    setFeed((f) => ({ unread: ids ? Math.max(0, f.unread - f.items.filter((n) => ids.includes(n.id) && !n.read).length) : 0, items: f.items.map((n) => (!ids || ids.includes(n.id) ? { ...n, read: true } : n)) }))
    try { await api('/notifications/read/', { body: ids ? { ids } : {} }) } catch { /* the next poll corrects it */ }
  }, [])
  const clearRead = useCallback(async () => {
    setFeed((f) => ({ ...f, items: f.items.filter((n) => !n.read) }))
    try { await api('/notifications/clear/', { body: {} }) } catch { /* the next poll corrects it */ }
  }, [])

  const value = useMemo(() => ({ items: feed.items, unread: feed.unread, muted, setMuted, markRead, clearRead, pull }), [feed, muted, setMuted, markRead, clearRead, pull])
  const socket = uid && TENANT_BASE !== '' && STAFF_SOCKET_ROLES.includes(me?.role ?? '')
  return (
    <NotifyCtx.Provider value={value}>
      {socket && <LiveSocket onEvent={() => { void pull(); refreshAll() }} />}
      {children}
    </NotifyCtx.Provider>
  )
}
