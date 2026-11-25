import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'
type Ctx = { choice: ThemeChoice; resolved: 'light' | 'dark'; setChoice: (c: ThemeChoice) => void; toggle: () => void }
const KEY = 'nts.theme'
const ThemeContext = createContext<Ctx>({ choice: 'system', resolved: 'light', setChoice: () => {}, toggle: () => {} })

const systemDark = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches

function stored(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

// Applied when the file loads, before React renders anything, so the page never flashes the wrong theme.
if (typeof document !== 'undefined') {
  const c = stored()
  const r = c === 'system' ? (systemDark() ? 'dark' : 'light') : c
  document.documentElement.dataset.theme = r
  document.documentElement.style.colorScheme = r
}

/** Light / dark mode for the whole app. "system" follows the device; an explicit choice is remembered on this device. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(stored)
  const [dark, setDark] = useState(systemDark)

  useEffect(() => {
    if (typeof matchMedia === 'undefined') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const on = () => setDark(mq.matches)
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])

  const resolved: 'light' | 'dark' = choice === 'system' ? (dark ? 'dark' : 'light') : choice
  useEffect(() => {
    document.documentElement.dataset.theme = resolved
    document.documentElement.style.colorScheme = resolved
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'dark' ? '#08111f' : '#0a72e0')
  }, [resolved])

  const setChoice = useCallback((c: ThemeChoice) => {
    setChoiceState(c)
    try {
      if (c === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, c)
    } catch { /* not remembered */ }
  }, [])
  const toggle = useCallback(() => setChoice(resolved === 'dark' ? 'light' : 'dark'), [resolved, setChoice])
  const value = useMemo(() => ({ choice, resolved, setChoice, toggle }), [choice, resolved, setChoice, toggle])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export const useTheme = () => useContext(ThemeContext)
