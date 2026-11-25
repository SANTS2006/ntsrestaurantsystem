import { LogOut, Menu as MenuIcon, UserCog } from 'lucide-react'
import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { setBrand } from './Loaders'
import { Dropdown } from './kit'
import { NotificationBell, RefreshButton, ThemeToggle } from './TopTools'

export type NavItem = { to: string; label: string; icon: ComponentType<{ size?: number; 'aria-hidden'?: boolean }>; end?: boolean; count?: number }
export type NavGroup = { label: string; items: NavItem[] }

/** The signed-in person's picture, or their initials. */
export function Avatar({ name, src, className = '' }: { name: string; src?: string | null; className?: string }) {
  const initials = (name || '?').split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()
  return <span className={`avatar ${className}`} aria-hidden>{src ? <img src={src} alt="" /> : initials}</span>
}

/** Premium application shell: dark brand sidebar with the profile at the bottom, sticky top bar (refresh, theme, notifications, profile menu),
 *  off-canvas navigation on tablets and phones. */
export default function Shell({ brand, tagline, logo, groups, user, onLogout, children, footerLink, profilePath }: {
  brand: string; tagline: string; logo?: string | null; groups: NavGroup[]; user: { name: string; role: string; avatar?: string | null }; onLogout: () => void; children?: ReactNode; footerLink?: { to: string; label: string }; profilePath: string
}) {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  useEffect(() => { setBrand({ logo, name: brand }); return () => setBrand(null) }, [logo, brand])
  const current = groups.flatMap((g) => g.items).find((i) => (i.end ? loc.pathname === i.to : loc.pathname.startsWith(i.to)))
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
          <Link className="me" to={profilePath} aria-label="Your profile and settings">
            <Avatar name={user.name} src={user.avatar} />
            <span><b>{user.name}</b><small>{user.role}</small></span>
          </Link>
        </footer>
      </aside>
      <div className="scrim" onClick={() => setOpen(false)} />
      <div className="content">
        <header className="topbar">
          <button className="icon-btn burger" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}><MenuIcon size={20} aria-hidden /></button>
          <div className="crumb"><small>{brand}</small><b>{current?.label ?? 'Workspace'}</b></div>
          <span className="spacer" />
          <div className="tools">
            <RefreshButton />
            <ThemeToggle />
            <NotificationBell />
            <Dropdown label="Account menu" trigger={<><Avatar name={user.name} src={user.avatar} /><span className="who"><b style={{ fontWeight: 600 }}>{user.name}</b><small>{user.role}</small></span></>}>
              <Link to={profilePath}><UserCog size={16} aria-hidden /> Profile and settings</Link>
              {footerLink && <Link to={footerLink.to}>{footerLink.label}</Link>}
              <hr />
              <button onClick={onLogout}><LogOut size={16} aria-hidden /> Sign out</button>
            </Dropdown>
          </div>
        </header>
        <main className="main">{children ?? <Outlet />}</main>
      </div>
    </div>
  )
}
