import React from 'react'
import A2UIQuestion, { readQuestionSurface } from './A2UIQuestion'
import ChatResult, { safeUrl } from './ChatResult'
import PennyAvatar from './PennyAvatar'

const CATALOG = 'https://mainstreet.ai/catalogs/penny/v1'

export function readRecommendationSurface(protocol) {
  if (!Array.isArray(protocol) || protocol.length !== 2) return null
  const [create, update] = protocol
  const surface = create?.createSurface
  const patch = update?.updateComponents
  if (create?.version !== 'v0.9' || update?.version !== 'v0.9' || surface?.catalogId !== CATALOG) return null
  if (typeof surface.surfaceId !== 'string' || !surface.surfaceId.startsWith('penny-recommendation-') || surface.surfaceId.length > 100) return null
  if (patch?.surfaceId !== surface.surfaceId || !Array.isArray(patch.components) || patch.components.length !== 1) return null
  const component = patch.components[0]
  if (component?.id !== 'root' || component.component !== 'PennyRecommendation') return null
  const recommendation = component.recommendation
  if (!recommendation || typeof recommendation !== 'object' || typeof recommendation.message !== 'string') return null
  if (!Array.isArray(recommendation.options) || !Array.isArray(recommendation.check_first) || !Array.isArray(recommendation.set_aside)) return null
  if (![...recommendation.options, ...recommendation.check_first].every((option) =>
    option && typeof option.tool_id === 'string' && Array.isArray(option.facts))) return null
  if (typeof component.problemTitle !== 'string' || component.problemTitle.length > 200) return null
  if (component.taskPurpose !== undefined && (typeof component.taskPurpose !== 'string' || component.taskPurpose.length > 200)) return null
  if (!component.statuses || typeof component.statuses !== 'object' || Array.isArray(component.statuses)) return null
  return component
}

export function readSimpleSurface(protocol, surfaceType, componentName) {
  if (!Array.isArray(protocol) || protocol.length !== 2) return null
  const [create, update] = protocol
  const surface = create?.createSurface
  const patch = update?.updateComponents
  if (create?.version !== 'v0.9' || update?.version !== 'v0.9' || surface?.catalogId !== CATALOG) return null
  if (typeof surface.surfaceId !== 'string' || !surface.surfaceId.startsWith(`penny-${surfaceType}-`) || surface.surfaceId.length > 100) return null
  if (patch?.surfaceId !== surface.surfaceId || !Array.isArray(patch.components) || patch.components.length !== 1) return null
  const component = patch.components[0]
  if (component?.id !== 'root' || component.component !== componentName) return null
  if (surfaceType === 'text') return typeof component.text === 'string' && component.text.length > 0 && component.text.length <= 2000 ? component : null
  if (surfaceType === 'table') {
    const limits = { tool_id: 100, tool: 200, plan: 400, entry_price: 200, added_cost: 200, notes: 1000 }
    if (typeof component.title !== 'string' || component.title.length > 200 || !['price', 'plan', 'cost', 'fit'].includes(component.criterion)) return null
    if (!Array.isArray(component.rows) || component.rows.length < 1 || component.rows.length > 6) return null
    if (!component.rows.every(row => row && Object.entries(limits).every(([key, maximum]) => typeof row[key] === 'string' && row[key].length <= maximum)
      && Array.isArray(row.sources) && row.sources.length <= 6 && row.sources.every(source => typeof source?.url === 'string' && safeUrl(source.url) && typeof source.checked === 'string' && source.checked.length <= 30))) return null
    return component
  }
  if (!Array.isArray(component.items) || component.items.length > 6) return null
  if (!component.items.every((item) => item && typeof item.title === 'string' && typeof item.url === 'string' && safeUrl(item.url))) return null
  return component
}

export default function A2UISurface({ protocol, onSelect, onOther, busy, ruledOut, onPrint, serviceUrls }) {
  if (readQuestionSurface(protocol)) return <A2UIQuestion protocol={protocol} onSelect={onSelect} onOther={onOther} busy={busy} />
  const text = readSimpleSurface(protocol, 'text', 'PennyText')
  if (text) return <div className="msc-row"><span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} /></span><p>{text.text}</p></div>
  const table = readSimpleSurface(protocol, 'table', 'PennyComparisonTable')
  if (table) return <div className="msc-comparison-scroll" role="region" aria-label={table.title} tabIndex={0}>
    <table className="msc-comparison-table">
      <caption>{table.title} by {table.criterion}. Alternatives are considered separately.</caption>
      <thead><tr><th scope="col">Tool</th><th scope="col">Required plan</th><th scope="col">Entry price</th><th scope="col">Added monthly cost</th><th scope="col">Details and sources</th></tr></thead>
      <tbody>{table.rows.map(row => <tr key={row.tool_id}>
        <th scope="row">{row.tool}</th><td>{row.plan}</td><td>{row.entry_price}</td><td>{row.added_cost}</td>
        <td>{row.notes}{row.sources.length > 0 && <details><summary>Sources</summary><ul>{row.sources.map((source, index) => <li key={`${source.url}-${index}`}><a href={source.url} target="_blank" rel="noreferrer noopener">Vendor source</a> · checked {source.checked}</li>)}</ul></details>}</td>
      </tr>)}</tbody>
    </table>
  </div>
  const sources = readSimpleSurface(protocol, 'sources', 'PennySources')
  if (sources) return <ul className="msc-sources">{sources.items.map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer noopener">{item.title}</a>{item.checked ? `, checked ${item.checked}` : ''}</li>)}</ul>
  const result = readRecommendationSurface(protocol)
  if (result) return <ChatResult
    recommendation={result.recommendation}
    problemTitle={result.problemTitle}
    taskPurpose={result.taskPurpose}
    statuses={result.statuses}
    serviceUrls={serviceUrls}
    ruledOut={ruledOut}
    onPrint={() => onPrint({ recommendation: result.recommendation, problemTitle: result.problemTitle, statuses: result.statuses })}
  />
  return <div className="msc-error" role="alert">Arkadio could not show this result. Please ask again.</div>
}
