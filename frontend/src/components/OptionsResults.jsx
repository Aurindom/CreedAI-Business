import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import './options.css'
import { FavouriteButton } from '../favourites/Favourites'

// Everything shown here comes from the backend recommendation. This file only groups it and
// words it plainly; it never ranks tools, decides fit, or works out a price.

const ROUTE_LABELS = {
  already_have: 'You already have this',
  check_plan: 'Your plan may include this',
  plan_upgrade: 'Needs a higher plan',
  native_add_on: 'Add-on to a tool you use',
  compatible_tool: 'Works with a tool you use',
  separate_tool: 'New tool',
  switch: 'Similar to a tool you already have',
}

const FIT_LABELS = {
  made_for: 'Yes, built for it',
  any_business: 'Yes, for any business',
  you_use_it: 'You already use it',
  unconfirmed: 'Not confirmed',
}

function money(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: amount % 1 ? 2 : 0 }).format(amount)
}

function monthlyCost(option) {
  if (option.added_monthly_usd === null || option.added_monthly_usd === undefined) return 'Ask the company'
  if (option.added_monthly_usd === 0) return option.route === 'already_have' || option.fit === 'you_use_it' ? 'Included in what you pay' : 'Free plan'
  const amount = `${money(option.added_monthly_usd)} a month`
  return option.price_estimated ? `About ${amount} (estimate)` : amount
}

function budgetText(option) {
  if (option.within_budget === true) return 'Fits your budget'
  if (option.within_budget === false) return 'Over your budget'
  return 'Price not confirmed'
}

function factValue(fact) {
  if (!fact) return 'Confirm with the service'
  if (fact.state === 'not_checked') return 'Not checked yet'
  if (!fact.known || fact.state === 'unresolved') return 'Confirm with the service'
  return fact.value
}

function isOwned(option) {
  return option.fit === 'you_use_it' || ['already_have', 'check_plan', 'plan_upgrade'].includes(option.route)
}

