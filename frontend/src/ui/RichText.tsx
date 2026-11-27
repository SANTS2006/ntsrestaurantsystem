import { Bold } from 'lucide-react'
import { Fragment, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Field } from './kit'
import { boldSelection, plain, splitBold } from './boldText'

/** Website text with the words the owner marked (`**like this**`) shown in bold. Everything else stays ordinary text: no HTML is read. */
export function RichText({ text }: { text: string | null | undefined }): ReactNode {
  return <>{splitBold(text ?? '').map((part, i) => (part.bold ? <strong key={i}>{part.text}</strong> : <Fragment key={i}>{part.text}</Fragment>))}</>
}

/** Several paragraphs of website text: a blank line starts a new paragraph, single line breaks are kept. */
export function Paragraphs({ text, className = '' }: { text: string | null | undefined; className?: string }) {
  const blocks = (text ?? '').split(/\n\s*\n/).filter((b) => b.trim())
  return <>{blocks.map((b, i) => <p key={i} className={`pre ${className}`}><RichText text={b} /></p>)}</>
}

/** A text box with a Bold button (or Ctrl+B): select the words, press it, and they are shown in bold on the website. */
export function RichField({ label, value, onChange, error, hint, rows, placeholder, maxLength }: {
  label: string; value: string; onChange: (v: string) => void; error?: string; hint?: string; rows?: number; placeholder?: string; maxLength?: number
}) {
  const box = useRef<HTMLInputElement & HTMLTextAreaElement>(null)

  function bold() {
    const el = box.current
    if (!el) return
    const next = boldSelection(value, el.selectionStart ?? value.length, el.selectionEnd ?? value.length)
    onChange(next.value)
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(next.start, next.end) })
  }
  function keys(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); bold() }
  }

  return (
    <Field label={label} error={error} hint={hint}>
      {(p) => (
        <div className="rich-field">
          <div className="rich-bar">
            <button type="button" className="rich-btn" onClick={bold} aria-label={`Make the selected words of ${label} bold`} title="Bold (Ctrl+B)"><Bold size={15} aria-hidden /> Bold</button>
          </div>
          {rows
            ? <textarea {...p} ref={box} className="input" rows={rows} placeholder={placeholder ?? `Enter ${label.toLowerCase()}`} maxLength={maxLength} value={value} onChange={(e) => onChange(e.target.value)} onKeyDown={keys} />
            : <input {...p} ref={box} className="input" placeholder={placeholder ?? `Enter ${label.toLowerCase()}`} maxLength={maxLength} value={value} onChange={(e) => onChange(e.target.value)} onKeyDown={keys} />}
          {value !== plain(value) && <div className="rich-preview"><small>On the website</small><span className="pre"><RichText text={value} /></span></div>}
        </div>
      )}
    </Field>
  )
}
