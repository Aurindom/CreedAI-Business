import React, { useEffect, useState } from 'react'
import { api } from '../api'
import OptionsResults from './OptionsResults'

// Several problems at once. The backend picks each tool and adds up the cost (/api/compare);
// this component only lays the answers side by side.

const CONFIRMED = ['new_tool', 'add_on', 'no_new_tool']

function money(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: amount % 1 ? 2 : 0 }).format(amount)
}

function costOf(option) {
  if (!option) return ''
  if (option.added_monthly_usd === null || option.added_monthly_usd === undefined) return ''
  if (option.added_monthly_usd === 0) return option.fit === 'you_use_it' || option.route === 'already_have' ? 'Included in what you pay' : 'Free plan'
  return `${option.price_estimated ? 'About ' : ''}${money(option.added_monthly_usd)} a month${option.price_estimated ? ' (estimate)' : ''}`
}

export default function MultiPlan({ problemIds, problems, profile, toolsById, business, budgetProvided, categories, compareProps, onChooseProblem, onAskPenny, onCompareThese }) {
  const [state, setState] = useState({ loading: true, error: '', results: [], comparison: null })
  const profileKey = JSON.stringify(profile)
  const idsKey = problemIds.join('|')

  useEffect(() => {
    let active = true
    setState({ loading: true, error: '', results: [], comparison: null })
    Promise.all(problemIds.map((id) => api.recommend(profile, id).then((recommendation) => ({ id, recommendation }))))
      .then(async (results) => {
        const winners = [...new Set(results
          .filter(({ recommendation }) => CONFIRMED.includes(recommendation.outcome) && recommendation.winner_tool_id)
          .map(({ recommendation }) => recommendation.winner_tool_id))]
        let comparison = null
        if (winners.length) {
          try {
            comparison = await api.compare(profile, problemIds, winners.slice(0, 3))
          } catch {
            comparison = null
          }
        }
        if (active) setState({ loading: false, error: '', results, comparison })
      })
      .catch(() => { if (active) setState({ loading: false, error: "We couldn't load your options. Try again in a moment.", results: [], comparison: null }) })
    return () => { active = false }
  }, [idsKey, profileKey])

  if (state.loading) return <div className="loading-state" role="status"><span className="loading-dot" />Finding options for {problemIds.length} problems...</div>
  if (state.error) return <div className="error-banner" role="alert"><strong>Something went wrong.</strong> {state.error}</div>

  const titleOf = (id) => problems.find((problem) => problem.id === id)?.title || 'This problem'
  const rows = state.results.map(({ id, recommendation }) => {
    const confirmed = CONFIRMED.includes(recommendation.outcome) && recommendation.winner_tool_id
    const winner = confirmed ? [...recommendation.options, ...recommendation.check_first].find((option) => option.tool_id === recommendation.winner_tool_id) : null
    return { id, recommendation, winner }
  })
  const winners = [...new Set(rows.filter((row) => row.winner).map((row) => row.winner.tool_id))]
  const stack = state.comparison?.stack
  const sharedTool = rows.length > winners.length && winners.length > 0

  let total = ''
  if (stack && stack.total_monthly_usd !== null && stack.total_monthly_usd !== undefined) total = `${money(stack.total_monthly_usd)} a month for the confirmed tools`
  else if (stack) total = `${money(stack.known_monthly_usd)} a month known so far. ${stack.unknown_cost_tools.length ? `${stack.unknown_cost_tools.join(', ')} still needs a price.` : ''}`

  return (
    <div className="opt-results">
      <section className="plan-summary" aria-labelledby="plan-summary-title">
        <p className="plan-kicker">YOUR PLAN</p>
        <h3 id="plan-summary-title">{winners.length ? `Here's a plan for your ${rows.length} problems` : `We couldn't confirm tools for these ${rows.length} problems yet`}</h3>
        <ul className="plan-rows">
          {rows.map((row) => (
            <li key={row.id}>
              <span className="plan-problem">{titleOf(row.id)}</span>
              {row.winner
                ? <span className="plan-tool"><strong>{row.winner.tool_name}</strong><small>{costOf(row.winner)}</small></span>
                : <span className="plan-tool plan-tool-none"><strong>No confirmed tool yet</strong><small>See the options below</small></span>}
            </li>
          ))}
        </ul>
        {total && <p className="plan-total"><strong>Total:</strong> {total}</p>}
        {sharedTool && <p className="plan-note">One tool covers more than one of your problems, so you'd only pay for it once.</p>}
        {state.comparison?.overlaps?.length > 0 && <p className="plan-note">{state.comparison.overlaps.join(' ')}</p>}
        {stack?.assumptions?.length > 0 && <details className="plan-assumptions"><summary>What this total includes</summary><ul>{stack.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></details>}
        <div className="opt-help-actions">
          {winners.length > 0 && <button type="button" className="opt-chip" onClick={() => onCompareThese(winners.slice(0, 3))}>Compare these tools</button>}
          <button type="button" className="opt-chip" onClick={() => onAskPenny({ problemIds })}>Ask Penny about this plan</button>
        </div>
      </section>

      {rows.map((row, index) => (
        <details className="plan-problem-section" key={row.id} open={index === 0}>
          <summary>
            <span>{titleOf(row.id)}</span>
            <small>{row.winner ? `Best match: ${row.winner.tool_name}` : 'Worth checking'}</small>
          </summary>
          <OptionsResults
            recommendation={row.recommendation}
            toolsById={toolsById}
            activeProblem={problems.find((problem) => problem.id === row.id)}
            business={business}
            budgetProvided={budgetProvided}
            profile={profile}
            problems={problems}
            categories={categories}
            compareProps={compareProps}
            onChooseProblem={onChooseProblem}
            onAskPenny={onAskPenny}
            onCompareThese={onCompareThese}
            showRelated={false}
          />
        </details>
      ))}
    </div>
  )
}
