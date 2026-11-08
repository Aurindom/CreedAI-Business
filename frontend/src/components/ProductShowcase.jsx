import React, { useEffect, useRef } from 'react'
import BusinessCarousel from './BusinessCarousel'

const featured = [
  { id: 'jobber', label: 'Run the day.', category: 'FIELD SERVICE', mark: 'J', theme: 'mint' },
  { id: 'slang_ai', label: 'Take the call.', category: 'RESTAURANT CALLS', mark: 'S', theme: 'violet' },
  { id: 'quickbooks_online', label: 'See the bigger picture.', category: 'BOOKKEEPING', mark: 'qb', theme: 'lime' },
]

export default function ProductShowcase({ part = 'hero', scene, onSceneChange, tools, paused, onChooseBusiness, onChooseProblem, onAskPenny, onCompare }) {
  const section = useRef(null)

  useEffect(() => {
    const root = section.current
    if (!root) return undefined
    const stage = root.querySelector('.product-sticky')
    const composition = root.querySelector('.product-composition')
    const intro = root.querySelector('.story-intro')
    const details = root.querySelector('.story-details')
    const backdrop = root.querySelector('.showcase-scene')
    const progressBar = root.querySelector('.story-progress span')
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    const mobile = window.matchMedia('(max-width: 700px)')
    let frame = 0
    let start = 0
    let range = 1
    let inset = 0
    let staticView = false
    let lastProgress = -1

    const progress = () => staticView ? 1 : Math.min(1, Math.max(0, (window.scrollY + inset - start) / range))
    const paint = () => {
      frame = 0
      const p = progress()
      if (p === lastProgress) return
      lastProgress = p
      const eased = p * p * (3 - 2 * p)
      const animating = !staticView && p > 0 && p < 1
      // Only compositor properties change during scrolling. Geometry is measured separately.
      composition.style.transform = mobile.matches ? '' : `translateX(${eased * -34}%) scale(${1.12 - eased * .38}) perspective(1200px) rotateX(${12 - p * 12}deg)`
      composition.style.willChange = animating ? 'transform' : 'auto'
      backdrop.style.opacity = String(.24 * (1 - eased))
      intro.style.opacity = mobile.matches ? '1' : String(Math.max(0, 1 - p * 2.4))
      details.style.opacity = String(Math.min(1, Math.max(0, (p - .4) / .35)))
      details.style.transform = mobile.matches ? '' : `translateY(calc(-50% + ${Math.max(0, 1 - p * 1.5) * 60}px))`
      details.style.visibility = p > .4 ? 'visible' : 'hidden'
      progressBar.style.transform = `scaleX(${p})`
    }
    const schedule = () => {
      // Before and after the showcase, no animation frame or style writes are needed.
      if (!frame && progress() !== lastProgress) frame = window.requestAnimationFrame(paint)
    }
    const measure = () => {
      staticView = paused || reduced.matches || mobile.matches
      root.dataset.static = String(staticView)
      const rect = root.getBoundingClientRect()
      start = rect.top + window.scrollY
      inset = Number.parseFloat(window.getComputedStyle(stage).top) || 0
      range = Math.max(1, root.offsetHeight - stage.offsetHeight)
      lastProgress = -1
      schedule()
    }
    measure()
    const resizeObserver = window.ResizeObserver ? new window.ResizeObserver(measure) : null
    resizeObserver?.observe(root)
    resizeObserver?.observe(stage)
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', measure)
    reduced.addEventListener('change', measure)
    mobile.addEventListener('change', measure)
    return () => {
      window.cancelAnimationFrame(frame)
      resizeObserver?.disconnect()
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', measure)
      reduced.removeEventListener('change', measure)
      mobile.removeEventListener('change', measure)
    }
  }, [paused])

  const products = featured.map((item) => ({ ...item, tool: tools.find((tool) => tool.id === item.id) }))

  if (part === 'hero') {
    return <BusinessCarousel paused={paused} onChooseBusiness={onChooseBusiness} onChooseProblem={onChooseProblem} onAskPenny={onAskPenny} onCompare={onCompare} onSceneChange={onSceneChange} />
  }

  return (
    <>
      <section className="showcase-bridge" aria-label="From your business to the right tools" style={{ '--scene-accent': scene.theme }}>
        <div className="bridge-photo" style={{ backgroundImage: `url(/images/${scene.image}.jpg)` }} aria-hidden="true" />
        <div className="bridge-line" aria-hidden="true" />
        <div className="bridge-copy"><p>YOUR CRAFT IS PERSONAL. YOUR TOOLS SHOULD FIT.</p><h2>Keep doing what you love.<br /><span>Find support for the rest.</span></h2><div className="bridge-caption"><span>{scene.type}</span><span aria-hidden="true">&#8594;</span><span>Your next advantage</span></div></div>
        <a href="#start" className="bridge-skip">Go straight to your tool finder <span aria-hidden="true">&#8599;</span></a>
      </section>
      <section className="product-story" id="product-story" ref={section} aria-labelledby="story-title">
        <div className="product-sticky">
          <div className="showcase-scene" style={{ backgroundImage: `url(/images/${scene.image}.jpg)` }} aria-hidden="true" />
          <div className="showcase-halo" aria-hidden="true" />
          <div className="story-intro"><p>LESS FRICTION. MORE POSSIBILITY.</p><h2 id="story-title">Meet your<br />next advantage.</h2></div>
          <div className="product-composition" aria-label="Featured tools from the catalog">
            {products.map((product, index) => (
              <article className={`showcase-product product-${index} theme-${product.theme}`} key={product.id}>
                <div className="product-topline"><span>main street / discover</span><span aria-hidden="true">&#10022;</span></div>
                <div className="product-mark" aria-hidden="true">{product.mark}</div>
                <p className="product-category">{product.category}</p>
                <h3>{product.tool?.name || product.category}</h3>
                <p className="product-tagline">{product.label}</p>
                <div className="product-art" aria-hidden="true"><span /><span /><span /></div>
                <span className="product-review-label">{product.tool ? (product.tool.status === 'verified' ? 'Source checked' : 'Pending review') : 'Loading catalog'}</span>
                <div className="product-card-bottom"><span>Explore the catalog</span><span aria-hidden="true">&#8599;</span></div>
              </article>
            ))}
          </div>
          <div className="story-details">
            <p className="detail-eyebrow">THE RIGHT TOOL CHANGES THE DAY.</p>
            <h2>Big potential.<br /><span>Down to business.</span></h2>
            <p className="detail-lead">Start with what takes your time. Get to know the tools that could help.</p>
            <div className="featured-facts">
              {products.map((product) => (
                <div key={product.id}>
                  <span className={`mini-mark theme-${product.theme}`} aria-hidden="true">{product.mark}</span>
                  <div><h3>{product.tool?.name || product.category}</h3><p>{product.tool?.summary || 'Loading catalog details...'}</p>{product.tool && <a href={product.tool.url} target="_blank" rel="noopener noreferrer">Explore {product.tool.name} &#8599;</a>}</div>
                </div>
              ))}
            </div>
            <p className="showcase-disclaimer">Catalog highlights, not personalized recommendations. Card artwork is illustrative.</p>
          </div>
          <div className="story-progress" aria-hidden="true"><span /></div>
          <span className="story-caption">DISCOVER. UNDERSTAND. DECIDE.</span>
        </div>
      </section>
    </>
  )
}
