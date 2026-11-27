import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { RichText } from './RichText'
import { plain } from './boldText'

/** The heading band every public page starts with: breadcrumb, small label, title and one sentence, over the page's picture if it has one. */
export function PageHero({ eyebrow, title, lead, image, children, crumb, icon }: {
  eyebrow?: string; title: string; lead?: string | null; image?: string | null; children?: ReactNode; crumb?: string; icon?: ReactNode
}) {
  return (
    <section className={`page-hero ${image ? 'has-image' : ''}`}>
      {image && <img className="page-hero-img" src={image} alt="" />}
      <span className="ring a" aria-hidden /><span className="ring b" aria-hidden />
      <div className="container">
        <nav className="crumbs" aria-label="Breadcrumb"><Link to="/">Home</Link><ChevronRight size={14} aria-hidden /><span aria-current="page">{crumb ?? plain(title)}</span></nav>
        {eyebrow && <p className="page-hero-eyebrow">{icon}<RichText text={eyebrow} /></p>}
        <h1><RichText text={title} /></h1>
        {lead && <p className="page-hero-lead"><RichText text={lead} /></p>}
        {children && <div className="page-hero-actions">{children}</div>}
      </div>
    </section>
  )
}
