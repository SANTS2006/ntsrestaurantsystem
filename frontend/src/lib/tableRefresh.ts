import { lastRefreshedAt, onRefresh, refreshAll } from './refresh'

// Adds a "Refresh" button and a live indicator above every data table (a .tbl with a header row), on every screen, including ones
// added later. Pressing it reloads all the data on screen without reloading the page. The same refresh also runs on its own
// (timer, focus, push from the server), so the button is for people who want to be sure.
const ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>'

function ago(): string {
  const s = Math.round((Date.now() - lastRefreshedAt()) / 1000)
  if (s < 8) return 'Updated just now'
  if (s < 60) return `Updated ${s}s ago`
  return `Updated ${Math.round(s / 60)} min ago`
}

function build(): HTMLElement {
  const bar = document.createElement('div')
  bar.className = 'tbl-tools'
  bar.dataset.tableTools = '1'
  const live = document.createElement('span')
  live.className = 'live'
  live.textContent = ago()
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.setAttribute('aria-label', 'Refresh this table')
  btn.innerHTML = `${ICON}<span>Refresh</span>`
  btn.addEventListener('click', () => {
    btn.classList.add('busy')
    refreshAll()
    live.textContent = ago()
    setTimeout(() => btn.classList.remove('busy'), 900)
  })
  bar.append(live, btn)
  return bar
}

function scan(root: ParentNode) {
  root.querySelectorAll<HTMLTableElement>('table.tbl').forEach((t) => {
    if (!t.tHead || t.closest('.modal, .drawer, [data-no-refresh]') || t.previousElementSibling?.matches('[data-table-tools]')) return
    t.parentElement?.insertBefore(build(), t)
  })
  root.querySelectorAll<HTMLElement>('[data-table-tools]').forEach((bar) => {
    if (!bar.nextElementSibling?.matches('table.tbl')) bar.remove()
  })
}

let installed = false
export function installTableRefresh() {
  if (installed || typeof document === 'undefined' || typeof MutationObserver === 'undefined') return
  installed = true
  let queued = false
  const run = () => { queued = false; scan(document) }
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(run) } }).observe(document.body, { childList: true, subtree: true })
  const stamp = () => document.querySelectorAll('[data-table-tools] .live').forEach((el) => { el.textContent = ago() })
  onRefresh(stamp)
  setInterval(stamp, 15000)
  run()
}
