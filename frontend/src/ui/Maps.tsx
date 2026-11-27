import { Crosshair, ExternalLink, MapPin, Navigation } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Field, Spinner } from './kit'
import { directionsUrl, embedUrl, mapQuery, parseCoordinates, viewUrl, type Place } from './geo'

export function MapFrame({ query, title }: { query: string; title: string }) {
  return <iframe className="map-frame" title={`Map showing ${title}`} src={embedUrl(query)} loading="lazy" referrerPolicy="no-referrer-when-downgrade" allowFullScreen />
}

/** One place: its address in words, the same place on a map, and buttons that take the visitor there. */
export function LocationCard({ name, place, children }: { name: string; place: Place; children?: React.ReactNode }) {
  const query = mapQuery(place)
  return (
    <article className="location">
      <div className="location-info">
        <h3><MapPin size={18} aria-hidden /> {name}</h3>
        <address>{place.address?.trim() || (query ? 'See the map for this location.' : 'Address not listed yet.')}</address>
        {children}
        {query && (
          <div className="location-actions">
            <a className="btn sm" href={directionsUrl(query)} target="_blank" rel="noopener noreferrer"><Navigation size={15} aria-hidden /> Get directions</a>
            <a className="btn sm secondary" href={viewUrl(query)} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} aria-hidden /> Open map</a>
          </div>
        )}
      </div>
      {query && <MapFrame query={query} title={name} />}
    </article>
  )
}

export type Pin = { latitude: string; longitude: string }

/**
 * For staff forms: shows where the written address lands on the map, and lets them fix the exact spot by pasting coordinates
 * or a Google Maps link, or by using the location of the device they are holding.
 */
export function LocationPicker({ address, value, onChange, error }: { address: string; value: Pin; onChange: (v: Pin) => void; error?: string }) {
  const pinned = value.latitude !== '' && value.longitude !== ''
  const [text, setText] = useState(pinned ? `${value.latitude}, ${value.longitude}` : '')
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [shown, setShown] = useState(address)
  useEffect(() => { const t = setTimeout(() => setShown(address), 900); return () => clearTimeout(t) }, [address]) // do not reload the map at every letter

  function typed(next: string) {
    setText(next)
    if (!next.trim()) { setProblem(''); onChange({ latitude: '', longitude: '' }); return }
    const found = parseCoordinates(next)
    setProblem(found ? '' : 'Paste "latitude, longitude" or a Google Maps link that contains them.')
    onChange(found ?? { latitude: '', longitude: '' })
  }
  function here() {
    if (!navigator.geolocation) return setProblem('This device cannot share its location.')
    setBusy(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const pin = { latitude: pos.coords.latitude.toFixed(6), longitude: pos.coords.longitude.toFixed(6) }
        setBusy(false); setProblem(''); setText(`${pin.latitude}, ${pin.longitude}`); onChange(pin)
      },
      () => { setBusy(false); setProblem('Could not read the location. Allow location access, or paste the coordinates.') },
      { enableHighAccuracy: true, timeout: 15000 },
    )
  }

  const query = mapQuery({ address: shown, latitude: value.latitude, longitude: value.longitude })
  return (
    <div className="location-picker">
      <Field label="Exact map pin (optional)" error={problem || error} hint="Leave empty to use the written address. For an exact spot, paste coordinates or a Google Maps link.">
        {(p) => <input {...p} className="input" placeholder="e.g. 8.484400, -13.234400" value={text} onChange={(e) => typed(e.target.value)} />}
      </Field>
      <div className="location-actions">
        <button type="button" className="btn sm secondary" onClick={here} disabled={busy}>{busy ? <Spinner /> : <><Crosshair size={15} aria-hidden /> I am here now: use my location</>}</button>
        {(pinned || text) && <button type="button" className="btn sm ghost" onClick={() => typed('')}>Remove pin</button>}
      </div>
      {query ? <><p className="hint">{pinned ? 'Visitors will see this exact pin.' : 'Visitors will see this search for the written address. Check that it lands in the right place.'}</p><MapFrame query={query} title="the location you are setting" /></>
        : <p className="hint">Type an address or add a pin to preview the map.</p>}
    </div>
  )
}
