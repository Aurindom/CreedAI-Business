import React, { useState } from 'react'
import { vendorQuestions, vendorQuestionsText } from './vendorQuestions'
import { FavouriteButton } from '../favourites/Favourites'

export const HEADLINES = {
  no_new_tool: 'You may not need a new tool',
  add_on: 'A small add-on may be enough',
  new_tool: "Here's what fits",
  verify_with_vendor: 'Check these before you decide',
  no_match: 'Nothing we checked fits yet',
}

export const ROUTE_LABELS = {
  already_have: 'You already have this',
  check_plan: 'Your plan may include this',
  native_add_on: 'Add-on to a tool you use',
  plan_upgrade: 'Needs a higher plan',
  compatible_tool: 'Connects to a tool you use',
  separate_tool: 'A new tool',
  switch: 'Overlaps a tool you use',
}

export function statusLabel(status) {
  if (status === 'verified') return 'Source checked'
  if (status === 'pending_review') return 'Pending review'
  return 'Check service details'
}

export function costText(option) {
  if (option.added_monthly_usd == null) return 'Check current pricing'
  return `$${Number(option.added_monthly_usd).toLocaleString()} more each month`
}

export function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : null
}

export function serviceUrl(option, fallback) {
  return safeUrl(option.service_url) || safeUrl(fallback) || option.facts.map((fact) => safeUrl(fact.source_url)).find(Boolean) || null
}

function FactRow({ fact, serviceLink }) {
  const url = safeUrl(fact.source_url) || (!fact.known ? serviceLink : null)
  return (
    <li>
      <span className="msc-fact-label">{fact.label}</span>
      <span>
        {fact.known ? fact.value : 'Confirm with the service'}
        {fact.note && <span className="msc-fact-note">{fact.note}</span>}
        {url && <> · <a href={url} target="_blank" rel="noreferrer noopener">{fact.known ? 'Source' : 'View service details'}{fact.checked ? `, checked ${fact.checked}` : ''}</a></>}
      </span>
    </li>
  )
}

function OptionCard({ option, status, ruledOut, taskPurpose, fallbackUrl }) {
  const url = serviceUrl(option, fallbackUrl)
  return (
    <article className="msc-option">
      <div className="msc-option-top">
        <h4>{option.tool_name}</h4>
        <span className={`msc-badge${status === 'verified' ? '' : ' msc-badge-check'}`}>{statusLabel(status)}</span>
        <FavouriteButton toolId={option.tool_id} name={option.tool_name} />
      </div>
      <p className="msc-route">{ROUTE_LABELS[option.route] || 'An option to consider'}</p>
      {ruledOut && <p className="msc-ruled-out">You told Penny you don't want this one</p>}
      <p className="msc-cost">{costText(option)}</p>
      <p className="msc-note">{option.cost_note}</p>
      <p className="msc-note">{option.fit_note}</p>
      {taskPurpose && <p className="msc-note"><strong>For this need:</strong> {taskPurpose}</p>}
      {url && <a className="msc-service-link" href={url} target="_blank" rel="noreferrer noopener">Visit {option.tool_name} <span aria-hidden="true">↗</span></a>}
      <details className="msc-details"><summary>Details and sources</summary>
        <ul className="msc-facts">{option.facts.map((fact) => <FactRow fact={fact} serviceLink={url} key={fact.label} />)}</ul>
      </details>
    </article>
  )
}

function CopyQuestions({ groups }) {
  const [state, setState] = useState('')

  async function copy() {
    try {
      await navigator.clipboard.writeText(vendorQuestionsText(groups))
      setState('Copied')
    } catch {
      setState("Couldn't copy. Select the questions above instead.")
    }
  }

  return (
    <div className="msc-copy">
      <button type="button" className="msc-secondary" onClick={copy}>Copy questions</button>
      <span role="status">{state}</span>
    </div>
  )
}

function ChatResult({ recommendation, statuses, ruledOut = [], onPrint, problemTitle, taskPurpose, serviceUrls = {} }) {
  const groups = vendorQuestions(recommendation)
  const noNewTool = recommendation.outcome === 'no_new_tool'
  const main = recommendation.options.slice(0, 3)
  const possible = main.length ? [] : recommendation.check_first.slice(0, 3)
  const more = [...recommendation.options.slice(main.length), ...recommendation.check_first.slice(possible.length)]
  const renderOption = (option) => <OptionCard option={option} status={statuses[option.tool_id]} ruledOut={ruledOut.includes(option.tool_id)} taskPurpose={taskPurpose} fallbackUrl={serviceUrls[option.tool_id]} key={option.tool_id} />

  return (
    <div className="msc-result">
      <div className={`msc-answer${noNewTool ? ' msc-answer-win' : ''}`}>
        <h3>{!noNewTool && problemTitle && (main.length || possible.length) ? `Tools for: ${problemTitle}` : HEADLINES[recommendation.outcome] || 'Here is what I found'}</h3>
        {(main.length + possible.length > 1) && <p className="msc-note">These are alternatives. Start with one that covers your need.</p>}
        <p>{recommendation.message}</p>
        {recommendation.tailoring_note && <p className="msc-note">{recommendation.tailoring_note}</p>}
      </div>

      {main.map(renderOption)}

      {possible.length > 0 && (
        <section>
          <h4 className="msc-section">Check these first</h4>
          <p className="msc-note">We can't confirm these fit yet.</p>
          {possible.map(renderOption)}
        </section>
      )}

      {more.length > 0 && <details className="msc-details"><summary>More alternatives ({more.length})</summary>{more.map(renderOption)}</details>}

      {recommendation.set_aside.length > 0 && (
        <details className="msc-details">
          <summary>Why not the others?</summary>
          <ul>{recommendation.set_aside.map((item) => <li key={item.tool_id}><strong>{item.tool_name}:</strong> {item.reason}</li>)}</ul>
        </details>
      )}

      {groups.length > 0 && (
        <details className="msc-details">
          <summary>Questions to ask the vendor</summary>
          {groups.map((group) => (
            <div key={group.toolId}>
              <h5>{group.toolName}</h5>
              <ul>{group.questions.map((question) => <li key={question}>{question}</li>)}</ul>
            </div>
          ))}
          <CopyQuestions groups={groups} />
        </details>
      )}

      <button type="button" className="msc-secondary msc-print-button" onClick={onPrint}>Print a one-page summary</button>
    </div>
  )
}

export default ChatResult
