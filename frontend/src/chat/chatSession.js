const KEY = 'main-street-penny-session-v2'
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
    if (message.kind === 'a2ui' && message.surface === 'sources') return []
    if (message.kind === 'assistant' || message.kind === 'clarify' || message.kind === 'a2ui') return [{ role: 'assistant', text: message.text }]
    if (message.kind === 'result') return [{ role: 'assistant', text: `I showed these results: ${message.recommendation.message}` }]
    return []
  }).map((item) => ({ ...item, text: item.text.slice(0, 2000) }))
    .filter((item) => item.text.trim())
  if (dropLastUser && items[items.length - 1]?.role === 'user') items.pop()
  return items.slice(-MAX_HISTORY)
}
