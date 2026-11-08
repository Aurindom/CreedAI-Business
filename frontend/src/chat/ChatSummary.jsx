import React from 'react'
import { createPortal } from 'react-dom'
import { costText, HEADLINES, ROUTE_LABELS, safeUrl, serviceUrl, statusLabel } from './ChatResult'
import { vendorQuestions } from './vendorQuestions'

function SummaryOption({ option, status }) {
  return (
    <div className="msc-print-option">
      <h3>{option.tool_name}</h3>
      <p>{ROUTE_LABELS[option.route] || 'An option to consider'} · {costText(option)} · {statusLabel(status)}</p>
      {serviceUrl(option) && <p>Service: {serviceUrl(option)}</p>}
      <ul>
        {option.facts.map((fact) => {
          const url = safeUrl(fact.source_url)
          return <li key={fact.label}>{fact.label}: {fact.known ? fact.value : 'Confirm with the service'}{(url || (!fact.known && serviceUrl(option))) ? ` (${url || serviceUrl(option)}${fact.checked ? `, checked ${fact.checked}` : ''})` : ''}</li>
        })}
      </ul>
    </div>
  )
}

function ChatSummary({ data }) {
  if (!data) return null
  const { recommendation, problemTitle, statuses } = data
  const groups = vendorQuestions(recommendation)

  return createPortal(
    <section className="msc-print">
      <h1>Main Street AI summary</h1>
      <p className="msc-print-meta">{problemTitle} · {new Date().toLocaleDateString()}</p>
      <h2>{HEADLINES[recommendation.outcome] || 'Here is what I found'}</h2>
      <p>{recommendation.message}</p>
      {recommendation.tailoring_note && <p>{recommendation.tailoring_note}</p>}
      {recommendation.options.map((option) => <SummaryOption option={option} status={statuses[option.tool_id]} key={option.tool_id} />)}
      {recommendation.check_first.length > 0 && <>
        <h2>Check these first</h2>
        {recommendation.check_first.map((option) => <SummaryOption option={option} status={statuses[option.tool_id]} key={option.tool_id} />)}
      </>}
      {recommendation.set_aside.length > 0 && <>
        <h2>Why not the others?</h2>
        <ul>{recommendation.set_aside.map((item) => <li key={item.tool_id}>{item.tool_name}: {item.reason}</li>)}</ul>
      </>}
      {groups.length > 0 && <>
        <h2>Questions to ask the vendor</h2>
        {groups.map((group) => (
          <div key={group.toolId}>
            <h3>{group.toolName}</h3>
            <ul>{group.questions.map((question) => <li key={question}>{question}</li>)}</ul>
          </div>
        ))}
      </>}
    </section>,
    document.body,
  )
}

export default ChatSummary
