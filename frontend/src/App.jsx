import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api'

const stages = [
  { number: '01', title: 'Your business', detail: 'Give us a little context', anchor: 'business' },
  { number: '02', title: 'Your challenge', detail: 'Pick a category and task', anchor: 'challenge' },
  { number: '03', title: 'Your options', detail: 'What fits, and what to check', anchor: 'explore' },
  { number: '04', title: 'Compare & plan', detail: 'Make a sensible choice', anchor: 'compare' },
]

const problemIcons = {
  missed_calls: '☎',
  slow_lead_replies: '↗',
  review_requests: '✦',
  review_replies: '✎',
  job_scheduling: '▦',
  staff_scheduling: '◷',
  invoicing: '$',
  bookkeeping: '▤',
  point_of_sale: '▣',
  email_marketing: '✉',
}

const routeLabels = {
  already_have: 'You already have this',
  check_plan: 'Your plan may include this',
  native_add_on: 'Add-on to a tool you use',
  plan_upgrade: 'Needs a higher plan',
  compatible_tool: 'Connects to a tool you use',
  separate_tool: 'A new tool',
  switch: 'Overlaps a tool you use',
}

const outcomeTones = {
  no_new_tool: 'good',
  add_on: 'good',
  new_tool: 'good',
  verify_with_vendor: 'check',
  no_match: 'none',
}

function ArrowIcon({ size = 18 }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M4 12h15m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path d="m5 12 4 4L19 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function priceOf(tool) {
  const fact = tool?.entry_monthly_usd
  return fact?.status === 'present' && typeof fact.value === 'number' ? fact.value : null
}

function dollars(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(amount)
}

function stageAnchor(anchor) {
  document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// Mirrors Catalog.resolve_trade on the backend so directory labels agree with the ranking.
function resolveTrade(trades, text) {
  const wanted = (text || '').trim().toLowerCase().replaceAll(' ', '_')
  if (!wanted) return null
  return trades.find((t) => wanted === t.id || wanted === t.name.toLowerCase().replaceAll(' ', '_'))?.id ?? null
}

function tradeNames(trades, ids, limit = 3) {
  const names = ids.map((id) => trades.find((t) => t.id === id)?.name || id)
  if (names.length <= limit) return names.join(', ')
  return `${names.slice(0, limit).join(', ')} and ${names.length - limit} more`
}

function audienceOf(tool, trades, tradeId) {
  if (tool.applicability === 'cross_industry') return { tone: 'good', text: 'Works for any kind of business' }
  if (tool.applicability === 'unknown') return { tone: 'check', text: 'Not yet confirmed which businesses it suits' }
  if (tradeId && tool.trades.includes(tradeId)) return { tone: 'good', text: 'Built for your kind of business' }
  return { tone: tradeId ? 'none' : 'check', text: `Built for ${tradeNames(trades, tool.trades)}` }
}

function useDebounced(value, delay) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), delay)
    return () => window.clearTimeout(id)
  }, [value, delay])
  return settled
}

function CompareButton({ selected, full, onClick }) {
  return (
    <button type="button" className={selected ? 'compare-selected' : ''} onClick={onClick} aria-pressed={selected} disabled={!selected && full}>
      {selected ? <><CheckIcon /> Added</> : 'Compare +'}
    </button>
  )
}

