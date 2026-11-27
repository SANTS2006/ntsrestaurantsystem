// Location maps use Google Maps' public embed and directions links, so no API key is needed.
export type Place = { address?: string | null; latitude?: string | number | null; longitude?: string | number | null }

const has = (v: unknown) => v !== null && v !== undefined && String(v).trim() !== '' && Number.isFinite(Number(v))

/** What to look for on the map: the exact pin when staff set one, otherwise the written address. Empty when there is neither. */
export function mapQuery(p: Place): string {
  if (has(p.latitude) && has(p.longitude)) return `${Number(p.latitude)},${Number(p.longitude)}`
  return (p.address ?? '').trim()
}

export const embedUrl = (query: string) => `https://maps.google.com/maps?q=${encodeURIComponent(query)}&z=16&output=embed`
export const directionsUrl = (query: string) => `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(query)}`
export const viewUrl = (query: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`

/**
 * Coordinates from what a person pastes: "8.4844, -13.2344", or a Google Maps address-bar link
 * (".../@8.4844,-13.2344,17z", "?q=8.4844,-13.2344" or the "!3d8.4844!4d-13.2344" of a place link).
 */
export function parseCoordinates(input: string): { latitude: string; longitude: string } | null {
  let text = input.trim()
  try { text = decodeURIComponent(text) } catch { /* keep the text as typed */ }
  const n = '(-?\\d{1,3}(?:\\.\\d+)?)'
  const patterns = [
    new RegExp(`!3d${n}!4d${n}`), // the pin of a place, more exact than the centre of the view
    new RegExp(`[?&](?:q|query|destination|ll)=${n},\\s*${n}`),
    new RegExp(`@${n},${n}`),
    new RegExp(`^${n}\\s*[,; ]\\s*${n}$`),
  ]
  for (const re of patterns) {
    const m = text.match(re)
    if (!m) continue
    const lat = Number(m[1])
    const lng = Number(m[2])
    if (Math.abs(lat) <= 90 && Math.abs(lng) <= 180) return { latitude: String(Number(lat.toFixed(6))), longitude: String(Number(lng.toFixed(6))) }
  }
  return null
}

/** "12 Beach Road, Freetown, Sierra Leone" without repeating a part the street line already ends with. */
export const fullAddress = (...parts: (string | null | undefined)[]) =>
  parts.map((x) => (x ?? '').trim()).filter((x, i, all) => x && !all.slice(0, i).some((y) => y.toLowerCase().includes(x.toLowerCase()))).join(', ')
