import { LogOut, Menu as MenuIcon } from 'lucide-react'
import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Dropdown } from './kit'

export type NavItem = { to: string; label: string; icon: ComponentType<{ size?: number; 'aria-hidden'?: boolean }>; end?: boolean; count?: number }
export type NavGroup = { label: string; items: NavItem[] }

/** Premium application shell: dark brand sidebar, sticky top bar, user menu, off-canvas navigation on tablets and phones. */
export default function Shell({ brand, tagline, logo, groups, user, onLogout, children, footerLink }: {
  brand: string; tagline: string; logo?: string | null; groups: NavGroup[]; user: { name: string; role: string }; onLogout: () => void; children?: ReactNode; footerLink?: { to: string; label: string }
}) {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  const current = groups.flatMap((g) => g.items).find((i) => (i.end ? loc.pathname === i.to : loc.pathname.startsWith(i.to)))
  const initials = (user.name || '?').split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div className={`admin shell ${open ? 'open' : ''}`}>
      <aside className="side" aria-label={`${brand} navigation`}>
        <div className="brand">
          <span className="mark">{logo ? <img src={logo} alt="" /> : brand.charAt(0)}</span>
          <span><b>{brand}</b><small>{tagline}</small></span>
        </div>
        <nav>
          {groups.filter((g) => g.items.length).map((g) => (
            <div className="group" key={g.label}>
              <span>{g.label}</span>
              {g.items.map(({ to, label, icon: Icon, end, count }) => <NavLink key={to} to={to} end={end}><Icon size={18} aria-hidden /> {label}{count ? <span className="count">{count}</span> : null}</NavLink>)}
            </div>
          ))}
        </nav>
        <footer>
          {footerLink && <Link className="btn sm" to={footerLink.to}>{footerLink.label}</Link>}
        </footer>
      </aside>
      <div className="scrim" onClick={() => setOpen(false)} />
      <div className="content">
        <header className="topbar">
          <button className="icon-btn burger" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}><MenuIcon size={20} aria-hidden /></button>
          <div className="crumb"><small>{brand}</small><b>{current?.label ?? 'Workspace'}</b></div>
          <span className="spacer" />
          <Dropdown label="Account menu" trigger={<><span className="avatar" aria-hidden>{initials}</span><span><b style={{ fontWeight: 600 }}>{user.name}</b><small>{user.role}</small></span></>}>
            {footerLink && <Link to={footerLink.to}>{footerLink.label}</Link>}
            <hr />
            <button onClick={onLogout}><LogOut size={16} aria-hidden /> Sign out</button>
          </Dropdown>
        </header>
        <main className="main">{children ?? <Outlet />}</main>
      </div>
    </div>
  )
}
