import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api, newRequestId } from '../api'
import { navigate, signInHref } from '../auth/route'

const SESSION_KEY = 'mainstreet-private-plans-v1'
function restoreSession() { try { const session = JSON.parse(window.localStorage.getItem(SESSION_KEY) || 'null'); return session?.token && Date.parse(session.expires_at) > Date.now() ? session : null } catch { return null } }
const money = (value) => value === null || value === undefined ? '' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value)

export default function PrivatePlans({ selection, canSave, auth }) {
  if (!auth?.user || !auth?.session?.access_token) return <section className="private-plans"><h3>Your adoption plans</h3><p><a href={signInHref('/#compare')} onClick={(event) => { event.preventDefault(); navigate(signInHref('/#compare')) }}>Sign in</a> to save plans to your account. Browsing and comparison are available as a guest.</p></section>
  return <AccountPlans key={auth.user.id} selection={selection} canSave={canSave} auth={auth} />
}

function AccountPlans({ selection, canSave, auth }) {
  const session = useMemo(() => ({ token: auth.session.access_token }), [auth.session.access_token])
  const [legacy, setLegacy] = useState(restoreSession)
  const [summaries, setSummaries] = useState([])
  const [saved, setSaved] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [storageNotice, setStorageNotice] = useState('')
  const [savedKey, setSavedKey] = useState('')
  const confirming = useRef(false)
  const retry = useRef(null)
  const selectionKey = JSON.stringify(selection)
  useEffect(() => {
    let current = true
    if (session) api.plans(session.token).then((items) => { if (current) setSummaries(items) }).catch((failure) => { if (current) setError(failure.message) })
    return () => { current = false }
  }, [session])

  async function save() {
    if (!canSave || confirming.current || savedKey === selectionKey) return
    confirming.current = true; setBusy(true); setError('')
    const snapshot = JSON.parse(selectionKey)
    if (retry.current?.key !== selectionKey) retry.current = { key: selectionKey, id: newRequestId() }
    try {
      const activeSession = session
      const plan = await api.savePlan(activeSession.token, snapshot.profile, snapshot.problem_ids, snapshot.tool_ids, retry.current.id, snapshot.assignments)
      setSaved({ plan, changed: false, change_note: '' }); setSavedKey(selectionKey)
      setSummaries(await api.plans(activeSession.token))
    } catch (failure) { setError(failure.message) }
    finally { confirming.current = false; setBusy(false) }
  }
  async function openPlan(id) {
    if (!session || busy) return
    setBusy(true); setError('')
    try { setSaved(await api.plan(session.token, id)) }
    catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function refresh() {
    if (!session || !saved || busy) return
    setBusy(true); setError('')
    try { const plan = await api.refreshPlan(session.token, saved.plan.id); setSaved({ plan, changed: false, change_note: '' }); setSummaries(await api.plans(session.token)) }
    catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function importLegacy() {
    if (!legacy || busy) return
    setBusy(true); setError('')
    try {
      await api.claimLegacyPlans(session.token, legacy.token)
      try { window.localStorage.removeItem(SESSION_KEY) } catch { /* No silent ownership transfer. */ }
      setLegacy(null)
      setSummaries(await api.plans(session.token))
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <section className="private-plans" aria-labelledby="private-plans-title"><div className="private-plans-header"><div><p className="section-kicker">KEEP YOUR NEXT STEPS</p><h3 id="private-plans-title">Your private adoption plan</h3><p>Confirm your task assignments to save a plan. Plans belong to your signed-in account and remain saved when you sign out. Nothing is purchased or connected.</p></div><button className="plan-save-button" type="button" onClick={save} disabled={!canSave || busy || savedKey === selectionKey}>{busy ? 'Working...' : savedKey === selectionKey ? 'Plan saved' : 'Confirm and save plan'}</button></div>
    {legacy && <p>Older plans exist in this browser. Import only if they belong to you. <button type="button" onClick={importLegacy} disabled={busy}>Import my old plans</button></p>}
    {!canSave && <p className="comparison-footnote">Select tasks and tools, then choose one tool per task before saving.</p>}
    {storageNotice && <p className="task-error" role="status">{storageNotice}</p>}
    {error && <div role="alert" className="error-banner">{error}</div>}
    {summaries.length > 0 && <details className="set-aside"><summary>Saved to your account ({summaries.length})</summary><div className="saved-plan-list">{summaries.map((plan) => <button type="button" key={plan.id} disabled={busy} onClick={() => openPlan(plan.id)}>{plan.tool_names.join(' + ') || 'Plan with open tasks'}{plan.total_monthly_usd !== null && <span>{money(plan.total_monthly_usd)} / mo</span>}</button>)}</div></details>}
    {saved && <article className="saved-plan-view"><div className="saved-plan-heading"><h3>Saved plan</h3><span className={`coverage-label coverage-${saved.plan.status === 'checked' ? 'confirmed' : 'possible'}`}>{saved.plan.status === 'checked' ? 'Recommended plan' : saved.plan.status === 'legacy' ? 'Older plan, refresh for current prices' : 'Draft plan'}</span></div><p>{saved.plan.note}</p>{saved.plan.stack.total_monthly_usd !== null && <p>Saved estimate: <strong>{money(saved.plan.stack.total_monthly_usd)} / mo added</strong></p>}{saved.changed && <div className="answer-banner answer-check"><p>{saved.change_note}</p><p>Current catalog total: {money(saved.current_total_monthly_usd)}</p><button className="quick-back" type="button" onClick={refresh} disabled={busy}>Refresh with current catalog</button></div>}
      {saved.plan.open_items.length > 0 && <><h4>Before relying on this plan</h4><ul>{saved.plan.open_items.map((item) => <li key={item}>{item}</li>)}</ul></>}
      {saved.plan.steps.map((step) => <details className="set-aside" key={step.tool_id}><summary>{step.tool_name}{step.monthly_usd !== null ? `: ${money(step.monthly_usd)} / mo` : ''}</summary>{step.coverage === 'confirmed' && <p>Recommended for these tasks</p>}{step.monthly_usd !== null && step.cost_note && <p>{step.cost_note}</p>}<h4>Tasks and reasons</h4><ul>{step.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>{step.setup?.known && <p>Setup: {step.setup.value}. {step.setup.note}</p>}{step.setup?.known && step.setup.source_url && <a className="evidence-link" href={step.setup.source_url} target="_blank" rel="noopener noreferrer">Setup source</a>}{step.to_confirm.length > 0 && <><h4>Questions to ask</h4><ul>{step.to_confirm.map((item) => <li key={item}>{item}</li>)}</ul></>}<h4>Try before paying</h4><ul>{step.to_try.map((item) => <li key={item}>{item}</li>)}</ul></details>)}
      {saved.plan.gaps.length > 0 && <p>Still uncovered: {saved.plan.gaps.join('; ')}</p>}
    </article>}
  </section>
}
