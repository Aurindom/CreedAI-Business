import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api, ownedProfile, planChoices, isSingleOffering, PLAN_UNKNOWN, PLAN_LABEL_MAX } from './api'
import ProductShowcase from './components/ProductShowcase'

const stages = [
  { number: '01', title: 'Your business', detail: 'Give us a little context', anchor: 'business' },
  { number: '02', title: 'Your challenge', detail: 'Pick a category and task', anchor: 'challenge' },
  { number: '03', title: 'Your options', detail: 'What fits, and what to check', anchor: 'explore' },
  { number: '04', title: 'Compare & plan', detail: 'Make a sensible choice', anchor: 'compare' },
]

const categoryIcons = {
  calls_messages: '\u260e', reviews: '\u2726', scheduling: '\u25a6',
  staff: '\u25f7', finance: '$', marketing: '\u2709', sales: '\u25a3',
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
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(amount)
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
  if (tool.applicability === 'cross_industry') return { tone: 'good', text: 'Offered to many kinds of business' }
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

function OptionCard({ option, tool, selected, full, onCompare, uncertain, budgetProvided }) {
  return (
    <article className="tool-card">
      <div className="tool-card-head">
        <span className="tool-avatar">{option.tool_name.slice(0, 1)}</span>
        <span className={`tool-status ${option.status !== 'verified' || uncertain || option.route === 'check_plan' || option.route === 'plan_upgrade' ? 'pending' : 'verified'}`}>{option.status === 'verified' ? 'Source checked' : 'Pending review'}</span>
      </div>
      <p className="route-label">{routeLabels[option.route]}</p>
      <h3>{option.tool_name}</h3>
      <p className="tool-summary">{tool?.summary}</p>
      <div className={`fit-line fit-${uncertain || option.status !== 'verified' || option.fit === 'unconfirmed' ? 'check' : 'good'}`}>{option.fit_note}</div>
      <div className="tool-divider" />
      <div className="tool-price">
        <div>
          <small>Added cost per month</small>
          <strong>{option.added_monthly_usd === null ? 'Ask vendor' : `${dollars(option.added_monthly_usd)} / mo`}</strong>
        </div>
        <CompareButton selected={selected} full={full} onClick={onCompare} />
      </div>
      <p className="cost-note">{option.cost_note}</p>
      {budgetProvided && <p className={`budget-status budget-${option.within_budget === true ? 'within' : option.within_budget === false ? 'over' : 'unknown'}`}>{option.within_budget === true ? 'Within your added monthly budget' : option.within_budget === false ? 'Over your added monthly budget' : 'Cost unknown - budget fit unconfirmed'}</p>}
      <dl className="fact-list">
        {option.facts.map((fact) => (
          <div key={fact.label} className={fact.known ? 'fact-known' : 'fact-unknown'}>
            <dt>{fact.label}</dt>
            <dd><ToolFactValue fact={fact} toolName={option.tool_name} />
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

function ToolFactValue({ fact, toolName }) {
  if (fact === null) return <span className="fact-load-error">Evidence unavailable. Try selecting this tool again.</span>
  if (!fact) return <span className="fact-loading">Loading evidence...</span>
  return <span className={`fact-value fact-state-${fact.state}`}>
    {fact.state === 'not_checked' ? 'Not checked yet' : fact.state === 'unresolved' ? 'Unknown' : fact.value}
    {fact.source_type === 'vendor' && fact.known && <span className="fact-source"> ? vendor says</span>}
    {fact.note && <span className="fact-why">{fact.note}</span>}
    {fact.checked && <small className="evidence-date">Checked {fact.checked}</small>}
    {fact.source_url && <a className="evidence-link" href={fact.source_url} target="_blank" rel="noopener noreferrer" aria-label={`View ${fact.label.toLowerCase()} source for ${toolName}`}>View source</a>}
  </span>
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
  const [ownedPlans, setOwnedPlans] = useState({})
  const [budget, setBudget] = useState('')
  const [comparisonFacts, setComparisonFacts] = useState({})
  const [category, setCategory] = useState('')
  const [selectedProblem, setSelectedProblem] = useState('')
  const [recommendation, setRecommendation] = useState(null)
  const [recommendError, setRecommendError] = useState('')
  const [isRecommending, setIsRecommending] = useState(false)
  const [showDirectory, setShowDirectory] = useState(false)
  const [selectedTools, setSelectedTools] = useState([])
  const [stack, setStack] = useState(null)
  const [taskText, setTaskText] = useState('')
  const [taskResolution, setTaskResolution] = useState(null)
  const [taskError, setTaskError] = useState('')
  const [isResolving, setIsResolving] = useState(false)
  const taskRequest = useRef(0)
  const [motionPaused, setMotionPaused] = useState(false)

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
    let current = true
    Promise.all([api.problems(typedTrade, category), api.tools(typedTrade, category)])
      .then(([cards, tools]) => {
        if (!current) return
        setProblems(cards)
        setDirectory(tools)
        setLoadError('')
      })
      .catch((error) => { if (current) setLoadError(error.message) })
    return () => { current = false }
  }, [typedTrade, category])

  useEffect(() => {
    let current = true
    setRecommendation(null)
    setRecommendError('')
    if (!selectedProblem) {
      setIsRecommending(false)
      return
    }
    setIsRecommending(true)
    api.recommend({ ...ownedProfile(typedTrade, owned, ownedPlans), budget_monthly_usd: budget === '' ? null : Number(budget) }, selectedProblem)
      .then((result) => { if (current) setRecommendation(result) })
      .catch((error) => { if (current) setRecommendError(error.message) })
      .finally(() => { if (current) setIsRecommending(false) })
    return () => { current = false }
  }, [selectedProblem, typedTrade, owned, ownedPlans, budget])

  useEffect(() => {
    let current = true
    setStack(null)
    if (selectedTools.length === 0) return
    api.stackCheck(selectedTools)
      .then((result) => { if (current) setStack(result) })
      .catch(() => { if (current) setStack(null) })
    return () => { current = false }
  }, [selectedTools])

  useEffect(() => {
    let current = true
    setComparisonFacts({})
    Promise.all(selectedTools.map(async (id) => {
      try { return [id, await api.toolFacts(id)] }
      catch { return [id, null] }
    })).then((entries) => { if (current) setComparisonFacts(Object.fromEntries(entries)) })
    return () => { current = false }
  }, [selectedTools])

  function comparisonFact(tool, label) {
    const facts = comparisonFacts[tool.id]
    return <ToolFactValue fact={facts === null ? null : facts?.find((fact) => fact.label === label)} toolName={tool.name} />
  }

  async function resolveTypedTask(event) {
    event.preventDefault()
    if (!taskText.trim() || isResolving) return
    const requestId = ++taskRequest.current
    setIsResolving(true)
    setTaskError('')
    setTaskResolution(null)
    try {
      const result = await api.resolveTask(taskText.trim())
      if (requestId !== taskRequest.current) return
      setTaskResolution(result)
      if (result.status === 'matched') {
        setCategory('')
        chooseProblem(result.problem_id)
      }
    } catch (error) {
      if (requestId === taskRequest.current) setTaskError(error.message)
    } finally {
      if (requestId === taskRequest.current) setIsResolving(false)
    }
  }

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
    taskRequest.current += 1
    setIsResolving(false)
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
    return { selected: selectedTools.includes(toolId), full, budgetProvided: budget !== '', onCompare: () => toggleCompare(toolId) }
  }

  const businessNote = typedTrade && !tradeId
    ? `We haven't checked tools for "${typedTrade}" yet. You'll still see tools offered to many kinds of business, and we'll say so.`
    : 'Pick a suggestion or type your own. If we have not checked your kind of business, we rank tools offered to many kinds of business.'

  const exploreHeading = showDirectory ? 'Browse the directory' : 'What fits this task'
  const exploreLead = showDirectory
    ? `Every tool in ${activeCategory ? activeCategory.name : 'the catalog'}, with who it is built for.`
    : activeProblem ? `For “${activeProblem.title.toLowerCase()}”.` : 'Choose a task above to see what fits.'
  const exploreCount = showDirectory
    ? plural(directory.length, 'tool')
    : recommendation ? plural(recommendation.options.length, 'ranked option') : 'No task chosen'

  return (
    <div className={`site-shell${motionPaused ? ' motion-paused' : ''}`}>
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
        <div className="ambient-flow" aria-hidden="true">
          <span className="flow-orb flow-peach" />
          <span className="flow-orb flow-blue" />
          <span className="flow-orb flow-gold" />
          <svg className="flow-lines" viewBox="0 0 1200 900" preserveAspectRatio="xMidYMid slice">
            <path d="M-200 650 C150 100 420 980 760 440 S1180 140 1440 380" />
            <path d="M-180 700 C180 150 450 1030 790 490 S1210 190 1470 430" />
            <path d="M-160 750 C210 200 480 1080 820 540 S1240 240 1500 480" />
          </svg>
        </div>
        <div className="topbar">
          <span className="topbar-route">Discover what comes next</span>
          <div className="topbar-right"><button className="motion-toggle" type="button" aria-pressed={motionPaused} onClick={() => setMotionPaused((paused) => !paused)}>{motionPaused ? 'Resume motion' : 'Pause motion'}</button><span className="status-dot" /> Prototype preview <span className="topbar-divider" /> <span className="topbar-avatar">AM</span></div>
        </div>

        <div className="content">
          {loadError && <div className="error-banner" role="alert"><strong>We couldn't reach the catalog service.</strong> {loadError}</div>}

          <ProductShowcase tools={allTools} paused={motionPaused} onChooseBusiness={(type) => { setBusinessType(type); stageAnchor('business') }} />

          <div className="metrics-row">
            <div><strong>{allTools.length}</strong><span>tools in the catalog</span></div>
            <div><strong>{categories.length}</strong><span>categories of everyday work</span></div>
            <div><strong>{trades.length}</strong><span>business types in the catalog</span></div>
          </div>

          <section className="section-block" id="business">
            <div className="section-heading"><div><div className="section-kicker">STEP 01 <span /> GET ORIENTED</div><h2>Tell us about your business</h2><p>A little context helps us find relevant options. Every field is optional.</p></div><div className="section-counter">01 / 04</div></div>
            <div className="form-card">
              <label className="field"><span>Business name <small>optional</small></span><input type="text" value={businessName} onChange={(event) => setBusinessName(event.target.value)} placeholder="e.g. Northside Coffee" maxLength={80} /></label>
              <label className="field">
                <span>Type of business <small>optional, type anything</small></span>
                <input type="text" list="trade-list" value={businessType} onChange={(event) => setBusinessType(event.target.value)} placeholder="e.g. Bakery, Plumbing, Dog grooming" maxLength={100} />
                <datalist id="trade-list">{trades.map((t) => <option key={t.id} value={t.name} />)}</datalist>
              </label>
              <label className="field budget-field"><span>Added monthly budget <small>optional, USD</small></span><input type="number" min="0" step="0.01" value={budget} onChange={(event) => { const value = event.target.value; if (value === '' || (Number.isFinite(Number(value)) && Number(value) >= 0)) setBudget(value) }} placeholder="e.g. 100" /><small>What you can add to your current bill each month. Leave blank for no budget preference.</small></label>
              <div className="field owned-field">
                <span>Tools you already pay for <small>optional</small></span>
                <div className="chip-list">
                  {allTools.map((t) => (
                    <button key={t.id} type="button" className={`chip ${owned.includes(t.id) ? 'chip-on' : ''}`} aria-pressed={owned.includes(t.id)} onClick={() => toggleOwned(t.id)}>{owned.includes(t.id) && <CheckIcon />}{t.name}</button>
                  ))}
                </div>
              </div>
              {owned.some((id) => !isSingleOffering(toolsById[id])) && <div className="owned-plans">
                <div className="owned-plans-heading"><strong>Which plans do you use?</strong><p>Choose a plan so we can check what you already pay for. It is fine if you do not know.</p></div>
                {owned.filter((id) => !isSingleOffering(toolsById[id])).map((id) => {
                  const tool = toolsById[id]
                  const choices = planChoices(tool)
                  return <label className="field" key={id}><span>{tool.name} plan <small>optional</small></span>{choices.length ? <select value={ownedPlans[id] ?? PLAN_UNKNOWN} onChange={(event) => setOwnedPlans((plans) => ({ ...plans, [id]: event.target.value }))}><option value={PLAN_UNKNOWN}>I do not know</option>{choices.map((plan) => <option value={plan} key={plan}>{plan}</option>)}</select> : <><input value={ownedPlans[id] ?? ''} maxLength={PLAN_LABEL_MAX} onChange={(event) => setOwnedPlans((plans) => ({ ...plans, [id]: event.target.value }))} placeholder="Plan name, if you know it" /><small>Not checked by us. We will ask you to verify an unrecognized plan.</small></>}</label>
                })}
              </div>}
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
                  <span className="problem-icon">{categoryIcons[categories.find((item) => item.capabilities.includes(problem.capability))?.id] || '✦'}</span><span className="problem-title">{problem.title}</span><span className="problem-description">{problem.plain_words}</span><span className="problem-arrow"><ArrowIcon size={16} /></span>
                </button>
              ))}
            </div>
            <div className="custom-task">
              <div><span className="custom-task-icon">✳</span><div><strong>Something different?</strong><small>Describe the task you want to improve.</small></div></div>
              <form onSubmit={resolveTypedTask}><input aria-label="Describe your task" maxLength={300} value={taskText} onChange={(event) => { taskRequest.current += 1; setTaskText(event.target.value); setTaskResolution(null); setTaskError(''); setIsResolving(false) }} placeholder="e.g. I need to book appointments online" /><button type="submit" disabled={!taskText.trim() || isResolving}>{isResolving ? 'Finding a task...' : 'Find my task'} <ArrowIcon size={16} /></button></form>
              {isResolving && <p className="preview-notice" role="status">Matching your words to the catalog...</p>}
              {taskError && <p className="task-error" role="alert">We could not match your task. {taskError} You can still choose a card above.</p>}
              {taskResolution && <div className="task-resolution" role="status"><p>{taskResolution.message}</p>{taskResolution.status === 'ambiguous' && <div className="task-choices">{taskResolution.choices.map((choice) => <button type="button" key={choice.id} onClick={() => { setCategory(''); chooseProblem(choice.id); setTaskResolution(null) }}>{choice.title} <ArrowIcon size={14} /></button>)}</div>}</div>}

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

            {!showDirectory && activeProblem && isRecommending && <div className="loading-state" role="status"><span className="loading-dot" />Finding options for your business...</div>}

            {!showDirectory && activeProblem && recommendError && <div className="error-banner" role="alert"><strong>We couldn't get an answer.</strong> {recommendError}</div>}

            {!showDirectory && activeProblem && !recommendError && recommendation && <>
              <div className={`answer-banner answer-${outcomeTones[recommendation.outcome]}`}>
                <strong>{recommendation.message}</strong>
                {recommendation.tailoring_note && <p>{recommendation.tailoring_note}</p>}
                {recommendation.budget_note && <p className="budget-explanation">{recommendation.budget_note}</p>}
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
                <ul>{recommendation.set_aside.map((item) => <li key={item.tool_id}><strong>{item.tool_name}</strong> <span className={`tool-status ${item.status === 'verified' ? 'verified' : 'pending'}`}>{item.status === 'verified' ? 'Source checked' : 'Pending review'}</span> · {item.reason}</li>)}</ul>
              </details>}
            </>}
          </section>

          <section className="section-block compare-section" id="compare">
            <div className="section-heading"><div><div className="section-kicker">STEP 04 <span /> DECIDE WITH CLARITY</div><h2>Compare your shortlist</h2><p>Put up to three tools side by side. We leave unknown facts visible.</p></div><div className="section-counter">04 / 04</div></div>
            {comparison.length === 0 ? <div className="comparison-empty"><div className="comparison-empty-art"><span>▤</span><span>▤</span><span>▤</span></div><strong>Your comparison starts here</strong><p>Use the “Compare +” button on a tool above. You can add up to three.</p></div> : <>
              <div className="comparison-wrap"><table className="comparison-table"><thead><tr><th>What to check</th>{comparison.map((tool) => <th key={tool.id}>{tool.name}<button type="button" onClick={() => toggleCompare(tool.id)} aria-label={`Remove ${tool.name}`}>×</button></th>)}</tr></thead><tbody>
                <tr><td>Who it is built for</td>{comparison.map((tool) => <td key={tool.id}>{optionsById[tool.id]?.fit_note || audienceOf(tool, trades, tradeId).text}</td>)}</tr>
                <tr><td>Entry price</td>{comparison.map((tool) => <td key={tool.id}>{comparisonFact(tool, 'Entry price')}</td>)}</tr>
                <tr><td>Cost for this task</td>{comparison.map((tool) => {
                  const option = optionsById[tool.id]
                  if (!option) return <td key={tool.id}>{activeProblem ? 'Not ranked for this task' : 'Choose a task'}</td>
                  return <td key={tool.id}>{option.added_monthly_usd === null ? `Unknown. ${option.cost_note}` : `${dollars(option.added_monthly_usd)} / mo`}</td>
                })}</tr>
                {['Setup', 'Privacy', 'Support'].map((label) => (
                  <tr key={label}><td>{label}</td>{comparison.map((tool) => <td key={tool.id}>{comparisonFact(tool, label)}</td>)}</tr>
                ))}
                <tr><td>Catalog status</td>{comparison.map((tool) => <td key={tool.id}>{tool.status === 'verified' ? 'Source checked' : 'Pending review'}</td>)}</tr>
              </tbody></table></div>
              {stack?.duplicates.length > 0 && <div className="answer-banner answer-check compare-overlap"><strong>These overlap.</strong><p>{stack.duplicates.join('. ')}. You may not need both.</p></div>}
              <div className="plan-preview"><div><span className="plan-icon">↗</span><div><strong>Early plan preview</strong><p>{businessName.trim() || 'Your business'} · {activeProblem?.title || 'Choose a challenge'} · {plural(comparison.length, 'tool')} shortlisted</p></div></div><div className="plan-cost"><small>Known entry prices add up to</small><strong>{stack ? `${dollars(stack.known_monthly_usd)}${stack.total_monthly_usd === null ? ' + unknowns' : ' / mo'}` : '...'}</strong></div></div>
              <p className="comparison-footnote">Entry prices only, before processing, hardware or add-on fees.{stack?.unknown_cost_tools.length ? ` No published price for ${stack.unknown_cost_tools.join(', ')}.` : ''}</p>
            </>}
          </section>

          <section className="next-panel"><div className="next-symbol">✳</div><div><span>WHAT COMES NEXT</span><h2>From a shortlist to a real plan.</h2><p>Check your current plan, explore task-specific costs, and spot overlapping tools. Saved adoption plans are coming next.</p></div><button type="button" onClick={() => stageAnchor('business')}>Explore again <ArrowIcon size={17} /></button></section>
          <footer><span>Main Street AI · A clearer way to choose AI</span><span>Prototype catalog checked 2026-11-07</span></footer>
        </div>
      </main>
    </div>
  )
}

export default App
