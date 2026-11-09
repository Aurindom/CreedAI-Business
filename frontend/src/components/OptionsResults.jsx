import React, { useMemo, useState } from 'react'
import './options.css'
import { FavouriteButton } from '../favourites/Favourites'
import ToolWebsiteLink from './ToolWebsiteLink'
import { BADGE, hasPrice, knownFacts, optionChecked, safeWebsite } from '../toolEvidence'

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
}

const aOr = (word) => (/^[aeiou]|^HVAC\b/i.test(word) ? 'an' : 'a')

function money(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: amount % 1 ? 2 : 0 }).format(amount)
}

function monthlyCost(option) {
  if (option.added_monthly_usd === 0) return option.route === 'already_have' || option.fit === 'you_use_it' ? 'Included in what you pay' : 'Free plan'
  const amount = `${money(option.added_monthly_usd)} a month`
  return option.price_estimated ? `About ${amount} (estimate)` : amount
}

function isOwned(option) {
  return option.fit === 'you_use_it' || ['already_have', 'check_plan', 'plan_upgrade'].includes(option.route)
}

// Unknown details are left off the card rather than labelled. The backend keeps the full record.
function cardRows(option, budgetProvided) {
  const rows = []
  if (hasPrice(option)) rows.push({ label: 'Monthly cost', value: monthlyCost(option) })
  if (FIT_LABELS[option.fit]) rows.push({ label: 'Fits your business?', value: FIT_LABELS[option.fit] })
  const setup = knownFacts(option.facts).find((fact) => fact.label === 'Setup')
  if (budgetProvided && typeof option.within_budget === 'boolean') rows.push({ label: 'Your budget', value: option.within_budget ? 'Fits your budget' : 'Over your budget' })
  else if (setup) rows.push({ label: 'Setup', value: setup.value })
  return rows
}

