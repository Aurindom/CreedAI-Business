import React from 'react'
import PennyAvatar from './PennyAvatar'

// This renderer accepts one versioned A2UI catalog component. The agent sends data,
// while the component and its click behavior stay in trusted application code.
const CATALOG = 'https://mainstreet.ai/catalogs/penny/v1'

export function readQuestionSurface(protocol) {
  if (!Array.isArray(protocol) || protocol.length !== 2) return null
  const [create, update] = protocol
  const surface = create?.createSurface
  const patch = update?.updateComponents
  if (create?.version !== 'v0.9' || update?.version !== 'v0.9' || surface?.catalogId !== CATALOG) return null
  if (typeof surface.surfaceId !== 'string' || !surface.surfaceId.startsWith('penny-question-') || surface.surfaceId.length > 100) return null
  if (patch?.surfaceId !== surface.surfaceId || !Array.isArray(patch.components) || patch.components.length !== 1) return null
  const component = patch.components[0]
  if (component?.id !== 'root' || component.component !== 'PennyQuestion') return null
  if (typeof component.question !== 'string' || !component.question || component.question.length > 200) return null
  if (!Array.isArray(component.choices) || component.choices.length < 2 || component.choices.length > 4) return null
  if (!component.choices.every((choice) => typeof choice === 'string' && choice.length > 0 && choice.length <= 80)) return null
  if (component.progress !== undefined && (typeof component.progress !== 'string' || component.progress.length > 30)) return null
  return component
}

export default function A2UIQuestion({ protocol, onSelect, busy }) {
  const question = readQuestionSurface(protocol)
  if (!question) return <div className="msc-error" role="alert">Penny could not show those choices. Please ask again.</div>
  return <div className="msc-row msc-clarify msc-a2ui-question">
    {question.progress && <span className="msc-progress">{question.progress}</span>}
    <div className="msc-clarify-question"><span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} /></span><p>{question.question}</p></div>
    <div className="msc-choices">{question.choices.map((choice) => <button type="button" key={choice} disabled={busy} onClick={() => onSelect(choice)}>{choice}</button>)}</div>
  </div>
}
