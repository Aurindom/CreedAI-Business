import { api } from '../api.js'

const UNAVAILABLE = 'Arkadio is unavailable right now. You can still browse and compare tools on this page.'
export const EMPTY_MEMORY = { trade: null, business_description: null, business_forgotten: false, business_goal: null, scenario_business: null, comparison_excluded_ids: [], comparison_presentation: 'prose', pending_favourite_action: null, last_tool_ids: [], comparison_criterion: null, owned: [], ruled_out: [], plans: {}, budget_monthly_usd: null, background_done: false, active_task_ids: [], pending_question: null, pending_task_ids: [] }
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
      body: JSON.stringify({ conversation_id: conversationId, message, profile, memory, history, ui_version: 3 }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      const seconds = Number(response.headers.get('retry-after'))
      throw Object.assign(new Error('Chat request was refused'), {
        status: response.status,
        dailyLimit: typeof body.detail === 'string' && /daily.*limit/i.test(body.detail),
        accountCheck: typeof body.detail === 'string' && /account verification/i.test(body.detail),
        retryAfter: Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null,
      })
    }
    if (!response.body) throw new Error('Chat response has no stream')

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

    try { while (!finished) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop()
      blocks.forEach(handle)
    }
    if (!finished && buffer.trim()) handle(buffer)
    if (!finished) throw new Error('The reply ended early')
    } finally {
      await reader.cancel().catch(() => {})
      reader.releaseLock()
    }
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
    // The server can answer app help and grounded catalog requests without a
    // healthy model. A separate readiness probe must not veto those requests.
    onEvent({ type: 'mode', live: true })
    try {
      await agent.sendMessage(request, (event) => {
        onEvent(event)
      })
    } catch (error) {
      if (request.signal?.aborted || error?.name === 'AbortError') return
      // A refusal or one broken stream does not establish global service health.
      // In particular, HTTP 429 must never become an "agent offline" badge.
      let failure = { type: 'error', code: 'agent_unavailable', message: 'The connection ended before the reply finished. Your chat is still here. Please try again.', retryable: true }
      if (error?.status === 429) failure = {
        type: 'error', code: error.dailyLimit ? 'daily_ai_limit' : 'rate_limited',
        message: error.dailyLimit
          ? "You have reached today's AI request limit. Catalog browsing and supported comparisons still work. Your AI allowance renews at midnight UTC."
          : `Too many messages were sent in a short time. Please wait ${error.retryAfter || 60} seconds before sending another. Your chat is still here.`,
        retryable: false, retry_after_seconds: error.retryAfter,
      }
      else if (error?.status === 401 || error?.status === 403) failure = {
        type: 'error', code: 'session_expired', message: 'Your sign-in has expired. Sign in again to continue this conversation. Your saved history is still available.', retryable: false,
      }
      else if (error?.status === 422) failure = {
        type: 'error', code: 'invalid_request', message: 'This message could not be sent. Refresh the page and try again; your saved chat will stay available.', retryable: false,
      }
      else if (error?.accountCheck) failure = {
        type: 'error', code: 'account_verification_unavailable', message: 'Your sign-in could not be checked right now. Please try again in a moment.', retryable: true,
      }
      onEvent(failure)
      onEvent({ type: 'done' })
    }
  }
  return { sendMessage, isLive }
}
