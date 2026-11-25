import { useEffect, useRef, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { GOOGLE_CLIENT_ID } from '../lib/config'
import { Field } from './kit'
import { ThemeToggle } from './TopTools'

/**
 * Sign-in / register layout: a card on a blue backdrop. The left panel (WELCOME + the restaurant or platform name) carries the brand,
 * the right panel holds the form. Colours follow the theme variables, so a restaurant's own colours apply automatically.
 */
export function AuthLayout({ brand, logo, tagline, title, subtitle, back, children, footer }: {
  brand: string
  logo?: string | null
  tagline: string
  title: string
  subtitle?: string
  back?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="auth">
      <div className="auth-theme"><ThemeToggle /></div>
      <div className="auth-card-wrap">
        <aside className="auth-side">
          <span className="orb a" /><span className="orb b" /><span className="orb c" />
          <div className="auth-side-inner">
            {logo && <img className="auth-logo" src={logo} alt="" width={52} height={52} />}
            <p className="eyebrow">WELCOME</p>
            <h2>{brand}</h2>
            <p className="blurb">{tagline}</p>
          </div>
        </aside>
        <main className="auth-main">
          <div className="auth-form">
            <div className="auth-mobile-brand">{logo && <img src={logo} alt="" width={34} height={34} />}<span>{brand}</span></div>
            {back && <p className="auth-back">{back}</p>}
            <h1>{title}</h1>
            {subtitle && <p className="auth-sub">{subtitle}</p>}
            {children}
            {footer && <div className="auth-foot">{footer}</div>}
          </div>
        </main>
      </div>
    </div>
  )
}

type FieldProps = { label: string; icon: LucideIcon; error?: string; hint?: string; secret?: boolean } & Omit<InputHTMLAttributes<HTMLInputElement>, 'className'>

/** Text input with a leading icon; `secret` adds a SHOW / HIDE button for passwords. */
export function AuthField({ label, icon: Icon, error, hint, secret, ...input }: FieldProps) {
  const [show, setShow] = useState(false)
  return (
    <Field label={label} error={error} hint={hint}>
      {(p) => (
        <div className="auth-input">
          <Icon size={18} aria-hidden className="lead" />
          <input {...p} {...input} className="input" type={secret ? (show ? 'text' : 'password') : input.type} />
          {secret && (
            <button type="button" className="auth-show" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}>
              {show ? 'HIDE' : 'SHOW'}
            </button>
          )}
        </div>
      )}
    </Field>
  )
}

/** "Remember me" checkbox and the forgot-password link. Remembered sessions are kept on this device until the person signs out. */
export function RememberRow({ remember, onChange, forgotTo }: { remember: boolean; onChange: (v: boolean) => void; forgotTo?: string }) {
  return (
    <div className="auth-links">
      <label className="auth-check"><input type="checkbox" checked={remember} onChange={(e) => onChange(e.target.checked)} /> Remember me</label>
      {forgotTo && <Link to={forgotTo}>Forgot Password?</Link>}
    </div>
  )
}

export function OrDivider() {
  return <div className="auth-divider"><span>or</span></div>
}

export type GoogleResult = { access?: string; refresh?: string; mfa_token?: string }
type GoogleApi = { accounts: { id: { initialize: (o: unknown) => void; renderButton: (el: HTMLElement, o: unknown) => void } } }

/**
 * "Sign in with Google". The button looks like the rest of the form; Google's own (transparent) button sits on top so the click opens
 * Google's sign-in. Needs GOOGLE_OAUTH_CLIENT_ID on the server; until it is set the button explains that instead of failing silently.
 */
export function GoogleSignIn({ label = 'Sign in with Google', onResult, onError }: { label?: string; onResult: (r: GoogleResult) => void; onError: (m: string) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const done = useRef(onResult)
  const fail = useRef(onError)
  done.current = onResult
  fail.current = onError

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return
    const init = () => {
      const g = (window as unknown as { google?: GoogleApi }).google
      if (!g || !box.current) return
      g.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (resp: { credential: string }) => {
          try {
            // The notice "By continuing you agree to the Terms and Privacy Policy" is shown next to this button.
            done.current(await api<GoogleResult>('/auth/google/', { body: { id_token: resp.credential, accept_terms: true }, auth: false }))
          } catch (e) { fail.current(e instanceof ApiError ? e.message : 'Google sign-in failed.') }
        },
      })
      g.accounts.id.renderButton(box.current, { theme: 'outline', size: 'large', width: Math.min(400, box.current.clientWidth || 320), text: 'signin_with' })
    }
    if ((window as unknown as { google?: GoogleApi }).google) return init()
    let s = document.getElementById('gsi') as HTMLScriptElement | null
    if (!s) {
      s = document.createElement('script')
      s.id = 'gsi'; s.src = 'https://accounts.google.com/gsi/client'; s.async = true
      document.head.appendChild(s)
    }
    s.addEventListener('load', init)
    return () => s?.removeEventListener('load', init)
  }, [])

  return (
    <div className="google-wrap">
      <button type="button" className="google-btn" onClick={() => !GOOGLE_CLIENT_ID && onError('Google sign-in has not been set up yet. Ask the administrator to add the Google client ID.')}>
        <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" /><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.5-4.2 7-10.3 7-17.6z" /><path fill="#FBBC05" d="M10.5 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.9-6.1z" /><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" /></svg>
        {label}
      </button>
      {GOOGLE_CLIENT_ID && <div className="google-overlay" ref={box} aria-label={label} />}
    </div>
  )
}