function OptionCard({ option, tool, selected, full, onCompare, uncertain }) {
  return (
    <article className="tool-card">
      <div className="tool-card-head">
        <span className="tool-avatar">{option.tool_name.slice(0, 1)}</span>
        <span className={`tool-status ${uncertain || option.route === 'check_plan' || option.route === 'plan_upgrade' ? 'pending' : 'verified'}`}>{routeLabels[option.route]}</span>
      </div>
      <h3>{option.tool_name}</h3>
      <p className="tool-summary">{tool?.summary}</p>
      <div className={`fit-line fit-${option.fit === 'unconfirmed' ? 'check' : 'good'}`}>{option.fit_note}</div>
      <div className="tool-divider" />
      <div className="tool-price">
        <div>
          <small>Added cost per month</small>
          <strong>{option.added_monthly_usd === null ? 'Ask vendor' : `${dollars(option.added_monthly_usd)} / mo`}</strong>
        </div>
        <CompareButton selected={selected} full={full} onClick={onCompare} />
      </div>
      <p className="cost-note">{option.cost_note}</p>
      <dl className="fact-list">
        {option.facts.map((fact) => (
          <div key={fact.label} className={fact.known ? 'fact-known' : 'fact-unknown'}>
            <dt>{fact.label}</dt>
            <dd>
              {fact.value}
              {fact.known && fact.source_type === 'vendor' && <span className="fact-source"> · vendor says</span>}
              {fact.checked && <span className="fact-source"> · checked {fact.checked}</span>}
              {!fact.known && fact.note && <span className="fact-why">{fact.note}</span>}
            </dd>
          </div>
        ))}
      </dl>
      {tool && <a className="source-link" href={tool.url} target="_blank" rel="noopener noreferrer">Visit vendor website <ArrowIcon size={14} /></a>}
    </article>
  )
}

function DirectoryCard({ tool, trades, tradeId, selected, full, onCompare }) {
  const audience = audienceOf(tool, trades, tradeId)
  const price = priceOf(tool)
  return (
    <article className="tool-card">
      <div className="tool-card-head"><span className="tool-avatar">{tool.name.slice(0, 1)}</span><span className={`tool-status ${tool.status === 'verified' ? 'verified' : 'pending'}`}>{tool.status === 'verified' ? 'Source checked' : 'Pending review'}</span></div>
      <h3>{tool.name}</h3><p className="tool-summary">{tool.summary}</p>
      <div className={`fit-line fit-${audience.tone}`}>{audience.text}</div>
      <div className="tool-divider" />
      <div className="tool-price"><div><small>Published entry price</small><strong>{price === null ? 'Ask vendor' : `${dollars(price)} / mo`}</strong></div><CompareButton selected={selected} full={full} onClick={onCompare} /></div>
      <a className="source-link" href={tool.url} target="_blank" rel="noopener noreferrer">Visit vendor website <ArrowIcon size={14} /></a>
    </article>
  )
}

const levelWords = { low: 'Low effort', medium: 'Some effort', high: 'High effort', strong: 'Strong', partial: 'Partial', weak: 'Weak' }

