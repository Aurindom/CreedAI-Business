import React from 'react'

function PennyMemory({ memory, names, onRemove }) {
  const label = (type, id) => names[type]?.[id] || id
  const items = [
    ...(memory.trade ? [{ key: 'trade', text: `Business: ${label('trades', memory.trade)}`, remove: { field: 'trade' } }] : []),
    ...memory.owned.map((id) => ({ key: `owned-${id}`, text: `Uses ${label('tools', id)}`, remove: { field: 'owned', id } })),
    ...memory.ruled_out.map((id) => ({ key: `out-${id}`, text: `Doesn't want ${label('tools', id)}`, remove: { field: 'ruled_out', id } })),
    ...(memory.budget_monthly_usd === null || memory.budget_monthly_usd === undefined ? [] : [{ key: 'budget', text: `Budget: $${memory.budget_monthly_usd}/mo`, remove: { field: 'budget_monthly_usd' } }]),
  ]
  if (!items.length) return null

  return (
    <details className="msc-memory" open>
      <summary>What Penny remembers ({items.length})</summary>
      <ul className="msc-memory-list">
        {items.map((item) => (
          <li key={item.key}>
            <span>{item.text}</span>
            <button type="button" onClick={() => onRemove(item.remove)} aria-label={`Remove: ${item.text}`}>×</button>
          </li>
        ))}
      </ul>
      <p className="msc-memory-note">Tap × to remove anything. Penny forgets this when you close the tab.</p>
    </details>
  )
}

export default PennyMemory
