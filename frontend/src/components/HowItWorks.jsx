import React, { useEffect, useRef } from 'react'

const steps = [
  { number: '1', title: 'Tell us about your business', detail: 'Your type of business and the software you already pay for. Every question is optional.' },
  { number: '2', title: "Pick what's slowing you down", detail: 'Missed calls, the books, reviews, scheduling and more, in plain words.' },
  { number: '3', title: 'See what we recommend', detail: 'Recommended tools show sourced prices and facts. More options link straight to each website so you can look for yourself.' },
  { number: '4', title: 'Compare, plan, or ask Arkadio', detail: 'Compare side by side, save a plan, or ask Arkadio. It can even draft a custom assistant for your staff.' },
]

// The core features, first and in plain words. Cards fade in once as they scroll into view.
export default function HowItWorks({ onStart, onAskPenny, onCompare, accent }) {
  const root = useRef(null)

  useEffect(() => {
    const element = root.current
    if (!element || !window.IntersectionObserver) {
      element?.classList.add('is-visible')
      return undefined
    }
    const observer = new window.IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        element.classList.add('is-visible')
        observer.disconnect()
      }
    }, { threshold: 0.15 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return (
    <section className="how-it-works" id="how-it-works" ref={root} aria-labelledby="how-it-works-title" style={{ '--journey-accent': accent || '#d8c8ff' }}>
      <div className="how-connection" aria-hidden="true"><span /><i /><span /></div>
      <div className="how-inner">
      <div className="how-intro">
      <p className="how-kicker">HOW CREED AI HELPS</p>
      <h2 id="how-it-works-title">Find the right AI tools in four simple steps</h2>
      <p className="how-lead">No tech knowledge needed. You can start with the steps below or just ask Arkadio.</p>
      </div>
      <ol className="how-steps">
        {steps.map((step, index) => (
          <li className="how-step" key={step.number} style={{ '--step-delay': `${index * 90}ms` }}>
            <span className="how-number" aria-hidden="true">{step.number}</span>
            <h3>{step.title}</h3>
            <p>{step.detail}</p>
          </li>
        ))}
      </ol>
      <div className="how-actions">
        <button type="button" className="how-primary" onClick={onStart}>Start with step 1 <span aria-hidden="true">&#8595;</span></button>
        <button type="button" className="how-secondary" onClick={onAskPenny}>Ask Arkadio instead</button>
        <button type="button" className="how-link" onClick={onCompare}>Already pay for a tool? Compare it</button>
      </div>
      </div>
    </section>
  )
}
