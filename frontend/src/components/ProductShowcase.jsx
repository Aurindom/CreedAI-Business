import React, { useEffect, useRef } from 'react'
import BusinessCarousel from './BusinessCarousel'

const featured = [
  { id: 'jobber', label: 'Run the day.', category: 'FIELD SERVICE', mark: 'J', theme: 'mint' },
  { id: 'slang_ai', label: 'Take the call.', category: 'RESTAURANT CALLS', mark: 'S', theme: 'violet' },
  { id: 'quickbooks_online', label: 'See the bigger picture.', category: 'BOOKKEEPING', mark: 'qb', theme: 'lime' },
]

export default function ProductShowcase({ tools, paused, onChooseBusiness }) {
  const section = useRef(null)

  useEffect(() => {
    const root = section.current
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0
    const paint = () => {
      frame = 0
      const rect = root.getBoundingClientRect()
      const range = Math.max(1, root.offsetHeight - window.innerHeight)
      const progress = Math.min(1, Math.max(0, -rect.top / range))
      const staticView = paused || reduced.matches
      const p = staticView ? 1 : progress
      root.style.setProperty('--showcase-progress', String(p))
      root.style.setProperty('--product-scale', String(1.34 - p * .57))
      root.style.setProperty('--product-tilt', `${12 - p * 12}deg`)
      root.style.setProperty('--product-shift', `${p * -30}%`)
      root.style.setProperty('--intro-opacity', String(Math.max(0, 1 - p * 3)))
      root.style.setProperty('--detail-opacity', String(Math.min(1, Math.max(0, (p - .32) / .32))))
      root.style.setProperty('--detail-shift', `${Math.max(0, 1 - p * 1.5) * 60}px`)
      root.dataset.static = String(staticView)
      root.querySelector('.story-details').style.visibility = p > .32 ? 'visible' : 'hidden'
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(paint) }
    paint()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    reduced.addEventListener('change', schedule)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      reduced.removeEventListener('change', schedule)
    }
  }, [paused])

  const products = featured.map((item) => ({ ...item, tool: tools.find((tool) => tool.id === item.id) }))

  return (
    <>
      <BusinessCarousel paused={paused} onChooseBusiness={onChooseBusiness} />
      <section className="product-story" id="product-story" ref={section} aria-labelledby="story-title">
        <div className="product-sticky">
          <div className="showcase-halo" aria-hidden="true" />
          <div className="story-intro"><p>LESS FRICTION. MORE POSSIBILITY.</p><h2 id="story-title">Meet your<br />next advantage.</h2></div>
          <div className="product-composition" aria-label="Featured tools from the catalog">
            {products.map((product, index) => (
              <article className={`showcase-product product-${index} theme-${product.theme}`} key={product.id}>
                <div className="product-topline"><span>main street / discover</span><span aria-hidden="true">&#10022;</span></div>
                <div className="product-mark" aria-hidden="true">{product.mark}</div>
                <p className="product-category">{product.category}</p>
                <h3>{product.tool?.name || product.category}</h3>
                <div className="product-art" aria-hidden="true"><span /><span /><span /><span /><span /></div>
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
      <div className="finder-intro"><p>YOUR BUSINESS. YOUR NEXT CHAPTER.</p><h2>Let's find your fit.</h2><span>A few details. Relevant options. A more informed decision.</span></div>
    </>
  )
}
