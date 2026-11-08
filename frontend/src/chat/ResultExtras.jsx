import React from 'react'
import { costText, safeUrl, statusLabel } from './ChatResult'

function Fact({ fact }) {
  const url = safeUrl(fact.source_url)
  return (
    <li>
      <span className="msc-fact-label">{fact.label}</span>
      <span>{fact.known ? fact.value : 'Unknown'}{fact.inferred ? ' (estimate)' : ''}{url && <> · <a href={url} target="_blank" rel="noreferrer noopener">Source{fact.checked ? `, checked ${fact.checked}` : ''}</a></>}</span>
    </li>
  )
}

export function AlternativesCard({ message }) {
  if (message.state === 'loading') return <div className="msc-loading">Checking other tools for this job...</div>
  if (message.state === 'none') {
    return <div className="msc-extra"><p className="msc-extra-title">No checked alternatives yet</p><p className="msc-note">We haven't checked another tool that does this job for you. You can build a custom assistant instead.</p></div>
  }
  const { comparison } = message
  const slot = comparison.tasks[0]
  return (
    <div className="msc-result">
      <div className="msc-answer"><h3>Other tools for this job</h3><p>{slot?.note || comparison.stack_note}</p><p className="msc-note">These are alternatives. You'd normally pick one, not buy them together.</p></div>
      {comparison.tools.map((tool) => {
        const fit = tool.tasks[0]
        return (
          <article className="msc-option" key={tool.tool_id}>
            <div className="msc-option-top">
              <h4>{tool.tool_name}</h4>
              <span className={`msc-badge${tool.status === 'verified' ? '' : ' msc-badge-check'}`}>{statusLabel(tool.status)}</span>
            </div>
            <p className="msc-route">{tool.role_note}</p>
            {fit && <p className="msc-cost">{costText({ added_monthly_usd: fit.added_monthly_usd ?? null, price_estimated: fit.price_estimated })}</p>}
            {fit?.cost_note && <p className="msc-note">{fit.cost_note}</p>}
            {fit?.reason && <p className="msc-note">{fit.reason}</p>}
            <ul className="msc-facts">{tool.facts.slice(0, 4).map((fact) => <Fact fact={fact} key={fact.label} />)}</ul>
          </article>
        )
      })}
      {comparison.overlaps.length > 0 && <p className="msc-note">{comparison.overlaps.join(' ')}</p>}
    </div>
  )
}

export function SavedPlanCard({ plan }) {
  const total = plan.stack?.total_monthly_usd
  return (
    <div className="msc-result">
      <div className="msc-answer msc-answer-win">
        <h3>{plan.status === 'checked' ? 'Plan saved and checked' : 'Plan saved as a draft'}</h3>
        <p>{total === null || total === undefined ? 'Some costs are unknown, so there is no total yet.' : `Known monthly cost: $${Number(total).toLocaleString()}`}</p>
        <p className="msc-note">Saved privately. Only this browser tab can open it, so closing the tab loses access to it.</p>
      </div>
      {plan.steps.map((step) => (
        <article className="msc-option" key={step.tool_id}>
          <div className="msc-option-top"><h4>{step.tool_name}</h4><span className={`msc-badge${step.status === 'verified' ? '' : ' msc-badge-check'}`}>{statusLabel(step.status)}</span></div>
          <p className="msc-cost">{costText({ added_monthly_usd: step.monthly_usd, price_estimated: plan.stack?.estimated?.includes(step.tool_name) })}</p>
          <p className="msc-note">{step.cost_note}</p>
          <ul className="msc-facts"><Fact fact={step.setup} /></ul>
          {step.to_try.length > 0 && <><h5 className="msc-list-title">Setup steps</h5><ol className="msc-steps">{step.to_try.map((item) => <li key={item}>{item}</li>)}</ol></>}
          {step.to_confirm.length > 0 && <><h5 className="msc-list-title">Check with the vendor</h5><ul className="msc-steps">{step.to_confirm.map((item) => <li key={item}>{item}</li>)}</ul></>}
        </article>
      ))}
      {plan.open_items?.length > 0 && (
        <div className="msc-extra">
          <p className="msc-extra-title">Check these before you rely on it</p>
          <ul className="msc-steps">{plan.open_items.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}
      {plan.gaps.length > 0 && <p className="msc-note">Still not covered: {plan.gaps.join(', ')}</p>}
      {plan.note && <p className="msc-note">{plan.note}</p>}
    </div>
  )
}