function ToolCard({ option, tool, budgetProvided, compare, highlight, uncertain }) {
  const [open, setOpen] = useState(false)
  const checked = option.status === 'verified'
  const setup = option.facts.find((fact) => fact.label === 'Setup')
  const third = budgetProvided ? { label: 'Your budget', value: budgetText(option) } : { label: 'Setup', value: factValue(setup) }
  const fitWarning = uncertain || option.fit === 'unconfirmed'
  const site = option.service_url || tool?.url

  return (
    <article className={`opt-card${highlight ? ' opt-card-best' : ''}`}>
      <div className="opt-card-top">
        <span className="opt-avatar" aria-hidden="true">{option.tool_name.slice(0, 1)}</span>
        <span className={`opt-badge ${checked ? 'opt-badge-ok' : 'opt-badge-warn'}`}>{checked ? 'Checked by us' : 'Not checked by us yet'}</span>
        <FavouriteButton toolId={option.tool_id} name={option.tool_name} />
      </div>
      <p className="opt-route">{ROUTE_LABELS[option.route] || 'Option'}</p>
      <h4>{option.tool_name}</h4>
      {tool?.summary && <p className="opt-summary">{tool.summary}</p>}
      <dl className="opt-facts">
        <div><dt>Monthly cost</dt><dd>{monthlyCost(option)}</dd></div>
        <div><dt>Fits your business?</dt><dd className={fitWarning ? 'opt-warn-text' : ''}>{FIT_LABELS[option.fit] || 'Not confirmed'}</dd></div>
        <div><dt>{third.label}</dt><dd>{third.value}</dd></div>
      </dl>
      {fitWarning && option.fit_note && <p className="opt-why"><span aria-hidden="true">!</span> {option.fit_note}</p>}
      <div className="opt-actions">
        {compare}
        <button type="button" className="opt-link" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? 'Hide details' : 'See details'}</button>
        {site && <a className="opt-link" href={site} target="_blank" rel="noopener noreferrer">Visit website <span className="sr-only">(opens in a new tab)</span><span aria-hidden="true">↗</span></a>}
      </div>
      {open && (
        <div className="opt-details">
          {option.cost_note && <p><strong>About the price:</strong> {option.cost_note}</p>}
          {!fitWarning && option.fit_note && <p><strong>Why it fits:</strong> {option.fit_note}</p>}
          <ul>
            {option.facts.map((fact) => (
              <li key={fact.label}>
                <span>{fact.label}</span>
                <span>
                  {factValue(fact)}{fact.inferred ? ' (estimate)' : ''}
                  {fact.source_url && <> · <a href={fact.source_url} target="_blank" rel="noopener noreferrer">Source{fact.checked ? `, checked ${fact.checked}` : ''}<span className="sr-only"> (opens in a new tab)</span></a></>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}

// Questions are worded from what the backend left unconfirmed. They make no claims.
function questionsFor(options, problemTitle, business) {
  return options.slice(0, 3).map((option) => {
    const list = []
    if (option.fit === 'unconfirmed') list.push(`Does ${option.tool_name} handle "${problemTitle.toLowerCase()}" for a ${business}?`)
    if (option.route === 'check_plan' || option.route === 'plan_upgrade') list.push(`Does my current ${option.tool_name} plan include this, or do I need to upgrade?`)
    if (option.added_monthly_usd === null) list.push(`What would ${option.tool_name} cost each month for a business my size, including fees?`)
    option.facts.filter((fact) => !fact.known).forEach((fact) => {
      if (fact.label === 'Setup') list.push(`How long does ${option.tool_name} take to set up, and who does the work?`)
      if (fact.label === 'Privacy') list.push(`What happens to my customer data in ${option.tool_name}?`)
      if (fact.label === 'Support') list.push(`How do I reach a real person at ${option.tool_name} when something goes wrong?`)
    })
    return { id: option.tool_id, name: option.tool_name, list }
  }).filter((group) => group.list.length)
}

function CopyButton({ text }) {
  const [state, setState] = useState('')
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setState('Copied')
    } catch {
      setState("Couldn't copy. Select the questions instead.")
    }
  }
  return <span className="opt-copy"><button type="button" onClick={copy}>Copy questions</button><span role="status">{state}</span></span>
}

// "Did you mean": asks the backend about a few related problems and keeps only confirmed answers.
function useRelatedProblems({ needed, activeProblem, problems, categories, profile }) {
  const [related, setRelated] = useState([])
  const profileKey = JSON.stringify(profile)

  useEffect(() => {
    if (!needed || !activeProblem) {
      setRelated([])
      return undefined
    }
    const category = categories.find((item) => item.capabilities.includes(activeProblem.capability))
    const trade = profile?.trade || null
    const suits = (problem) => !trade || problem.trades?.includes('all') || problem.trades?.includes(trade)
    // Closest first: same category, then similar wording ("scheduling" and "schedule"), then problems common for this business.
    const stems = (text) => new Set((text.toLowerCase().match(/[a-z]{5,}/g) || []).map((word) => word.slice(0, 5)))
    const activeStems = stems(`${activeProblem.title} ${activeProblem.plain_words || ''}`)
    const score = (problem) => {
      let points = 0
      if (category?.capabilities.includes(problem.capability)) points += 3
      if ([...stems(`${problem.title} ${problem.plain_words || ''}`)].some((stem) => activeStems.has(stem))) points += 2
      if (suits(problem)) points += 1
      return points
    }
    const candidates = problems
      .filter((problem) => problem.id !== activeProblem.id)
      .map((problem) => ({ problem, points: score(problem) }))
      .filter((entry) => entry.points >= 2)
      .sort((a, b) => b.points - a.points)
      .slice(0, 4)
      .map((entry) => entry.problem)
    let active = true
    Promise.allSettled(candidates.map((problem) => api.recommend(profile, problem.id).then((found) => ({ problem, found }))))
      .then((results) => {
        if (!active) return
        setRelated(results
          .filter((result) => result.status === 'fulfilled' && result.value.found.winner_tool_id && ['new_tool', 'add_on', 'no_new_tool'].includes(result.value.found.outcome))
          .slice(0, 2)
          .map((result) => result.value.problem))
      })
    return () => { active = false }
  }, [needed, activeProblem?.id, profileKey, problems.length, categories.length])

  return related
}

export default function OptionsResults({ recommendation, toolsById, activeProblem, business, budgetProvided, profile, problems, categories, compareProps, onChooseProblem, onAskPenny, onCompareThese, showRelated = true }) {
  const groups = useMemo(() => {
    // A tool only counts as confirmed when the backend's answer is confirmed.
    // When it says "check with the vendor", even its leading option belongs under "Worth checking".
    const confident = ['new_tool', 'add_on', 'no_new_tool'].includes(recommendation.outcome)
    const all = [...recommendation.options.map((option) => ({ option, uncertain: !confident })), ...recommendation.check_first.map((option) => ({ option, uncertain: true }))]
    const owned = all.filter(({ option }) => isOwned(option))
    const rest = all.filter(({ option }) => !isOwned(option))
    const best = rest.find(({ option, uncertain }) => !uncertain && option.tool_id === recommendation.winner_tool_id)
    return {
      owned,
      best,
      others: rest.filter(({ option, uncertain }) => !uncertain && option !== best?.option),
      checking: rest.filter(({ uncertain }) => uncertain),
    }
  }, [recommendation])

  const unconfirmed = ['verify_with_vendor', 'no_match'].includes(recommendation.outcome)
  const related = useRelatedProblems({ needed: unconfirmed && showRelated, activeProblem, problems, categories, profile })
  const businessName = business ? business.toLowerCase() : 'business like yours'
  const confirmedCount = (groups.best ? 1 : 0) + groups.others.length
  const questions = questionsFor([...groups.owned, ...groups.checking].map(({ option }) => option).filter((option) => option.fit === 'unconfirmed' || option.added_monthly_usd === null || option.route === 'check_plan'), activeProblem?.title || 'this task', businessName)
  const questionText = questions.map((group) => [group.name, ...group.list.map((item) => `- ${item}`)].join('\n')).join('\n\n')

  const headline = {
    no_new_tool: 'Good news: you may not need a new tool',
    add_on: 'A small add-on may be all you need',
    new_tool: "Here's your best match",
    verify_with_vendor: "We couldn't confirm a perfect fit yet",
    no_match: "We don't have a checked tool for this yet",
  }[recommendation.outcome] || "Here's what we found"

  const card = ({ option, uncertain }, highlight = false) => (
    <ToolCard key={option.tool_id} option={option} tool={toolsById[option.tool_id]} budgetProvided={budgetProvided} uncertain={uncertain} highlight={highlight}
      compare={<CompareToggle {...compareProps(option.tool_id)} />} />
  )

  return (
    <div className="opt-results">
      <div className="opt-summary-bar" aria-label="Summary">
        {(confirmedCount > 0 || groups.owned.length === 0) && <span className="opt-pill"><strong>{confirmedCount}</strong> confirmed {confirmedCount === 1 ? 'fit' : 'fits'}</span>}
        {groups.checking.length > 0 && <span className="opt-pill"><strong>{groups.checking.length}</strong> worth checking</span>}
        {groups.owned.length > 0 && <span className="opt-pill"><strong>{groups.owned.length}</strong> you already pay for</span>}
        {recommendation.set_aside.length > 0 && <span className="opt-pill"><strong>{recommendation.set_aside.length}</strong> not a fit</span>}
      </div>

      <div className={`opt-answer${unconfirmed ? ' opt-answer-check' : ''}`} role="status">
        <h3>{headline}</h3>
        <p>{recommendation.message}</p>
        {recommendation.tailoring_note && <p className="opt-muted">{recommendation.tailoring_note}</p>}
        {unconfirmed && (
          <>
            {related.length > 0 && <p className="opt-did-you-mean">Did you mean one of these? We found checked tools for them:</p>}
            <div className="opt-help-actions">
              {related.map((problem) => <button type="button" key={problem.id} className="opt-chip" onClick={() => onChooseProblem(problem.id)}>{problem.title} <span aria-hidden="true">→</span></button>)}
              <button type="button" className="opt-chip" onClick={onAskPenny}>Ask Penny to help decide</button>
              {groups.checking.length > 1 && <button type="button" className="opt-chip" onClick={() => onCompareThese(groups.checking.slice(0, 3).map(({ option }) => option.tool_id))}>Compare these {Math.min(3, groups.checking.length)}</button>}
            </div>
          </>
        )}
      </div>

      {groups.best && <section aria-labelledby="opt-best"><h4 className="opt-group" id="opt-best">Best match</h4><div className="opt-grid">{card(groups.best, true)}</div></section>}
      {groups.owned.length > 0 && <section aria-labelledby="opt-owned"><h4 className="opt-group" id="opt-owned">You already pay for</h4><div className="opt-grid">{groups.owned.map((item) => card(item))}</div></section>}
      {groups.others.length > 0 && <section aria-labelledby="opt-others"><h4 className="opt-group" id="opt-others">Also a good fit</h4><div className="opt-grid">{groups.others.map((item) => card(item))}</div></section>}
      {groups.checking.length > 0 && (
        <section aria-labelledby="opt-checking">
          <h4 className="opt-group" id="opt-checking">Worth checking</h4>
          <p className="opt-group-note">These can do the job, but we haven't confirmed they suit a {businessName}. Ask the company before you pay.</p>
          <div className="opt-grid">{groups.checking.map((item) => card(item))}</div>
        </section>
      )}

      {questions.length > 0 && (
        <details className="opt-more">
          <summary>Questions to ask before you pay ({questions.reduce((total, group) => total + group.list.length, 0)})</summary>
          {questions.map((group) => <div key={group.id}><h5>{group.name}</h5><ul>{group.list.map((item) => <li key={item}>{item}</li>)}</ul></div>)}
          <CopyButton text={questionText} />
        </details>
      )}
      {budgetProvided && recommendation.budget_note && (
        <details className="opt-more"><summary>How we used your budget</summary><p>{recommendation.budget_note}</p></details>
      )}
      {recommendation.set_aside.length > 0 && (
        <details className="opt-more">
          <summary>Not a fit, and why ({recommendation.set_aside.length})</summary>
          <ul>{recommendation.set_aside.map((item) => <li key={item.tool_id}><strong>{item.tool_name}:</strong> {item.reason}</li>)}</ul>
        </details>
      )}
    </div>
  )
}

function CompareToggle({ selected, full, onCompare }) {
  return (
    <button type="button" className={`opt-compare${selected ? ' opt-compare-on' : ''}`} aria-pressed={selected} disabled={!selected && full} onClick={onCompare}>
      {selected ? '✓ Added to compare' : 'Add to compare'}
    </button>
  )
}
