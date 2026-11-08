import React from 'react'

export default function ComparisonTray({ tools, onRemove, onClear, onView }) {
  if (!tools.length) return null
  return <aside className="comparison-tray" aria-label="Your comparison shortlist">
    <div className="comparison-tray-heading"><span><strong>{tools.length}</strong> of 3 selected</span><button type="button" onClick={onClear} aria-label="Clear comparison">Clear</button></div>
    <div className="comparison-tray-tools">{tools.map(tool => <button key={tool.id} type="button" onClick={() => onRemove(tool.id)} aria-label={`Remove ${tool.name} from comparison`}><span>{tool.name}</span><span aria-hidden="true">×</span></button>)}</div>
    <button className="comparison-tray-go" type="button" onClick={onView}>Compare {tools.length === 1 ? 'selection' : `${tools.length} tools`}<span aria-hidden="true">↗</span></button>
    <span className="sr-only" role="status">{tools.length} {tools.length === 1 ? 'tool' : 'tools'} selected for comparison</span>
  </aside>
}