function ToolCard({ option, tool, budgetProvided, compare, highlight }) {
  const [open, setOpen] = useState(false)
  const recommended = optionChecked(option)
  const rows = cardRows(option, budgetProvided)
  const site = safeWebsite(option.service_url || tool?.url)
  const facts = knownFacts(option.facts)
  const hasDetails = Boolean(option.cost_note || (recommended && option.fit_note) || facts.length)

  return (
    <article className={`opt-card${highlight ? ' opt-card-best' : ''}`}>
      <div className="opt-card-top">
        <span className="opt-avatar" aria-hidden="true">{option.tool_name.slice(0, 1)}</span>
        {recommended && <span className="opt-badge opt-badge-ok">{BADGE.checked}</span>}
        <FavouriteButton toolId={option.tool_id} name={option.tool_name} />
      </div>
      <p className="opt-route">{ROUTE_LABELS[option.route] || 'Option'}</p>
      <h4>{option.tool_name}</h4>
      {tool?.summary && <p className="opt-summary">{tool.summary}</p>}
      {rows.length > 0 && (
        <dl className="opt-facts">
          {rows.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
        </dl>
      )}
      <div className="opt-actions">
        {compare}
        {hasDetails && <button type="button" className="opt-link" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? 'Hide details' : 'See details'}</button>}
        {site && <a className="opt-link" href={site} target="_blank" rel="noopener noreferrer">Visit website <span className="sr-only">(opens in a new tab)</span><span aria-hidden="true">↗</span></a>}
      </div>
      {open && (
        <div className="opt-details">
          {option.cost_note && <p><strong>About the price:</strong> {option.cost_note}</p>}
          {recommended && option.fit_note && <p><strong>Why it fits:</strong> {option.fit_note}</p>}
          {facts.length > 0 && (
            <ul>
              {facts.map((fact) => (
                <li key={fact.label}>
                  <span>{fact.label}</span>
                  <span>
                    {fact.value}{fact.inferred && !String(fact.value).includes('(estimate)') ? ' (estimate)' : ''}
                    {safeWebsite(fact.source_url) && <>. <a href={safeWebsite(fact.source_url)} target="_blank" rel="noopener noreferrer">Source{fact.checked ? `, checked ${fact.checked}` : ''}<span className="sr-only"> (opens in a new tab)</span></a></>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  )
}

// Questions are worded from what the backend left open. They make no claims.
function questionsFor(options, problemTitle, business) {
  return options.slice(0, 3).map((option) => {
    const list = []
    if (option.fit === 'unconfirmed') list.push(`Does ${option.tool_name} handle "${problemTitle.toLowerCase()}" for ${aOr(business)} ${business}?`)
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

export default function OptionsResults({ recommendation, toolsById, activeProblem, business, budgetProvided, compareProps, onAskPenny, onCompareThese }) {
  const groups = useMemo(() => {
    // Only a confident answer about a tool checked for this task is called recommended.
    // A checked winner never lends that label to the tools next to it.
    const confident = ['new_tool', 'add_on', 'no_new_tool'].includes(recommendation.outcome)
    const all = [
      ...recommendation.options.map((option) => ({ option, recommended: confident && optionChecked(option) })),
      ...recommendation.check_first.map((option) => ({ option, recommended: false })),
    ]
    const owned = all.filter(({ option }) => isOwned(option))
    const rest = all.filter(({ option }) => !isOwned(option))
    const best = rest.find(({ option, recommended }) => recommended && option.tool_id === recommendation.winner_tool_id)
    return {
      owned,
      best,
      others: rest.filter(({ option, recommended }) => recommended && option !== best?.option),
      more: rest.filter(({ recommended }) => !recommended),
    }
  }, [recommendation])

  const recommendedCount = (groups.best ? 1 : 0) + groups.others.length
  const browsing = recommendedCount === 0 && groups.owned.length === 0
  const businessName = business ? (business === business.toUpperCase() ? business : business.toLowerCase()) : 'business like yours'
  const questions = questionsFor([...groups.owned, ...groups.more].map(({ option }) => option).filter((option) => option.fit === 'unconfirmed' || option.added_monthly_usd === null || option.route === 'check_plan'), activeProblem?.title || 'this task', businessName)
  const questionText = questions.map((group) => [group.name, ...group.list.map((item) => `- ${item}`)].join('\n')).join('\n\n')

  const headline = browsing ? 'Tools to look at' : {
    no_new_tool: 'Good news: you may not need a new tool',
    add_on: 'A small add-on may be all you need',
    new_tool: "Here's what we recommend",
  }[recommendation.outcome] || "Here's what we found"
  const message = browsing ? `These tools work in this area. Their websites show which plan suits your ${businessName}.` : recommendation.message

  const card = ({ option }, highlight = false) => (
    <ToolCard key={option.tool_id} option={option} tool={toolsById[option.tool_id]} budgetProvided={budgetProvided} highlight={highlight}
      compare={<CompareToggle {...compareProps(option.tool_id)} />} />
  )

  return (
    <div className="opt-results">
      <div className="opt-summary-bar" aria-label="Summary">
        {recommendedCount > 0 && <span className="opt-pill"><strong>{recommendedCount}</strong> recommended</span>}
        {groups.owned.length > 0 && <span className="opt-pill"><strong>{groups.owned.length}</strong> you already pay for</span>}
        {groups.more.length > 0 && <span className="opt-pill"><strong>{groups.more.length}</strong> {browsing ? 'to look at' : 'more options'}</span>}
      </div>

      <div className="opt-answer" role="status">
        <h3>{headline}</h3>
        <p>{message}</p>
        {recommendation.tailoring_note && <p className="opt-muted">{recommendation.tailoring_note}</p>}
      </div>

      {groups.best && <section aria-labelledby="opt-best"><h4 className="opt-group" id="opt-best">Recommended</h4><div className="opt-grid">{card(groups.best, true)}</div></section>}
      {groups.others.length > 0 && <section aria-labelledby="opt-others"><h4 className="opt-group" id="opt-others">{groups.best ? 'Also recommended' : 'Recommended'}</h4><div className="opt-grid">{groups.others.map((item) => card(item))}</div></section>}
      {groups.owned.length > 0 && <section aria-labelledby="opt-owned"><h4 className="opt-group" id="opt-owned">You already pay for</h4><div className="opt-grid">{groups.owned.map((item) => card(item))}</div></section>}
      {groups.more.length > 0 && (
        <section aria-labelledby="opt-more">
          <h4 className="opt-group" id="opt-more">{browsing ? 'Tools to look at' : 'More options'}</h4>
          <ul className="tool-site-list">
            {groups.more.map(({ option }) => (
              <ToolWebsiteLink key={option.tool_id} toolId={option.tool_id} name={option.tool_name}
                url={option.service_url || toolsById[option.tool_id]?.url} summary={toolsById[option.tool_id]?.summary}
                compare={<CompareToggle {...compareProps(option.tool_id)} />} />
            ))}
          </ul>
        </section>
      )}

      <div className="opt-help-actions">
        <button type="button" className="opt-chip" onClick={() => onAskPenny({ problemIds: [activeProblem.id] })}>Ask Arkadio about these options</button>
        {groups.more.length > 1 && <button type="button" className="opt-chip" onClick={() => onCompareThese(groups.more.slice(0, 3).map(({ option }) => option.tool_id))}>Compare these {Math.min(3, groups.more.length)}</button>}
      </div>

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
