import { useEffect, useRef, useState } from 'react'
import { tokenStore } from './api'
import { API_ORIGIN, TENANT_BASE } from './config'

export type LiveStatus = 'connecting' | 'live' | 'polling'
export type StaffEvent = { type: string; [k: string]: unknown }

/**
 * Staff real-time channel. Authenticates with the access token as the FIRST message (never in the URL),
 * reconnects with backoff, and reports `polling` whenever the socket is not live so the caller keeps
 * its polling fallback running. A rejected login (close 4403/4404) is final: no reconnect storm.
 */
export function useStaffSocket(onEvent: (e: StaffEvent) => void): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>('connecting')
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    let stopped = false
    let ws: WebSocket | null = null
    let retry = 0
    let ping: ReturnType<typeof setInterval> | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    const url = API_ORIGIN.replace(/^http/, 'ws') + TENANT_BASE + '/ws/staff/'

    const connect = () => {
      const tokens = tokenStore.get()
      if (stopped || !tokens || typeof WebSocket === 'undefined') return setStatus('polling')
      setStatus('connecting')
      ws = new WebSocket(url)
      ws.onopen = () => ws?.send(JSON.stringify({ type: 'auth', token: tokens.access }))
      ws.onmessage = (m) => {
        try {
          const e = JSON.parse(m.data as string) as StaffEvent
          if (e.type === 'ready') { retry = 0; setStatus('live') }
          else if (e.type !== 'pong') handler.current(e)
        } catch { /* ignore malformed frames */ }
      }
      ws.onclose = (ev) => {
        clearInterval(ping)
        setStatus('polling')
        if (stopped || ev.code === 4403 || ev.code === 4404) return
        timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++))
      }
      ws.onerror = () => ws?.close()
      ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: 'ping' })), 25000)
    }
    connect()
    return () => { stopped = true; clearInterval(ping); clearTimeout(timer); ws?.close() }
  }, [])
  return status
}
