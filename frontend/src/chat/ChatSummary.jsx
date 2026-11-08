import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { costText, HEADLINES, ROUTE_LABELS, serviceUrl, statusLabel } from './ChatResult'

function SummaryOption({ option, status, fallbackUrl }) {
  const url = serviceUrl(option, fallbackUrl)
  return (
    <div className="msc-print-option">
      <h3>{option.tool_name}</h3>
      <p>{ROUTE_LABELS[option.route] || 'An option to consider'} · {costText(option)} · {statusLabel(status)}</p>
      <p>{option.cost_note}</p>
      <p>{option.fit_note}</p>
      {url && <p><a href={url} target="_blank" rel="noreferrer noopener">{url}</a></p>}
    </div>
  )
}

function SummaryPreview({ data, onClose, onPrint, serviceUrls = {} }) {
  const closeRef = useRef(null)
  useEffect(() => {
    const previousFocus = document.activeElement
    closeRef.current?.focus()
    return () => previousFocus?.focus?.()
  }, [])
  const { recommendation, problemTitle, statuses = {} } = data
  const primary = recommendation.options.length ? recommendation.options : recommendation.check_first
  const shortlist = primary.slice(0, 3)
  const remaining = recommendation.options.length + recommendation.check_first.length - shortlist.length

  function onKeyDown(event) {
    if (event.key === 'Escape') { event.stopPropagation(); onClose() }
    if (event.key === 'Tab') {
      const controls = [...event.currentTarget.querySelectorAll('button, a[href]')]
      const first = controls[0], last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
  }

  return createPortal(
    <div className="msc-summary-overlay" role="dialog" aria-modal="true" aria-labelledby="penny-summary-title" onKeyDown={onKeyDown}>
    <div className="msc-summary-preview">
      <div className="msc-summary-controls">
        <p>Summary preview. Use Print / Save PDF, or your browser’s Print menu if the dialog does not open.</p>
        <div><button type="button" onClick={onPrint}>Print / Save PDF</button><button type="button" ref={closeRef} onClick={onClose}>Close summary</button></div>
      </div>
    <section className="msc-print">
      <h1 id="penny-summary-title">Main Street AI summary</h1>
      <p className="msc-print-meta">{problemTitle} · {new Date().toLocaleDateString()}</p>
      <h2>{HEADLINES[recommendation.outcome] || 'Here is what I found'}</h2>
      <p>{recommendation.message}</p>
      {recommendation.tailoring_note && <p>{recommendation.tailoring_note}</p>}
      {recommendation.budget_note && <p>{recommendation.budget_note}</p>}
      {shortlist.length > 1 && <p>These are alternatives. Choose one that covers your need.</p>}
      {shortlist.map(option => <SummaryOption key={option.tool_id} option={option} status={statuses[option.tool_id]} fallbackUrl={serviceUrls[option.tool_id]} />)}
      {remaining > 0 && <p>{remaining} more alternatives and detailed sources are available in your chat.</p>}
      <p className="msc-print-footer">Confirm the required plan, current pricing, business fit and data handling with the service before subscribing.</p>
    </section>
    </div>
    </div>,
    document.body,
  )
}

export default function ChatSummary(props) {
  return props.data ? <SummaryPreview {...props} /> : null
}
