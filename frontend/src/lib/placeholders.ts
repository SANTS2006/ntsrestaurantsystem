// Every text box in the app shows what to type: "Enter your <what it is>". The text comes from the field's label (or its aria-label),
// so new fields get it automatically. An example already written on the field is kept after it ("Enter your amount, e.g. 120.50").
// Search boxes keep their own "Search ..." wording; dates, checkboxes, files and hidden spam-trap fields are left alone.
const SKIP_TYPES = new Set(['checkbox', 'radio', 'file', 'hidden', 'date', 'time', 'datetime-local', 'month', 'week', 'color', 'range', 'submit', 'button', 'image', 'reset', 'search'])

function labelOf(el: HTMLInputElement | HTMLTextAreaElement): string {
  const aria = el.getAttribute('aria-label')
  if (aria) return aria
  if (el.id) {
    const l = document.querySelector<HTMLLabelElement>(`label[for="${CSS.escape(el.id)}"]`)
    if (l?.textContent) return l.textContent
  }
  const wrap = el.closest('label')
  if (wrap) {
    const clone = wrap.cloneNode(true) as HTMLElement
    clone.querySelectorAll('input, textarea, select, button').forEach((n) => n.remove())
    if (clone.textContent?.trim()) return clone.textContent
  }
  return el.getAttribute('name') ?? ''
}

function lowerFirst(word: string): string {
  return /[A-Z].*[A-Z]|^[A-Z]{2,}/.test(word) ? word : word.charAt(0).toLowerCase() + word.slice(1) // keep acronyms such as SKU, PIN, QR
}

export function describe(label: string): string {
  const clean = label.replace(/\([^)]*\)/g, ' ').replace(/[*:]/g, ' ').replace(/\s+/g, ' ').trim()
  return clean.split(' ').map((w, i) => (i === 0 ? lowerFirst(w) : w === w.toUpperCase() ? w : w.toLowerCase())).join(' ')
}

/** "Enter your <what>" plus any example that was already there. Returns null when the box already says the right thing. */
export function placeholderFor(label: string, current: string): string | null {
  if (/^(enter your|re-enter your) /i.test(current)) return null
  const reworded = current.replace(/^enter (the|a|an) /i, 'Enter your ')
  if (reworded !== current) return reworded
  if (/^enter /i.test(current)) return current.replace(/^enter /i, 'Enter your ')
  if (label.trim().endsWith('?')) return 'Enter your answer'
  const confirming = /^confirm (?!with )/i.test(label.trim())
  const what = describe(label.replace(/^\s*confirm with /i, '').replace(/^\s*confirm /i, '')).replace(/^your /i, '')
  if (!what) return null
  const base = `${confirming ? 'Re-enter' : 'Enter'} your ${what}`
  const c = current.trim()
  if (!c) return base
  if (/^e\.g\./i.test(c)) return `${base}, ${c}`
  if (/^[+\-\d.,\s:x]+$/i.test(c) && /\d/.test(c)) return `${base}, e.g. ${c}`
  if (/^[+\-\d.,\s]+$/.test(c)) return `${base}, e.g. ${c}`
  const eg = c.match(/^(.*?),\s*(e\.g\..*)$/i)
  if (eg) return `${base}, ${eg[2]}`
  return base
}

function apply(el: HTMLInputElement | HTMLTextAreaElement) {
  if (el instanceof HTMLInputElement && SKIP_TYPES.has((el.type || 'text').toLowerCase())) return
  if (el.tabIndex === -1 || el.closest('[aria-hidden="true"], [hidden], [data-keep-placeholder]')) return
  const next = placeholderFor(labelOf(el), el.getAttribute('placeholder') ?? '')
  if (next && next !== el.getAttribute('placeholder')) el.setAttribute('placeholder', next)
}

function scan(root: ParentNode) {
  root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input, textarea').forEach(apply)
}

let installed = false
export function installPlaceholders() {
  if (installed || typeof document === 'undefined' || typeof MutationObserver === 'undefined') return
  installed = true
  let queued = false
  const run = () => { queued = false; scan(document) }
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(run) } }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['placeholder', 'aria-label', 'type'] })
  run()
}
