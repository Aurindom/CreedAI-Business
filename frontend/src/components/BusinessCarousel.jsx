import React, { useEffect, useRef, useState } from 'react'

const businesses = [
  { type: 'Coffee shop', image: 'coffee-shop', alt: 'Coffee being poured by hand behind a cafe counter', eyebrow: 'FOR THE EARLY RISERS', title: 'You make the coffee.', accent: 'Make room for more.', copy: 'The morning rush. The staff rota. The books after closing. Find tools for the work behind the work you love.', challenges: ['Staff scheduling', 'Bookkeeping', 'Customer reviews'], theme: '#edc49e', source: 'https://images.unsplash.com/photo-1442512595331-e89e73853f31' },
  { type: 'Restaurant', image: 'restaurant', alt: 'Warmly lit restaurant tables set for dinner service', eyebrow: 'FOR THE NEIGHBORHOOD FAVORITES', title: 'Every table has a story.', accent: 'Keep yours growing.', copy: 'When the dining room fills up, everything else keeps moving. Explore help with calls, team schedules, and customer follow-up.', challenges: ['Missed calls', 'Staff scheduling', 'Review replies'], theme: '#d4ddbc', source: 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0' },
  { type: 'Salon or barber', image: 'barber-shop', alt: 'A barber carefully trimming a customer\'s beard', eyebrow: 'FOR THE PEOPLE WHO KNOW YOUR NAME', title: 'Your craft. Your clients.', accent: 'Your next chapter.', copy: 'You bring the personal touch. Discover options for appointments, reminders, and the admin that follows you home.', challenges: ['Appointments', 'Customer follow-up', 'Bookkeeping'], theme: '#d5c6f0', source: 'https://images.unsplash.com/photo-1503951914875-452162b0f3f1' },
  { type: 'Retail shop', image: 'flower-shop', alt: 'A neighborhood flower shop with bouquets displayed outside', eyebrow: 'FOR THE HEART OF MAIN STREET', title: 'More than a storefront.', accent: 'Someone\'s dream.', copy: 'From the first customer to the last invoice, your day is full. Find a little support for the business you built.', challenges: ['Email marketing', 'Customer reviews', 'Invoicing'], theme: '#eac5ce', source: 'https://unsplash.com/photos/a-flower-shop-on-the-side-of-a-street-EqIB29_JeZs' },
  {"type": "Bakery", "image": "bakery", "title": "Fresh bread.", "accent": "Fresh possibilities.", "eyebrow": "FOR THE ONES UP BEFORE THE SUN", "copy": "You put care into every batch. Explore support for shift planning, customer updates, and the books that wait until closing.", "challenges": ["Staff scheduling", "Email marketing", "Bookkeeping"], "theme": "#e8c79d", "alt": "Fresh artisan bread on a bakery worktop", "source": "https://images.unsplash.com/photo-1509440159596-0249088772ff"},
  {"type": "Food truck", "image": "food-truck", "title": "Big flavor.", "accent": "Small footprint.", "eyebrow": "FOR THE KITCHENS ON WHEELS", "copy": "Your kitchen moves. Your business keeps going. Find options for answering customers, sending invoices, and keeping your finances in view.", "challenges": ["Customer follow-up", "Invoicing", "Bookkeeping"], "theme": "#bfd5e9", "alt": "A blue food truck parked on a city street", "source": "https://images.unsplash.com/photo-1565123409695-7b5ef63a2efb"},
  {"type": "Bar or brewery", "image": "bar", "title": "Good nights start here.", "accent": "Keep the business flowing.", "eyebrow": "FOR THE AFTER-HOURS ORIGINALS", "copy": "Behind every great night are staff schedules, customer messages, and tomorrow's paperwork. Explore tools for that side of the bar.", "challenges": ["Staff scheduling", "Customer reviews", "Bookkeeping"], "theme": "#e7bd97", "alt": "A neighborhood bar with warm lights and a stocked counter", "source": "https://images.unsplash.com/photo-1514933651103-005eec06c04b"},
  {"type": "Spa or wellness", "image": "spa", "title": "A little more calm.", "accent": "For your business, too.", "eyebrow": "FOR THE PEOPLE WHO HELP US RESET", "copy": "You create space for others to unwind. Discover options for bookings, reminders, and keeping in touch between visits.", "challenges": ["Appointments", "Customer follow-up", "Email marketing"], "theme": "#d3ddc2", "alt": "Spa towels, a candle, and flowers", "source": "https://images.unsplash.com/photo-1540555700478-4be289fbecef"},
  {"type": "Gym or fitness studio", "image": "fitness", "title": "You build their strength.", "accent": "Build your next chapter.", "eyebrow": "FOR THE EVERYDAY MOTIVATORS", "copy": "Classes, clients, and a growing to-do list. Explore support for schedules, customer communication, and everyday business admin.", "challenges": ["Staff scheduling", "Email marketing", "Bookkeeping"], "theme": "#c7d0ea", "alt": "Weights and training equipment in a fitness studio", "source": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48"},
  {"type": "Clinic or vet", "image": "clinic", "title": "Care comes first.", "accent": "Make space for it.", "eyebrow": "FOR THE TEAMS WHO SHOW UP FOR OTHERS", "copy": "Your team has a lot to coordinate. Explore options for general office scheduling and business admin, with privacy details to check before you choose.", "challenges": ["Staff scheduling", "Bookkeeping", "Privacy checks"], "theme": "#bcdedb", "alt": "Reception and waiting area in a clinic", "source": "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d"},
  {"type": "Pet care", "image": "pet-care", "title": "Big hearts. Happy paws.", "accent": "A business to grow.", "eyebrow": "FOR THE NEIGHBORHOOD ANIMAL LOVERS", "copy": "Between walks, grooming, and pickup times, admin adds up. Explore tools for bookings, customer updates, and everyday paperwork.", "challenges": ["Appointments", "Customer follow-up", "Invoicing"], "theme": "#eccbaf", "alt": "Two dogs running together outdoors", "source": "https://images.unsplash.com/photo-1548199973-03cce0bbc87b"},
  {"type": "Auto shop", "image": "auto-shop", "title": "Keep them moving.", "accent": "Keep your shop growing.", "eyebrow": "FOR THE PEOPLE UNDER THE HOOD", "copy": "You know what keeps an engine running. Find support for the calls, appointments, and invoices that keep your business running.", "challenges": ["Missed calls", "Appointments", "Invoicing"], "theme": "#c3ced8", "alt": "Close-up of a vehicle engine and belts", "source": "https://images.unsplash.com/photo-1486262715619-67b85e0b08d3"},
  {"type": "Professional services", "image": "office", "title": "Your expertise matters.", "accent": "Give it more room.", "eyebrow": "FOR THE INDEPENDENT EXPERTS", "copy": "Your clients come for what you know. Explore tools for scheduling, client communication, and keeping on top of the numbers.", "challenges": ["Appointments", "Invoicing", "Bookkeeping"], "theme": "#d7ccec", "alt": "An independent workspace with desks and large windows", "source": "https://images.unsplash.com/photo-1497366811353-6870744d04b2"},
  {"type": "Cleaning", "image": "cleaning", "title": "A fresh start.", "accent": "For every workday.", "eyebrow": "FOR THE TEAMS BEHIND THE SHINE", "copy": "Jobs to schedule, customers to update, and invoices to send. Discover options for keeping the work around each clean organized.", "challenges": ["Job scheduling", "Invoicing", "Customer follow-up"], "theme": "#c5ded5", "alt": "A cleaning professional wiping a window", "source": "https://images.unsplash.com/photo-1581578731548-c64695cc6952"},
  {"type": "HVAC", "image": "home-services", "title": "Comfort is your calling.", "accent": "Growth is your next move.", "eyebrow": "FOR THE TEAMS WHO KEEP THINGS RUNNING", "copy": "When you are out on a job, the calls keep coming. Explore tools for incoming leads, job schedules, and the paperwork between visits.", "challenges": ["Missed calls", "Job scheduling", "Invoicing"], "theme": "#cad6e7", "alt": "A power drill on a home improvement worksite", "source": "https://images.unsplash.com/photo-1504148455328-c376907d081c"},
  {"type": "Plumbing", "image": "electrical", "title": "Every call matters.", "accent": "Make room for the next.", "eyebrow": "FOR THE LOCAL PROBLEM SOLVERS", "copy": "From urgent callouts to planned visits, every day is different. Explore help with lead replies, job schedules, and invoices.", "challenges": ["Customer follow-up", "Job scheduling", "Invoicing"], "theme": "#bfd8e0", "alt": "A home service professional working at a building site", "source": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e"},
  {"type": "Electrical", "image": "electrical", "title": "You bring the power.", "accent": "Find your next spark.", "eyebrow": "FOR THE PEOPLE WHO CONNECT IT ALL", "copy": "Your hands are busy on site. Discover options for handling customer messages, organizing jobs, and sending the next invoice.", "challenges": ["Missed calls", "Job scheduling", "Invoicing"], "theme": "#e9d0a1", "alt": "A technician working on a wall installation", "source": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e"},
  {"type": "Landscaping or lawn care", "image": "landscaping", "title": "You make things grow.", "accent": "Your business included.", "eyebrow": "FOR THE OUTDOOR ORIGINALS", "copy": "From the first quote to the last job of the day, there is more to manage than the garden. Explore scheduling, follow-up, and invoicing tools.", "challenges": ["Job scheduling", "Invoicing", "Customer reviews"], "theme": "#c2d4b1", "alt": "Gardening tools and potting soil on a work surface", "source": "https://images.unsplash.com/photo-1416879595882-3373a0480b5b"},
  {"type": "Handyman or repair", "image": "home-services", "title": "Built with your hands.", "accent": "Backed by better tools.", "eyebrow": "FOR THE PEOPLE WHO GET IT DONE", "copy": "You fix a little of everything. Find options for organizing incoming jobs, replying to leads, and keeping invoices moving.", "challenges": ["Job scheduling", "Customer follow-up", "Invoicing"], "theme": "#ddc7af", "alt": "A cordless drill at a repair worksite", "source": "https://images.unsplash.com/photo-1504148455328-c376907d081c"},

]

// Hero challenge labels map to catalog problem cards, so a tap goes straight to matching tools.
const CHALLENGE_PROBLEMS = {
  'Staff scheduling': 'staff_scheduling',
  Bookkeeping: 'bookkeeping',
  'Customer reviews': 'review_requests',
  'Review replies': 'review_replies',
  'Missed calls': 'missed_calls',
  Appointments: 'appointment_booking',
  'Customer follow-up': 'slow_lead_replies',
  'Email marketing': 'email_marketing',
  Invoicing: 'invoicing',
  'Job scheduling': 'job_scheduling',
}

export default function BusinessCarousel({ paused = false, onChooseBusiness, onChooseProblem, onAskPenny, onCompare, onSceneChange }) {
  const [active, setActive] = useState(0)
  // Advance by default; interaction and reduced-motion preferences suspend playback.
  const [playing, setPlaying] = useState(true)
  const [engaged, setEngaged] = useState(false)
  const [reduced, setReduced] = useState(false)
  const root = useRef(null)
  const touch = useRef(null)
  const pagination = useRef(null)
  const [visible, setVisible] = useState(true)
  const [pageVisible, setPageVisible] = useState(true)
  const move = (direction) => setActive((index) => (index + direction + businesses.length) % businesses.length)

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(preference.matches)
    const visibility = () => setPageVisible(!document.hidden)
    update()
    visibility()
    preference.addEventListener('change', update)
    document.addEventListener('visibilitychange', visibility)
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting))
    observer.observe(root.current)
    return () => {
      preference.removeEventListener('change', update)
      document.removeEventListener('visibilitychange', visibility)
      observer.disconnect()
    }
  }, [])

  useEffect(() => {
    const business = businesses[active]
    onSceneChange?.({ image: business.image, type: business.type, theme: business.theme })
  }, [active, onSceneChange])

  const autoPlaying = playing && !paused && !reduced
  useEffect(() => {
    if (!autoPlaying || engaged || !visible || !pageVisible) return
    const timer = window.setInterval(() => move(1), 7500)
    return () => window.clearInterval(timer)
  }, [autoPlaying, engaged, visible, pageVisible, active])

  useEffect(() => {
    const list = pagination.current
    const selected = list?.children[active]
    if (!selected) return
    list.scrollTo({ left: selected.offsetLeft - list.offsetLeft - list.clientWidth / 2 + selected.clientWidth / 2, behavior: reduced || paused ? 'instant' : 'smooth' })
  }, [active, reduced, paused])

  function navigate(index) {
    setActive((index + businesses.length) % businesses.length)
  }

  return (
    <section className="business-carousel" ref={root} role="region" aria-roledescription="carousel" aria-label="Find tools for your small business"
      onMouseEnter={() => setEngaged(true)} onMouseLeave={() => setEngaged(false)}
      onFocusCapture={() => setEngaged(true)} onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setEngaged(false) }}
      onKeyDown={(event) => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); navigate(active + (event.key === 'ArrowRight' ? 1 : -1)) } }}
      onTouchStart={(event) => { touch.current = { x: event.touches[0].clientX, y: event.touches[0].clientY } }}
      onTouchEnd={(event) => { if (!touch.current) return; const dx = event.changedTouches[0].clientX - touch.current.x; const dy = event.changedTouches[0].clientY - touch.current.y; if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) navigate(active + (dx < 0 ? 1 : -1)); touch.current = null }}>
      {businesses.map((business, index) => (
        <article className={`business-slide${index === active ? ' is-active' : ''}`} key={business.type} inert={index !== active} aria-hidden={index !== active} aria-roledescription="slide" aria-label={`${index + 1} of ${businesses.length}: ${business.type}`} style={{ '--business-accent': business.theme }}>
          <img className="business-photo" src={index === active || index === (active + 1) % businesses.length || index === (active - 1 + businesses.length) % businesses.length ? `/images/${business.image}.jpg` : undefined} alt={business.alt} loading="eager" fetchPriority={index === 0 ? 'high' : 'auto'} />
          <div className="business-shade" />
          <div className="business-slide-content">
            <p className="business-kicker"><span /> {business.eyebrow}</p>
            <h1>{business.title}<br /><em>{business.accent}</em></h1>
            <p className="business-story">{business.copy}</p>
            <button className="business-start" type="button" onClick={() => onChooseBusiness(business.type)}>Find tools for my business <span aria-hidden="true">&#8599;</span></button>
            <button className="business-ask-penny" type="button" onClick={onAskPenny}>Ask Penny <span aria-hidden="true">&#8599;</span></button>
            <button className="business-explore business-compare-shortcut" type="button" onClick={onCompare}>Already pay for a tool? Compare it <span aria-hidden="true">&#8599;</span></button>
          </div>
          <div className="business-day" role="group" aria-label={`Common problems for a ${business.type.toLowerCase()}`}><span className="day-label">What's slowing you down?</span>{business.challenges.map((challenge) => CHALLENGE_PROBLEMS[challenge]
            ? <button type="button" className="day-challenge" key={challenge} onClick={() => onChooseProblem?.(business.type, CHALLENGE_PROBLEMS[challenge])}><span aria-hidden="true">&#10022;</span>{challenge}</button>
            : <span className="day-challenge" key={challenge}><span aria-hidden="true">&#10022;</span>{challenge}</span>)}</div>
          <a className="photo-credit" href={business.source} target="_blank" rel="noopener noreferrer">Photo / Unsplash</a>
        </article>
      ))}
      <div className="business-jump"><label htmlFor="business-story-select">Your kind of business</label><select id="business-story-select" value={active} onChange={(event) => navigate(Number(event.target.value))}>{businesses.map((business, index) => <option value={index} key={business.type}>{business.type}</option>)}</select><span>{businesses.length} businesses. Find your story.</span></div>
      <div className="carousel-bottom">
        <div className="business-pagination" ref={pagination} aria-hidden="true">{businesses.map((business, index) => <button type="button" key={business.type} tabIndex={-1} className={active === index ? 'is-active' : ''} aria-label={`Show ${business.type} story`} aria-current={active === index ? 'true' : undefined} onClick={() => navigate(index)}><span className="pagination-index">{String(index + 1).padStart(2, '0')}</span><span>{business.type}</span><i aria-hidden="true" /></button>)}</div>
        <div className="carousel-controls"><span className="carousel-count" aria-live={autoPlaying ? 'off' : 'polite'}>{String(active + 1).padStart(2, '0')} / {businesses.length}</span><button type="button" aria-label="Previous business story" onClick={() => navigate(active - 1)}>&#8592;</button><button type="button" aria-label="Next business story" onClick={() => navigate(active + 1)}>&#8594;</button>{!paused && !reduced && <button type="button" aria-label={playing ? 'Pause slideshow' : 'Play slideshow'} aria-pressed={!playing} onClick={() => setPlaying((value) => !value)}>{playing ? <span aria-hidden="true">&#10074;&#10074;</span> : <span aria-hidden="true">&#9654;</span>}</button>}</div>
      </div>
      <a className="carousel-skip" href="#start">Skip to tool finder</a>
    </section>
  )
}