function factText(fact) {
  if (!fact || fact.status === 'unknown' || fact.value == null) return 'Not checked yet'
  return levelWords[fact.value] ?? String(fact.value)
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

function App() {
  const [trades, setTrades] = useState([])
  const [categories, setCategories] = useState([])
  const [allTools, setAllTools] = useState([])
  const [problems, setProblems] = useState([])
  const [directory, setDirectory] = useState([])
  const [loadError, setLoadError] = useState('')

  const [businessName, setBusinessName] = useState('')
  const [businessType, setBusinessType] = useState('')
  const [owned, setOwned] = useState([])
  const [category, setCategory] = useState('')
  const [selectedProblem, setSelectedProblem] = useState('')
  const [recommendation, setRecommendation] = useState(null)
  const [recommendError, setRecommendError] = useState('')
  const [showDirectory, setShowDirectory] = useState(false)
  const [selectedTools, setSelectedTools] = useState([])
  const [stack, setStack] = useState(null)
  const [taskText, setTaskText] = useState('')
  const [taskNotice, setTaskNotice] = useState(false)

  const typedTrade = useDebounced(businessType.trim(), 300)
  const tradeId = resolveTrade(trades, typedTrade)
  const tradeLabel = tradeId ? trades.find((t) => t.id === tradeId)?.name : typedTrade
  const toolsById = useMemo(() => Object.fromEntries(allTools.map((t) => [t.id, t])), [allTools])
  const activeProblem = problems.find((p) => p.id === selectedProblem) || null
  const activeCategory = categories.find((c) => c.id === category) || null

  useEffect(() => {
    Promise.all([api.trades(), api.categories(), api.tools()])
      .then(([tradeList, categoryList, toolList]) => {
        setTrades(tradeList)
        setCategories(categoryList)
        setAllTools(toolList)
      })
      .catch((error) => setLoadError(error.message))
  }, [])

  useEffect(() => {
    api.problems(typedTrade, category).then(setProblems).catch((error) => setLoadError(error.message))
    api.tools(typedTrade, category).then(setDirectory).catch((error) => setLoadError(error.message))
  }, [typedTrade, category])

  useEffect(() => {
    if (!selectedProblem) {
      setRecommendation(null)
      return
    }
    setRecommendError('')
    api.recommend({ trade: typedTrade || null, owned_tool_ids: owned }, selectedProblem)
      .then(setRecommendation)
      .catch((error) => setRecommendError(error.message))
  }, [selectedProblem, typedTrade, owned])

  useEffect(() => {
    if (selectedTools.length === 0) {
      setStack(null)
      return
    }
    api.stackCheck(selectedTools).then(setStack).catch(() => setStack(null))
  }, [selectedTools])

  const comparison = selectedTools.map((id) => toolsById[id]).filter(Boolean)
  const ranked = [...(recommendation?.options || []), ...(recommendation?.check_first || [])]
  const optionsById = Object.fromEntries(ranked.map((o) => [o.tool_id, o]))
  const full = selectedTools.length >= 3

  function toggleCompare(toolId) {
    setSelectedTools((current) => {
      if (current.includes(toolId)) return current.filter((id) => id !== toolId)
      if (current.length >= 3) return current
      return [...current, toolId]
    })
  }

  function toggleOwned(toolId) {
    setOwned((current) => (current.includes(toolId) ? current.filter((id) => id !== toolId) : [...current, toolId]))
  }

  function chooseProblem(id) {
    setSelectedProblem(id)
    setSelectedTools([])
    setShowDirectory(false)
    window.setTimeout(() => stageAnchor('explore'), 80)
  }

  function chooseCategory(id) {
    setCategory(id)
    const next = categories.find((c) => c.id === id)
    if (activeProblem && next && !next.capabilities.includes(activeProblem.capability)) setSelectedProblem('')
  }

  function compareProps(toolId) {
    return { selected: selectedTools.includes(toolId), full, onCompare: () => toggleCompare(toolId) }
  }

  const businessNote = typedTrade && !tradeId
    ? `We haven't checked tools for "${typedTrade}" yet. You'll still see tools that suit any business, and we'll say so.`
    : 'Pick a suggestion or type your own. If we have not checked your kind of business, we only rank tools that suit any business.'

  const exploreHeading = showDirectory ? 'Browse the directory' : 'What fits this task'
  const exploreLead = showDirectory
    ? `Every tool in ${activeCategory ? activeCategory.name : 'the catalog'}, with who it is built for.`
    : activeProblem ? `For “${activeProblem.title.toLowerCase()}”.` : 'Choose a task above to see what fits.'
  const exploreCount = showDirectory
    ? plural(directory.length, 'tool')
    : recommendation ? plural(recommendation.options.length, 'ranked option') : 'No task chosen'

  return (
    <div className="site-shell">
      <aside className="sidebar">
        <div className="brand" role="img" aria-label="Main Street AI">
          <div className="brand-mark"><span /><span /><span /><span /></div>
          <div className="brand-wordmark">main<span>street</span><b>ai</b></div>
        </div>
        <div className="sidebar-group">
          <div className="sidebar-label">YOUR JOURNEY</div>
          <nav className="stage-list" aria-label="Page sections">
            {stages.map((stage) => (
              <button className="stage" key={stage.number} type="button" onClick={() => stageAnchor(stage.anchor)}>
                <span className="stage-number">{stage.number}</span>
                <span className="stage-copy"><strong>{stage.title}</strong><small>{stage.detail}</small></span>
              </button>
            ))}
          </nav>
        </div>
        <div className="sidebar-bottom">
          <div className="sidebar-tip-icon">✳</div>
          <strong>A calmer way to choose AI.</strong>
          <p>See what is known, what needs checking, and what fits the way you work.</p>
          <span>LOCAL PRODUCT PREVIEW</span>
        </div>
      </aside>

      <main className="main-panel">
        <div className="topbar">
          <span className="topbar-route">Workspace <span>/</span> Find your fit</span>
          <div className="topbar-right"><span className="status-dot" /> Prototype preview <span className="topbar-divider" /> <span className="topbar-avatar">AM</span></div>
        </div>

        <div className="content">
          {loadError && <div className="error-banner" role="alert"><strong>We couldn't reach the catalog service.</strong> {loadError}</div>}

          <section className="hero">
            <div className="hero-text">
              <div className="eyebrow"><span className="eyebrow-line" /> THE SMALL BUSINESS AI GUIDE</div>
              <h1>AI tools that make sense <em>for your business.</em></h1>
              <p>Tell us what is taking up your time. Explore relevant tools, compare what they really offer, and leave with a clearer next step.</p>
              <button className="primary-button" type="button" onClick={() => stageAnchor('business')}>Find my starting point <ArrowIcon /></button>
            </div>
            <div className="hero-graphic" aria-hidden="true">
              <div className="graphic-orbit orbit-one" /><div className="graphic-orbit orbit-two" />
              <div className="graphic-card graphic-card-top"><span className="graphic-card-icon">✦</span><div><strong>Find your fit</strong><small>Start with a real need</small></div><span className="graphic-check">✓</span></div>
              <div className="graphic-center"><span>AI</span><small>made practical</small></div>
              <div className="graphic-card graphic-card-bottom"><span className="graphic-card-icon green">▦</span><div><strong>Compare clearly</strong><small>Cost · fit · evidence</small></div><span className="graphic-check">✓</span></div>
            </div>
          </section>

          <div className="metrics-row">
            <div><strong>{allTools.length}</strong><span>tools in the catalog</span></div>
            <div><strong>{categories.length}</strong><span>categories of everyday work</span></div>
            <div><strong>{trades.length}</strong><span>business types checked, and any other works too</span></div>
          </div>

          <section className="section-block" id="business">
            <div className="section-heading"><div><div className="section-kicker">STEP 01 <span /> GET ORIENTED</div><h2>Tell us about your business</h2><p>All optional. It only changes which tools rank first.</p></div><div className="section-counter">01 / 04</div></div>
            <div className="form-card">
              <label className="field"><span>Business name <small>optional</small></span><input type="text" value={businessName} onChange={(event) => setBusinessName(event.target.value)} placeholder="e.g. Northside Coffee" maxLength={80} /></label>
              <label className="field">
                <span>Type of business <small>optional, type anything</small></span>
                <input type="text" list="trade-list" value={businessType} onChange={(event) => setBusinessType(event.target.value)} placeholder="e.g. Bakery, Plumbing, Dog grooming" maxLength={100} />
                <datalist id="trade-list">{trades.map((t) => <option key={t.id} value={t.name} />)}</datalist>
              </label>
              <div className="field owned-field">
                <span>Tools you already pay for <small>optional</small></span>
                <div className="chip-list">
                  {allTools.map((t) => (
                    <button key={t.id} type="button" className={`chip ${owned.includes(t.id) ? 'chip-on' : ''}`} aria-pressed={owned.includes(t.id)} onClick={() => toggleOwned(t.id)}>{owned.includes(t.id) && <CheckIcon />}{t.name}</button>
                  ))}
                </div>
              </div>
              <div className="form-note"><span>✳</span><p>{businessNote}</p></div>
            </div>
          </section>

          <section className="section-block" id="challenge">
            <div className="section-heading"><div><div className="section-kicker">STEP 02 <span /> NAME THE PROBLEM</div><h2>What would you like help with?</h2><p>Browse by category, then pick a task.</p></div><div className="section-counter">02 / 04</div></div>
            <div className="category-tabs" role="tablist" aria-label="Categories">
              <button type="button" role="tab" aria-selected={category === ''} className={`tab ${category === '' ? 'tab-on' : ''}`} onClick={() => chooseCategory('')}>All</button>
              {categories.map((c) => (
                <button key={c.id} type="button" role="tab" aria-selected={category === c.id} className={`tab ${category === c.id ? 'tab-on' : ''}`} onClick={() => chooseCategory(c.id)}>{c.name}</button>
              ))}
            </div>
            <div className="problem-grid">
              {problems.map((problem) => (
                <button className={`problem-card ${selectedProblem === problem.id ? 'selected' : ''}`} type="button" key={problem.id} onClick={() => chooseProblem(problem.id)}>
                  <span className="problem-icon">{problemIcons[problem.id] || '✦'}</span><span className="problem-title">{problem.title}</span><span className="problem-description">{problem.plain_words}</span><span className="problem-arrow"><ArrowIcon size={16} /></span>
                </button>
              ))}
            </div>
            <div className="custom-task">
              <div><span className="custom-task-icon">✳</span><div><strong>Something different?</strong><small>Describe the task you want to improve.</small></div></div>
              <form onSubmit={(event) => { event.preventDefault(); setTaskNotice(true) }}><input aria-label="Describe your task" value={taskText} onChange={(event) => { setTaskText(event.target.value); setTaskNotice(false) }} placeholder="e.g. I spend hours following up with customers..." /><button type="submit" disabled={!taskText.trim()}>Try my words <ArrowIcon size={16} /></button></form>
              {taskNotice && <p className="preview-notice">We have your wording. Agent matching is being connected. Choose a card above to see the catalog answer today.</p>}
            </div>
          </section>

          <section className="section-block" id="explore">
            <div className="section-heading"><div><div className="section-kicker">STEP 03 <span /> YOUR OPTIONS</div><h2>{exploreHeading}</h2><p>{exploreLead}</p></div><div className="section-counter">03 / 04</div></div>
            <div className="explore-toolbar">
              <div><strong>{exploreCount}</strong><span>{tradeLabel ? ` · ${tradeLabel}` : ' · Any business'}</span></div>
              <button type="button" onClick={() => setShowDirectory((value) => !value)}>{showDirectory ? 'Back to my options' : 'Browse directory'} <ArrowIcon size={15} /></button>
            </div>

            {showDirectory && <div className="tool-grid">{directory.map((tool) => (
              <DirectoryCard key={tool.id} tool={tool} trades={trades} tradeId={tradeId} {...compareProps(tool.id)} />
            ))}</div>}

            {!showDirectory && !activeProblem && <div className="empty-state"><span>◇</span><strong>Choose a task first</strong><p>That lets us rank tools for the job you actually need done.</p><button type="button" onClick={() => stageAnchor('challenge')}>See the tasks <ArrowIcon size={16} /></button></div>}

            {!showDirectory && activeProblem && recommendError && <div className="error-banner" role="alert"><strong>We couldn't get an answer.</strong> {recommendError}</div>}

            {!showDirectory && activeProblem && !recommendError && recommendation && <>
              <div className={`answer-banner answer-${outcomeTones[recommendation.outcome]}`}>
                <strong>{recommendation.message}</strong>
                {recommendation.tailoring_note && <p>{recommendation.tailoring_note}</p>}
              </div>
              {recommendation.options.length > 0 && <div className="tool-grid">{recommendation.options.map((option) => (
                <OptionCard key={option.tool_id} option={option} tool={toolsById[option.tool_id]} {...compareProps(option.tool_id)} />
              ))}</div>}
              {recommendation.check_first.length > 0 && <>
                <h3 className="subhead">Check with the vendor first</h3>
                <p className="subhead-note">These cover the task, but we haven't confirmed they suit your kind of business. They are never picked as the answer.</p>
                <div className="tool-grid">{recommendation.check_first.map((option) => (
                  <OptionCard key={option.tool_id} option={option} tool={toolsById[option.tool_id]} {...compareProps(option.tool_id)} uncertain />
                ))}</div>
              </>}
              {recommendation.set_aside.length > 0 && <details className="set-aside">
                <summary>{plural(recommendation.set_aside.length, 'tool')} set aside because they are built for other businesses</summary>
                <ul>{recommendation.set_aside.map((item) => <li key={item.tool_id}><strong>{item.tool_name}</strong> · {item.reason}</li>)}</ul>
              </details>}
            </>}
          </section>

          <section className="section-block compare-section" id="compare">
            <div className="section-heading"><div><div className="section-kicker">STEP 04 <span /> DECIDE WITH CLARITY</div><h2>Compare your shortlist</h2><p>Put up to three tools side by side. We leave unknown facts visible.</p></div><div className="section-counter">04 / 04</div></div>
            {comparison.length === 0 ? <div className="comparison-empty"><div className="comparison-empty-art"><span>▤</span><span>▤</span><span>▤</span></div><strong>Your comparison starts here</strong><p>Use the “Compare +” button on a tool above. You can add up to three.</p></div> : <>
              <div className="comparison-wrap"><table className="comparison-table"><thead><tr><th>What to check</th>{comparison.map((tool) => <th key={tool.id}>{tool.name}<button type="button" onClick={() => toggleCompare(tool.id)} aria-label={`Remove ${tool.name}`}>×</button></th>)}</tr></thead><tbody>
                <tr><td>Who it is built for</td>{comparison.map((tool) => <td key={tool.id}>{optionsById[tool.id]?.fit_note || audienceOf(tool, trades, tradeId).text}</td>)}</tr>
                <tr><td>Entry price</td>{comparison.map((tool) => <td key={tool.id}>{priceOf(tool) === null ? 'Unknown' : `${dollars(priceOf(tool))} / mo`}</td>)}</tr>
                <tr><td>Cost for this task</td>{comparison.map((tool) => {
                  const option = optionsById[tool.id]
                  if (!option) return <td key={tool.id}>{activeProblem ? 'Not ranked for this task' : 'Choose a task'}</td>
                  return <td key={tool.id}>{option.added_monthly_usd === null ? `Unknown. ${option.cost_note}` : `${dollars(option.added_monthly_usd)} / mo`}</td>
                })}</tr>
                {[['Setup', 'setup_effort'], ['Privacy', 'privacy'], ['Support', 'support_stability']].map(([label, key]) => (
                  <tr key={key}><td>{label}</td>{comparison.map((tool) => <td key={tool.id}>{factText(tool[key])}</td>)}</tr>
                ))}
                <tr><td>Catalog status</td>{comparison.map((tool) => <td key={tool.id}>{tool.status === 'verified' ? 'Source checked' : 'Pending review'}</td>)}</tr>
              </tbody></table></div>
              {stack?.duplicates.length > 0 && <div className="answer-banner answer-check compare-overlap"><strong>These overlap.</strong><p>{stack.duplicates.join('. ')}. You may not need both.</p></div>}
              <div className="plan-preview"><div><span className="plan-icon">↗</span><div><strong>Early plan preview</strong><p>{businessName.trim() || 'Your business'} · {activeProblem?.title || 'Choose a challenge'} · {plural(comparison.length, 'tool')} shortlisted</p></div></div><div className="plan-cost"><small>Known entry prices add up to</small><strong>{stack ? `${dollars(stack.known_monthly_usd)}${stack.total_monthly_usd === null ? ' + unknowns' : ' / mo'}` : '...'}</strong></div></div>
              <p className="comparison-footnote">Entry prices only, before processing, hardware or add-on fees.{stack?.unknown_cost_tools.length ? ` No published price for ${stack.unknown_cost_tools.join(', ')}.` : ''}</p>
            </>}
          </section>

          <section className="next-panel"><div className="next-symbol">✳</div><div><span>WHAT COMES NEXT</span><h2>From a shortlist to a real plan.</h2><p>The finished guide will check your current software plan, compare true costs, flag overlapping tools, and help you take the next step.</p></div><button type="button" onClick={() => stageAnchor('business')}>Explore again <ArrowIcon size={17} /></button></section>
          <footer><span>Main Street AI · A clearer way to choose AI</span><span>Prototype catalog checked 2026-11-07</span></footer>
        </div>
      </main>
    </div>
  )
}

export default App
