const KEY = 'main-street-penny-session-v1'
const MAX_SAVED_MESSAGES = 40
const MAX_HISTORY = 12

function store() {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function newConversationId() {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `penny-${random}`
}

export function loadSession(emptyMemory, storage = store()) {
  try {
    const saved = JSON.parse(storage?.getItem(KEY) || 'null')
    if (typeof saved?.conversationId !== 'string' || !Array.isArray(saved.messages)) return null
    return {
      conversationId: saved.conversationId,
      messages: saved.messages.filter((message) => message?.id && message.kind && message.kind !== 'loading'),
      memory: {
        ...emptyMemory,
        ...saved.memory,
        owned: Array.isArray(saved.memory?.owned) ? saved.memory.owned : [],
        ruled_out: Array.isArray(saved.memory?.ruled_out) ? saved.memory.ruled_out : [],
        plans: saved.memory?.plans && typeof saved.memory.plans === 'object' ? saved.memory.plans : {},
      },
    }
  } catch {
    return null
  }
}

export function saveSession({ conversationId, messages, memory }, storage = store()) {
  try {
    const kept = messages.filter((message) => message.kind !== 'loading').slice(-MAX_SAVED_MESSAGES)
    storage?.setItem(KEY, JSON.stringify({ conversationId, messages: kept, memory }))
  } catch {
    // Saving is a convenience. The chat keeps working if the browser refuses it.
  }
}

export function clearSession(storage = store()) {
  try {
    storage?.removeItem(KEY)
  } catch {
    // Nothing to clear.
  }
}

export function historyFor(messages, { dropLastUser = false } = {}) {
  const items = messages.flatMap((message) => {
    if (message.kind === 'user') return [{ role: 'user', text: message.text }]
    if (message.kind === 'assistant' || message.kind === 'clarify') return [{ role: 'assistant', text: message.text }]
    if (message.kind === 'result') return [{ role: 'assistant', text: `I showed these results: ${message.recommendation.message}` }]
    if (message.kind === 'alternatives' && message.comparison) return [{ role: 'assistant', text: `I showed alternatives: ${message.comparison.tools.map((tool) => tool.tool_name).join(', ')}` }]
    if (message.kind === 'saved-plan') return [{ role: 'assistant', text: `I saved a plan with ${message.plan.steps.map((step) => step.tool_name).join(', ')}` }]
    if (message.kind === 'draft') return [{ role: 'assistant', text: `I drafted a custom assistant called ${message.draft.name}` }]
    return []
  }).map((item) => ({ ...item, text: item.text.slice(0, 2000) }))
    .filter((item) => item.text.trim())
  if (dropLastUser && items[items.length - 1]?.role === 'user') items.pop()
  return items.slice(-MAX_HISTORY)
}

export function greetingFor(conversationId) {
  const greetings = [
    "Hi, I'm Penny. What's eating up your time lately?",
    "Hi, I'm Penny. What's the most annoying part of your week?",
    "Hi, I'm Penny. Where does your business keep losing time or money?",
  ]
  const total = [...conversationId].reduce((sum, letter) => sum + letter.charCodeAt(0), 0)
  return greetings[total % greetings.length]
}
