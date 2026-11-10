import React from 'react'

function PennyMemory({ memory, names, onRemove, signedIn = false }) {
  const label = (type, id) => names[type]?.[id] || id
  const items = [
    ...(!memory.business_forgotten && (memory.business_description || memory.trade) ? [{ key: 'trade', text: `Business: ${memory.business_description || label('trades', memory.trade)}`, remove: { field: 'business' } }] : []),
    ...memory.owned.map((id) => ({ key: `owned-${id}`, text: `Uses ${label('tools', id)}${memory.plans?.[id] ? ` (${memory.plans[id]})` : ''}`, remove: { field: 'owned', id } })),
    ...memory.ruled_out.map((id) => ({ key: `out-${id}`, text: `Doesn't want ${label('tools', id)}`, remove: { field: 'ruled_out', id } })),
    ...(memory.budget_monthly_usd === null || memory.budget_monthly_usd === undefined ? [] : [{ key: 'budget', text: `Budget: $${memory.budget_monthly_usd}/mo`, remove: { field: 'budget_monthly_usd' } }]),
  ]
  if (!items.length) return null

  return (
    <details className="msc-memory">
      <summary>
        <span>Business context</span>
        <small>{items.map((item) => item.text).join(', ')}</small>
      </summary>
      <ul className="msc-memory-list">
        {items.map((item) => (
          <li key={item.key}>
            <span>{item.text}</span>
            <button type="button" onClick={() => onRemove(item.remove)} aria-label={`Remove: ${item.text}`}>×</button>
          </li>
        ))}
      </ul>
      <p className="msc-memory-note">Tap × to remove context. {signedIn ? 'This conversation stays with your account for up to 30 days.' : 'Guest chat stays temporarily in this browser tab.'} Removing context does not delete earlier messages.</p>
    </details>
  )
}

export default PennyMemory
