import React, { useState } from 'react'
import { isSingleOffering, planChoices, PLAN_LABEL_MAX, PLAN_UNKNOWN } from '../api'

export default function QuickCompare({ tools, baseline, selected, plans, onBaseline, onPlan, onToggle, onBack }) {
  const [search, setSearch] = useState('')
  const current = tools.find((tool) => tool.id === baseline)
  const choices = planChoices(current)
  const query = search.trim().toLowerCase()
  const alternatives = tools.filter((tool) => tool.id !== baseline && (!query || `${tool.name} ${tool.summary}`.toLowerCase().includes(query)))
  const full = selected.length >= 3
  return <section className="quick-workspace" id="quick-compare" aria-labelledby="quick-compare-title">
    <div className="quick-workspace-head"><div><p className="section-kicker">STRAIGHT TO THE COMPARISON</p><h1 id="quick-compare-title">Keep it. Switch it.<br /><em>See your options.</em></h1><p>Already paying for a tool? Put it beside alternatives and compare the evidence.</p></div><button className="quick-back" type="button" onClick={onBack}>Back to the guided journey</button></div>
    <div className="quick-intake"><label className="field"><span>1. Your current subscription <small>optional</small></span><select value={baseline} onChange={(event) => onBaseline(event.target.value)}><option value="">Choose the tool you already use</option>{tools.map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}</select><small>Not listed? You can still compare catalog tools below.</small></label>
      {current && !isSingleOffering(current) && <label className="field"><span>Your {current.name} plan <small>optional</small></span>{choices.length ? <select value={plans[baseline] ?? PLAN_UNKNOWN} onChange={(event) => onPlan(baseline, event.target.value)}><option value={PLAN_UNKNOWN}>I do not know</option>{choices.map((plan) => <option key={plan} value={plan}>{plan}</option>)}</select> : <><input value={plans[baseline] ?? ''} maxLength={PLAN_LABEL_MAX} placeholder="Plan name, if you know it" onChange={(event) => onPlan(baseline, event.target.value)} /><small>Not checked by us. A custom plan needs vendor confirmation.</small></>}</label>}
    </div>
    <div className="quick-search-heading"><div><h2>2. Add platforms to compare</h2><p>Search by tool name or what it does. Compare up to three at once.</p></div><label className="quick-search"><span className="sr-only">Search comparison tools</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tools, scheduling, bookkeeping..." /></label></div>
    <div className="quick-shortlist" aria-live="polite"><span>{selected.length} / 3 selected</span>{selected.map((id) => <button type="button" key={id} onClick={() => onToggle(id)} aria-label={`Remove ${tools.find((tool) => tool.id === id)?.name} from comparison`}>{tools.find((tool) => tool.id === id)?.name}{id === baseline ? ' (current)' : ''}<span aria-hidden="true">&#215;</span></button>)}{full && <small>Remove a tool to add another.</small>}</div>
    <div className="quick-tool-list">{alternatives.map((tool) => {
      const added = selected.includes(tool.id)
      return <article className={`quick-tool${added ? ' quick-tool-added' : ''}`} key={tool.id}><span className="tool-avatar" aria-hidden="true">{tool.name.slice(0, 1)}</span><div className="quick-tool-copy"><h3>{tool.name}</h3><p>{tool.summary}</p><span className={`tool-status ${tool.status === 'verified' ? 'verified' : 'pending'}`}>{tool.status === 'verified' ? 'Source checked' : 'Pending review'}</span></div><button type="button" aria-pressed={added} disabled={!added && full} onClick={() => onToggle(tool.id)}>{added ? 'Remove' : 'Compare +'}</button></article>
    })}</div>
    {!alternatives.length && <p className="quick-no-results" role="status">No catalog tools match that search. Try another name or task.</p>}
    <a className="quick-results-link" href="#compare">See side-by-side comparison <span aria-hidden="true">&#8595;</span></a>
  </section>
}
