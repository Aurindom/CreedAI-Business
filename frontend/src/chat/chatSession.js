const KEY = 'main-street-penny-session-v2'
const MAX_SAVED_MESSAGES = 40
const MAX_HISTORY = 12
// The backend's ChatMemory limits. Memory goes back with every message, so a list over its
// limit would get every message rejected; trimming here also heals a chat that is already stuck.
const MEMORY_LIMITS = { owned: 20, ruled_out: 20, active_task_ids: 5, pending_task_ids: 3, last_tool_ids: 6, comparison_excluded_ids: 20, pending_favourite_ids: 6 }
const MAX_PLANS = 20

export function memoryForRequest(memory = {}) {
  const trimmed = { ...memory }
  for (const [name, limit] of Object.entries(MEMORY_LIMITS)) {
    if (Array.isArray(trimmed[name])) trimmed[name] = trimmed[name].slice(0, limit)
  }
  if (trimmed.plans && typeof trimmed.plans === 'object') trimmed.plans = Object.fromEntries(Object.entries(trimmed.plans).slice(0, MAX_PLANS))
  return trimmed
}

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

// Older snapshots saved the evidence paragraph after the same turn's cards.
// Keep the stored conversation intact; omit that duplicate from presentation.
export function visibleMessages(messages) {
  let title = null
  let evidence = false
  return messages.filter((message) => {
    if (message.kind === 'user') { title = null; evidence = false }
    const component = message.protocol?.[1]?.updateComponents?.components?.[0]
    if (message.kind === 'result' || component?.component === 'PennyRecommendation') {
      title = message.problemTitle || component?.problemTitle
      evidence = false
    }
    const isText = message.kind === 'assistant' || (message.kind === 'a2ui' && message.surface === 'text')
    if (title && isText && (evidence || (message.text?.startsWith(`${title}:`) && message.text.includes('Source: https://')))) {
      evidence = true
      return false
    }
    if (!isText) evidence = false
    return true
  })
}

export function historyFor(messages, { dropLastUser = false } = {}) {
  const items = messages.flatMap((message) => {
    if (message.kind === 'user') return [{ role: 'user', text: message.text }]
    if (message.kind === 'a2ui' && message.surface === 'sources') return []
    if (message.kind === 'a2ui' && message.surface === 'table') {
      const table = message.protocol?.[1]?.updateComponents?.components?.[0]
      return [{ role: 'assistant', text: `Compared by ${table?.criterion}: ${(table?.rows || []).map(row => `${row.tool}: plan ${row.plan}, entry ${row.entry_price}, added cost ${row.added_cost}`).join('; ')}` }]
    }
    if (message.kind === 'a2ui' && message.surface === 'recommendation') {
      const result = message.protocol?.[1]?.updateComponents?.components?.[0]?.recommendation
      const tools = [...(result?.options || []), ...(result?.check_first || [])].map(tool => tool.tool_id).join(', ')
      return [{ role: 'assistant', text: `${message.text || ''} Shown tool IDs: ${tools}` }]
    }
    if (message.kind === 'assistant' || message.kind === 'clarify' || message.kind === 'a2ui') return [{ role: 'assistant', text: message.text }]
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
