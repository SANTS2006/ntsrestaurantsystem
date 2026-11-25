import { useEffect } from 'react'

type Seo = { title: string; description?: string; image?: string | null; path: string; type?: string; jsonLd?: object }

function setMeta(attr: 'name' | 'property', key: string, content: string | undefined) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`)
  if (!content) return el?.remove()
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

/** Per-page title, description, canonical URL, Open Graph tags and JSON-LD structured data. */
export function useSeo({ title, description, image, path, type = 'website', jsonLd }: Seo) {
  const ld = jsonLd ? JSON.stringify(jsonLd) : ''
  useEffect(() => {
    document.title = title
    const url = `${window.location.origin}${path}`
    setMeta('name', 'description', description)
    setMeta('property', 'og:title', title)
    setMeta('property', 'og:description', description)
    setMeta('property', 'og:image', image ?? undefined)
    setMeta('property', 'og:type', type)
    setMeta('property', 'og:url', url)
    let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!link) {
      link = document.createElement('link')
      link.rel = 'canonical'
      document.head.appendChild(link)
    }
    link.href = url
    let script = document.head.querySelector<HTMLScriptElement>('script#jsonld')
    if (!ld) script?.remove()
    else {
      if (!script) {
        script = document.createElement('script')
        script.id = 'jsonld'
        script.type = 'application/ld+json'
        document.head.appendChild(script)
      }
      script.textContent = ld // JSON.stringify output assigned as text, never parsed as HTML
    }
  }, [title, description, image, path, type, ld])
}
