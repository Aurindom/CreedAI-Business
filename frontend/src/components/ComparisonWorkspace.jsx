import React, { useEffect, useState } from 'react'
import { catalogStatus, catalogChecked } from '../catalogStatus'
import { api } from '../api'
import PrivatePlans from './PrivatePlans'

const money = (value) => value === null ? 'Check vendor pricing' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value)

export default function ComparisonWorkspace({ tools, problems, profile, activeProblemId, baseline, onRemove, renderFact, auth }) {
  const [taskIds, setTaskIds] = useState(activeProblemId ? [activeProblemId] : [])
  const [assignments, setAssignments] = useState({})
  const [result, setResult] = useState(null)
  const [resultKey, setResultKey] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const profileKey = JSON.stringify(profile)
  useEffect(() => { setTaskIds(activeProblemId ? [activeProblemId] : []); setAssignments({}) }, [activeProblemId])
  useEffect(() => { setAssignments({}) }, [profileKey])
  const selection = { profile, problem_ids: taskIds, tool_ids: tools.map((tool) => tool.id), assignments: Object.fromEntries(Object.entries(assignments).filter(([task, tool]) => taskIds.includes(task) && tools.some((item) => item.id === tool))) }
  const selectionKey = JSON.stringify(selection)

  useEffect(() => {
    let current = true
    const chosen = JSON.parse(selectionKey)
    setResult(null); setError('')
    if (!chosen.tool_ids.length || !chosen.problem_ids.length) { setLoading(false); return }
    setLoading(true)
    api.compare(chosen.profile, chosen.problem_ids, chosen.tool_ids, chosen.assignments)
      .then((data) => { if (current) { setResult(data); setResultKey(selectionKey) } })
      .catch((failure) => { if (current) setError(failure.message) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [selectionKey])

  function toggleTask(id) {
    setAssignments({})
    setTaskIds((current) => current.includes(id) ? current.filter((task) => task !== id) : current.length < 5 ? [...current, id] : current)
  }
  const compared = Object.fromEntries((result?.tools || []).map((tool) => [tool.tool_id, tool]))
  return <div className="comparison-workspace">
    <div className="comparison-task-picker"><h3>What are you comparing them for?</h3><p>Choose up to five tasks for plan-aware costs and fit. Leave these blank to compare general facts.</p><div className="chip-list">{problems.map((problem) => <button className={`chip ${taskIds.includes(problem.id) ? 'chip-on' : ''}`} type="button" key={problem.id} aria-pressed={taskIds.includes(problem.id)} disabled={taskIds.length >= 5 && !taskIds.includes(problem.id)} onClick={() => toggleTask(problem.id)}>{problem.title}</button>)}</div></div>
    {loading && <p role="status" className="preview-notice">Checking tasks, plans, and costs...</p>}
    {error && <p role="alert" className="error-banner">Comparison unavailable. {error}</p>}
    {!tools.length ? <div className="comparison-empty"><strong>Choose tools to compare</strong><p>Add up to three platforms. Your selected tasks stay here.</p></div> : <div className="comparison-wrap"><table className="comparison-table"><thead><tr><th>What to check</th>{tools.map((tool) => <th key={tool.id}>{tool.name}<button type="button" onClick={() => onRemove(tool.id)} aria-label={`Remove ${tool.name}`}>&#215;</button></th>)}</tr></thead><tbody>
      <tr><td>Your subscription</td>{tools.map((tool) => <td key={tool.id}>{tool.id === baseline ? <span className="current-subscription">Your current subscription</span> : profile.owned.some((item) => item.tool_id === tool.id) ? 'You also use this' : 'Alternative'}{profile.owned.find((item) => item.tool_id === tool.id)?.plan && <small className="evidence-date">Your plan: {profile.owned.find((item) => item.tool_id === tool.id).plan}</small>}</td>)}</tr>
      {taskIds.length > 0 && <tr><td>Role in this selection</td>{tools.map((tool) => <td key={tool.id}>{compared[tool.id]?.role_note || (loading ? 'Checking...' : 'Choose valid tasks above')}</td>)}</tr>}
      {(result?.tasks || []).map((task) => <tr key={task.problem_id}><td>{task.title}</td>{tools.map((tool) => { const fit = compared[tool.id]?.tasks.find((item) => item.problem_id === task.problem_id); return <td key={tool.id}>{fit ? <><span className={`coverage-label coverage-${fit.coverage}`}>{fit.coverage === 'confirmed' ? 'Confirmed task fit' : fit.coverage === 'possible' ? 'Needs checking' : 'Set aside'}</span><p>{fit.reason}</p><strong>{money(fit.added_monthly_usd)}{fit.added_monthly_usd !== null ? ' / mo added' : ''}</strong><p>{fit.cost_note}</p></> : 'This tool does not list this task'}</td> })}</tr>)}
      {['Entry price', 'Setup', 'Privacy', 'Support'].map((label) => <tr key={label}><td>{label}</td>{tools.map((tool) => <td key={tool.id}>{renderFact(tool, label)}</td>)}</tr>)}
      <tr><td>Catalog status</td>{tools.map((tool) => <td key={tool.id}><span className={`tool-status ${catalogChecked(tool) ? 'verified' : 'pending'}`}>{catalogStatus(tool)}</span></td>)}</tr>
    </tbody></table></div>}
    {!taskIds.length && tools.length > 0 && <p className="comparison-footnote">These are alternatives, not a combined subscription bill. Entry prices may differ from your plan or the price for a specific task.</p>}
    {result && <>
      <div className="comparison-assignments"><h3>Choose one tool for each task</h3>{result.tasks.map((task) => <div className="task-assignment" key={task.problem_id}><label className="field"><span>{task.title}</span>{task.candidate_ids.length > 0 ? <select aria-label={`Tool for ${task.title}`} value={task.assigned_to || ''} onChange={(event) => setAssignments((current) => { const next = { ...current }; if (event.target.value) next[task.problem_id] = event.target.value; else delete next[task.problem_id]; return next })}><option value="">Choose a tool</option>{task.candidate_ids.map((id) => <option value={id} key={id}>{tools.find((tool) => tool.id === id)?.name || id}</option>)}</select> : <span className="coverage-label coverage-excluded">No selected tool covers this task</span>}</label><p>{task.suggested && <strong>Suggested, not confirmed by you. </strong>}{task.note}</p></div>)}</div>
      <div className="stack-summary"><h3>{result.stack?.ready ? 'Confirmed added monthly cost' : 'Your selection needs checking'}</h3><p>{result.stack_note}</p>{result.stack && <><dl>{result.stack.lines.map((line) => <div key={line.tool_id}><dt>{line.tool_name}<small>{line.note}</small></dt><dd>{money(line.monthly_usd)}{line.monthly_usd !== null ? ' / mo' : ''}</dd></div>)}</dl><div className="stack-total"><span>{result.stack.ready ? 'Added monthly total' : 'Conditional added monthly total'}</span><strong>{money(result.stack.total_monthly_usd)}{result.stack.total_monthly_usd !== null ? ' / mo' : ''}</strong></div>{result.stack.total_monthly_usd === null && <p>Priced parts: {money(result.stack.known_monthly_usd)} / mo, plus unconfirmed costs.</p>}{result.stack.within_budget !== null && <p className={`budget-status budget-${result.stack.within_budget ? 'within' : 'over'}`}>{result.stack.within_budget ? 'Within your added monthly budget' : 'Over your added monthly budget'}</p>}<ul>{result.stack.assumptions.map((note) => <li key={note}>{note}</li>)}</ul></>}</div>
      {result.overlaps.length > 0 && <details className="set-aside"><summary>Possible overlap between these tools</summary><ul>{result.overlaps.map((note) => <li key={note}>{note}</li>)}</ul></details>}
      {result.connections.length > 0 && <details className="set-aside"><summary>Connections to verify</summary>{result.connections.map((connection, index) => <div key={index}><p><strong>{connection.state === 'listed' ? 'Vendor-listed connection' : 'Connection unverified'}</strong>: {connection.note}</p>{connection.sources.map((url) => <a className="evidence-link" key={url} href={url} target="_blank" rel="noopener noreferrer">Vendor source</a>)}</div>)}</details>}
      {taskIds.length > 1 && <details className="set-aside"><summary>Tools listing all chosen tasks</summary><p>{result.all_in_one_note}</p>{result.all_in_one.map((tool) => <p key={tool.tool_id}><strong>{tool.tool_name}</strong>: {tool.coverage === 'confirmed' ? 'Confirmed task coverage' : 'Needs checking'}. {money(tool.monthly_usd)}{tool.monthly_usd !== null ? ' / mo' : ''}. {tool.note}</p>)}</details>}
    </>}
    <PrivatePlans auth={auth} selection={selection} canSave={Boolean(result?.stack) && resultKey === selectionKey && !loading && !error} />
  </div>
}
