import { Mail, Phone } from 'lucide-react'
import { LocationCard } from '../ui/Maps'
import { fullAddress } from '../ui/geo'
import { useSite, type Site } from './SiteContext'

export type Spot = { key: string; name: string; address: string; latitude: string | null; longitude: string | null; phone: string; email: string; hours: Record<string, string> }

/** Every place a visitor can go to: the branches, plus the restaurant's main address when it is somewhere else. */
export function spotsOf(site: Site): Spot[] {
  const r = site.restaurant
  const spots: Spot[] = site.branches.map((b) => ({
    key: `b${b.id}`, name: b.name, address: b.address || b.location ? fullAddress(b.address, b.location, r.city, r.country) : '',
    latitude: b.latitude, longitude: b.longitude, phone: b.phone, email: b.email, hours: b.operating_hours ?? {},
  }))
  const norm = (x: string) => x.trim().toLowerCase()
  const listed = r.address && site.branches.some((b) => norm(b.address) === norm(r.address))
  if (!listed && (r.address || r.latitude || !spots.length)) {
    const address = r.address || r.city ? fullAddress(r.address, r.city, r.country) : ''
    if (address || r.latitude) spots.unshift({ key: 'main', name: spots.length ? 'Main address' : r.name, address, latitude: r.latitude, longitude: r.longitude, phone: r.contact_phone, email: r.contact_email, hours: {} })
  }
  return spots
}

export function Locations() {
  const { site } = useSite()
  const spots = spotsOf(site)
  if (!spots.length) return <p className="center muted">Our address will be published here soon.</p>
  return (
    <div className="locations">
      {spots.map((s) => (
        <LocationCard key={s.key} name={s.name} place={s}>
          {s.phone && <p><Phone size={15} aria-hidden /> <a href={`tel:${s.phone}`}>{s.phone}</a></p>}
          {s.email && <p><Mail size={15} aria-hidden /> <a href={`mailto:${s.email}`}>{s.email}</a></p>}
          {Object.keys(s.hours).length > 0 && <ul className="hours">{Object.entries(s.hours).map(([d, t]) => <li key={d}><b>{d}</b><span>{t}</span></li>)}</ul>}
        </LocationCard>
      ))}
    </div>
  )
}
