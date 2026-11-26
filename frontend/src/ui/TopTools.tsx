import { Bell, BellRing, CheckCheck, Moon, RefreshCw, Sun, Trash2, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { refreshAll, useNotifications, type AppNotification } from '../lib/live'
import { useTheme } from '../lib/theme'
import { useMaybeMe } from '../lib/auth'
import { ago, kindIcon, notificationsBase } from './notificationMeta'

/** Reloads everything on screen, without reloading the page. */
export function RefreshButton() {
  const [busy, setBusy] = useState(false)
  return (
    <button className={`icon-btn ${busy ? 'spin' : ''}`} aria-label="Refresh data" title="Refresh data" onClick={() => { setBusy(true); refreshAll(); setTimeout(() => setBusy(false), 900) }}>
      <RefreshCw size={18} aria-hidden />
    </button>
  )
}

export function ThemeToggle() {
  const { resolved, toggle } = useTheme()
  return (
    <button className="icon-btn" aria-label={resolved === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} title={resolved === 'dark' ? 'Light mode' : 'Dark mode'} onClick={toggle}>
      {resolved === 'dark' ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
    </button>
  )
}

/** The bell: unread count, the list of notifications, mark as read, mute sounds. */
export function NotificationBell() {
  const { items, unread, muted, setMuted, markRead, clearRead } = useNotifications()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const me = useMaybeMe()
  const base = notificationsBase(me?.role)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', off)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', off); document.removeEventListener('keydown', key) }
  }, [open])
  const go = (n: AppNotification) => {
    void markRead([n.id])
    setOpen(false)
    navigate(`${base}/${n.id}`)
  }
  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button className="icon-btn" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
        {unread ? <BellRing size={18} aria-hidden /> : <Bell size={18} aria-hidden />}
        {unread > 0 && <span className="badge-dot">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div className="notif-pop" role="dialog" aria-label="Notifications">
          <header>
            <b>Notifications</b>
            <span style={{ display: 'flex', gap: 4 }}>
              <button className="icon-btn" style={{ width: 32, height: 32 }} aria-label={muted ? 'Turn sounds on' : 'Turn sounds off'} title={muted ? 'Sounds off' : 'Sounds on'} onClick={() => setMuted(!muted)}>{muted ? <VolumeX size={16} aria-hidden /> : <Volume2 size={16} aria-hidden />}</button>
              <button className="icon-btn" style={{ width: 32, height: 32 }} aria-label="Mark all as read" title="Mark all as read" onClick={() => void markRead()}><CheckCheck size={16} aria-hidden /></button>
              <button className="icon-btn" style={{ width: 32, height: 32 }} aria-label="Clear read notifications" title="Clear read" onClick={() => void clearRead()}><Trash2 size={16} aria-hidden /></button>
            </span>
          </header>
          <div className="list">
            {items.length === 0 ? <div className="notif-empty">You are all caught up.</div> : items.map((n) => (
              <button key={n.id} className={`notif ${n.read ? '' : 'unread'} ${n.kind === 'order_ready' ? 'ready' : ''}`} onClick={() => go(n)}>
                <span className="ico">{kindIcon(n.kind)}</span>
                <span><b>{n.title}</b>{n.body && <p>{n.body}</p>}<span className="t">{ago(n.created_at)}</span></span>
              </button>
            ))}
          </div>
          <button className="notif-all" onClick={() => { setOpen(false); navigate(base) }}>View all notifications</button>
        </div>
      )}
    </div>
  )
}
