import { AlertTriangle, HelpCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

/**
 * In-app replacements for the browser's confirm() and prompt() boxes.
 *
 *   const confirm = useConfirm();  if (!(await confirm({ title: 'Archive Rice?', message: '...', danger: true, confirmLabel: 'Archive' }))) return
 *   const prompt = usePrompt();    const reason = await prompt({ title: 'Cancel order', label: 'Reason', required: true })  // null when dismissed
 */
export type ConfirmOptions = { title: string; message?: ReactNode; confirmLabel?: string; cancelLabel?: string; danger?: boolean }
export type PromptOptions = {
  title: string; message?: ReactNode; label: string; placeholder?: string; defaultValue?: string; confirmLabel?: string
  required?: boolean; multiline?: boolean; danger?: boolean; inputMode?: 'text' | 'decimal' | 'numeric'
}
type Pending =
  | { kind: 'confirm'; opts: ConfirmOptions; resolve: (v: boolean) => void }
  | { kind: 'prompt'; opts: PromptOptions; resolve: (v: string | null) => void }

type DialogApi = { confirm: (o: ConfirmOptions) => Promise<boolean>; prompt: (o: PromptOptions) => Promise<string | null> }
// Without a provider (isolated component tests) nothing is confirmed: the safe answer.
const Ctx = createContext<DialogApi>({ confirm: async () => false, prompt: async () => null })

export function DialogProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<Pending[]>([])
  const confirm = useCallback((opts: ConfirmOptions) => new Promise<boolean>((resolve) => setQueue((q) => [...q, { kind: 'confirm', opts, resolve }])), [])
  const prompt = useCallback((opts: PromptOptions) => new Promise<string | null>((resolve) => setQueue((q) => [...q, { kind: 'prompt', opts, resolve }])), [])
  const current = queue[0]
  const done = () => setQueue((q) => q.slice(1))
  return (
    <Ctx.Provider value={{ confirm, prompt }}>
      {children}
      {current?.kind === 'confirm' && <ConfirmDialog key={queue.length} {...current.opts} onResult={(v) => { current.resolve(v); done() }} />}
      {current?.kind === 'prompt' && <PromptDialog key={queue.length} {...current.opts} onResult={(v) => { current.resolve(v); done() }} />}
    </Ctx.Provider>
  )
}

const use = () => useContext(Ctx)
export const useConfirm = () => use().confirm
export const usePrompt = () => use().prompt

function Frame({ title, danger, children, onCancel }: { title: string; danger?: boolean; children: ReactNode; onCancel: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])
  useEffect(() => { ref.current?.querySelector<HTMLElement>('input, textarea, button.primary')?.focus() }, [])
  return (
    <div className="modal-back dialog-back" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal dialog" role="alertdialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className={`dialog-icon ${danger ? 'danger' : ''}`} aria-hidden>{danger ? <AlertTriangle size={26} /> : <HelpCircle size={26} />}</div>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  )
}

function ConfirmDialog({ title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger, onResult }: ConfirmOptions & { onResult: (v: boolean) => void }) {
  return (
    <Frame title={title} danger={danger} onCancel={() => onResult(false)}>
      {message && <div className="dialog-msg">{message}</div>}
      <div className="dialog-actions">
        <button className="btn secondary" onClick={() => onResult(false)}>{cancelLabel}</button>
        <button className={`btn primary ${danger ? 'danger' : ''}`} onClick={() => onResult(true)}>{confirmLabel}</button>
      </div>
    </Frame>
  )
}

function PromptDialog({ title, message, label, placeholder, defaultValue = '', confirmLabel = 'Continue', required, multiline, danger, inputMode, onResult }: PromptOptions & { onResult: (v: string | null) => void }) {
  const [value, setValue] = useState(defaultValue)
  const [error, setError] = useState('')
  const submit = () => {
    const v = value.trim()
    if (required && !v) return setError('This is required.')
    onResult(v)
  }
  return (
    <Frame title={title} danger={danger} onCancel={() => onResult(null)}>
      {message && <div className="dialog-msg">{message}</div>}
      <div className="field">
        <label htmlFor="dialog-input">{label}</label>
        {multiline
          ? <textarea id="dialog-input" className="input" rows={3} placeholder={placeholder} value={value} onChange={(e) => { setValue(e.target.value); setError('') }} />
          : <input id="dialog-input" className="input" inputMode={inputMode} placeholder={placeholder} value={value} onChange={(e) => { setValue(e.target.value); setError('') }} onKeyDown={(e) => e.key === 'Enter' && submit()} />}
        {error && <span className="err">{error}</span>}
      </div>
      <div className="dialog-actions">
        <button className="btn secondary" onClick={() => onResult(null)}>Cancel</button>
        <button className={`btn primary ${danger ? 'danger' : ''}`} onClick={submit}>{confirmLabel}</button>
      </div>
    </Frame>
  )
}
