import { Eye, EyeOff, type LucideIcon } from 'lucide-react'
import { useState, type InputHTMLAttributes, type ReactNode } from 'react'
import { Field } from './kit'

/**
 * Shared sign-in / register layout: a brand panel on the left (hidden on phones) and the form on the right.
 * The colours come from the theme variables (--brand, --brand-2), so a restaurant's own colours apply automatically.
 */
export function AuthLayout({ brand, logo, tagline, points, title, subtitle, back, children, footer }: {
  brand: string
  logo?: string | null
  tagline: string
  points: { icon: LucideIcon; text: string }[]
  title: string
  subtitle?: string
  back?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="auth">
      <aside className="auth-side">
        <div className="auth-side-inner">
          <div className="auth-brand">{logo && <img src={logo} alt="" width={44} height={44} />}<span>{brand}</span></div>
          <h2>{tagline}</h2>
          <ul>{points.map(({ icon: Icon, text }) => <li key={text}><span><Icon size={18} aria-hidden /></span>{text}</li>)}</ul>
        </div>
      </aside>
      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-mobile-brand">{logo && <img src={logo} alt="" width={36} height={36} />}<span>{brand}</span></div>
          {back && <p className="auth-back">{back}</p>}
          <h1>{title}</h1>
          {subtitle && <p className="auth-sub">{subtitle}</p>}
          {children}
          {footer && <div className="auth-foot">{footer}</div>}
        </div>
      </main>
    </div>
  )
}

type FieldProps = { label: string; icon: LucideIcon; error?: string; hint?: string; secret?: boolean } & Omit<InputHTMLAttributes<HTMLInputElement>, 'className'>

/** Text input with a leading icon; `secret` adds a show/hide button for passwords. */
export function AuthField({ label, icon: Icon, error, hint, secret, ...input }: FieldProps) {
  const [show, setShow] = useState(false)
  return (
    <Field label={label} error={error} hint={hint}>
      {(p) => (
        <div className="auth-input">
          <Icon size={18} aria-hidden className="lead" />
          <input {...p} {...input} className="input" type={secret ? (show ? 'text' : 'password') : input.type} />
          {secret && (
            <button type="button" className="auth-eye" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}>
              {show ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}
            </button>
          )}
        </div>
      )}
    </Field>
  )
}
