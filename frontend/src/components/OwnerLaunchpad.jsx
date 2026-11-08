import React from 'react'

function PathArt({ kind }) {
  return <svg className="path-art" viewBox="0 0 112 90" fill="none" aria-hidden="true">
    {kind === 'find' ? <>
      <rect x="18" y="29" width="75" height="48" rx="9" fill="currentColor" opacity=".12" />
      <path d="M19 34h73M24 34v37h62V34M20 24h70l6 13H14l6-13Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="m32 24-3 13m17-13-1 13m15-13 1 13m13-13 3 13M35 49h17v14H35m28 8V49h14v22" stroke="currentColor" strokeWidth="2" />
      <circle cx="94" cy="16" r="6" fill="currentColor" opacity=".6" />
    </> : kind === 'compare' ? <>
      <rect x="17" y="17" width="38" height="57" rx="8" fill="currentColor" opacity=".12" />
      <rect x="60" y="24" width="35" height="57" rx="8" stroke="currentColor" strokeWidth="2" />
      <rect x="17" y="17" width="35" height="57" rx="8" stroke="currentColor" strokeWidth="2" />
      <path d="m27 34 4 4 8-9m-13 22h17m-17 9h11m24-16 4 4 8-9m-13 22h17m-17 9h11" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </> : <>
      <path d="M25 19a7 7 0 0 1 7-7h48a7 7 0 0 1 7 7v63L56 66 25 82V19Z" fill="currentColor" opacity=".12" />
      <path d="M25 19a7 7 0 0 1 7-7h48a7 7 0 0 1 7 7v63L56 66 25 82V19Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M56 51 42 38a8 8 0 0 1 14-7 8 8 0 0 1 14 7L56 51Z" fill="currentColor" />
    </>}
  </svg>
}

export default function OwnerLaunchpad({ categories, onCategory, onFind, onCompare, onFavourites, favouritesCount }) {
  const paths = [
    { kind: 'find', label: 'FOR THE EVERYDAY CHALLENGES', title: 'A little less on your plate.', copy: 'Find support for the jobs that take up your day.', action: 'Explore tasks', onClick: onFind },
    { kind: 'compare', label: 'FOR YOUR NEXT DECISION', title: 'Make your tools earn their place.', copy: 'See your current subscription alongside the alternatives.', action: 'Compare subscriptions', onClick: onCompare },
    { kind: 'saved', label: 'FOR THE GOOD FINDS', title: 'Keep your favourites close.', copy: favouritesCount ? `${favouritesCount} saved ${favouritesCount === 1 ? 'tool is' : 'tools are'} ready when you are.` : 'Give the tools you like a home you can come back to.', action: 'Open favourites', onClick: onFavourites },
  ]
  return <section className="owner-launchpad" id="start" aria-labelledby="launchpad-title">
    <div className="launchpad-heading"><div><p className="section-kicker">YOUR MAIN STREET TOOLKIT</p><h2 id="launchpad-title">More room for<br /><span>what you do best.</span></h2></div><p>No perfect starting point needed. Pick what brings you here today.</p></div>
    <div className="owner-paths">{paths.map(path => <button key={path.kind} type="button" className={`owner-path path-${path.kind}`} onClick={path.onClick}>
      <div className="path-top"><span>{path.label}</span><PathArt kind={path.kind} /></div>
      <h3>{path.title}</h3><p>{path.copy}</p><span className="path-action">{path.action}<span className="path-arrow" aria-hidden="true">↗</span></span>
    </button>)}</div>
    <div className="launchpad-categories"><p>Or start with a part of your day</p><div>{categories.map(category => <button key={category.id} type="button" onClick={() => onCategory(category.id)}>{category.name}<span aria-hidden="true">↗</span></button>)}</div></div>
  </section>
}
