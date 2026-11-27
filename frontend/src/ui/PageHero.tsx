import { ChevronDown, ChevronRight } from 'lucide-react'
import { Suspense, lazy, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { RichText } from './RichText'
import { plain } from './boldText'
import { PageBlocks, SmartLink, usePageDesign } from './builder/PageDesign'
import { modelFor, pageIdOf } from './builder/types'

const Scene3D = lazy(() => import('./Scene3D'))

/** The heading band every public page starts with: breadcrumb, small label, title and one sentence, over the page's picture if it
 *  has one, with a 3D model beside it. What the owner wrote in the page builder replaces the built-in words, and the sections they
 *  placed at the top of the page follow it. */
export function PageHero({ eyebrow, title, lead, image, children, crumb, icon }: {
  eyebrow?: string; title: string; lead?: string | null; image?: string | null; children?: ReactNode; crumb?: string; icon?: ReactNode
}) {
  const page = pageIdOf(useLocation().pathname)
  const hero = usePageDesign(page)?.hero
  const shownTitle = hero?.title || title
  const shownEyebrow = hero?.eyebrow || eyebrow
  const shownLead = hero?.lead || lead
  const picture = hero?.image_url || image
  const model = modelFor(page, hero?.model)
  return (
    <>
      <section className={`page-hero ${picture ? 'has-image' : ''} ${model ? 'has-model' : ''}`}>
        {picture && <img className="page-hero-img" src={picture} alt="" />}
        <span className="ring a" aria-hidden /><span className="ring b" aria-hidden />
        <div className="container page-hero-cols">
          <div>
            <nav className="crumbs" aria-label="Breadcrumb"><Link to="/">Home</Link><ChevronRight size={14} aria-hidden /><span aria-current="page">{crumb ?? plain(title)}</span></nav>
            {shownEyebrow && <p className="page-hero-eyebrow">{icon}<RichText text={shownEyebrow} /></p>}
            <h1><RichText text={shownTitle} /></h1>
            {shownLead && <p className="page-hero-lead"><RichText text={shownLead} /></p>}
            {(children || (hero?.button_label && hero.button_link)) && (
              <div className="page-hero-actions">{hero?.button_label && hero.button_link && <SmartLink to={hero.button_link} className="btn lg">{hero.button_label}</SmartLink>}{children}</div>
            )}
          </div>
          {model && <div className="page-hero-model"><span className="halo" aria-hidden /><Suspense fallback={null}><Scene3D kind={model} /></Suspense></div>}
        </div>
        <span className="scroll-cue" aria-hidden><ChevronDown size={20} /></span>
      </section>
      {page && <PageBlocks page={page} placement="top" />}
    </>
  )
}
