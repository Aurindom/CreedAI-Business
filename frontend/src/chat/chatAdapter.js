import { api } from '../api.js'

const UNAVAILABLE = 'Penny is unavailable right now. You can still browse and compare tools on this page.'
export const EMPTY_MEMORY = { trade: null, owned: [], ruled_out: [], plans: {}, budget_monthly_usd: null, background_done: false, active_task_ids: [], pending_question: null, pending_task_ids: [] }
let catalog = null

export async function loadCatalog() {
  if (!catalog) {
    catalog = Promise.all([api.trades(), api.problems(), api.tools()])
      .then(([trades, problems, tools]) => ({ trades, problems, tools }))
      .catch((error) => { catalog = null; throw error })
  }
  return catalog
}

export function createHttpAdapter({ fetcher = (...args) => fetch(...args) } = {}) {
  async function sendMessage({ conversationId, message, profile, memory, history, accessToken, signal }, onEvent) {
    const response = await fetcher('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}) },
      signal,
      body: JSON.stringify({ conversation_id: conversationId, message, profile, memory, history }),
    })
    if (!response.ok || !response.body) throw new Error(`Chat request failed with ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finished = false

    function handle(block) {
      const payload = block.split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n')
      if (!payload) return
      const event = JSON.parse(payload)
      if (event.type === 'done') finished = true
      onEvent(event)
    }

    while (!finished) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop()
      blocks.forEach(handle)
    }
    if (!finished && buffer.trim()) handle(buffer)
    if (!finished) throw new Error('The reply ended early')
  }

  return { sendMessage }
}

export async function checkLiveChat(fetcher = (...args) => fetch(...args)) {
  try {
    const response = await fetcher('/api/chat/status')
    if (!response.ok) return false
    return (await response.json()).available === true
  } catch {
    return false
  }
}


// Production-only transport: failures never generate scripted answers.
export function createChatAdapter({ fetcher = (...args) => fetch(...args) } = {}) {
  const agent = createHttpAdapter({ fetcher })
  const isLive = () => checkLiveChat(fetcher)
  async function sendMessage(request, onEvent) {
    if (!(await isLive())) {
      onEvent({ type: 'mode', live: false })
      onEvent({ type: 'error', code: 'agent_unavailable', message: UNAVAILABLE, retryable: true })
      onEvent({ type: 'done' })
      return
    }
    onEvent({ type: 'mode', live: true })
    try {
      await agent.sendMessage(request, (event) => {
        if (event.type === 'error' && event.code !== 'agent_busy') onEvent({ type: 'mode', live: false })
        onEvent(event)
      })
    } catch {
      onEvent({ type: 'mode', live: false })
      onEvent({ type: 'error', code: 'agent_unavailable', message: 'Penny could not finish that reply. Please retry, or browse and compare tools on this page.', retryable: true })
      onEvent({ type: 'done' })
    }
  }
  return { sendMessage, isLive }
}
