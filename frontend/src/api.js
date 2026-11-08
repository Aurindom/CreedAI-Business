export const OFFLINE_MESSAGE = "We can't reach the server right now. Check your connection and try again."
export const SERVER_MESSAGE = 'Something went wrong on our side. Please try again in a moment.'

// Nothing here retries. A POST that timed out may have been saved, and the plan save relies on request_id for safe repeats.
function failure(message, extra) {
  return Object.assign(new Error(message), extra)
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    throw failure(OFFLINE_MESSAGE, { offline: true, cause })
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.detail ?? null
    if (response.status >= 500) {
      throw failure(SERVER_MESSAGE, { status: response.status, serverError: true, detail })
    }
    const message = detail ? `${response.status}: ${JSON.stringify(detail)}` : `Request failed with ${response.status}`
    throw failure(message, { status: response.status, detail })
  }
  return response.status === 204 ? null : response.json()
}

export function isAbort(error) {
  return error?.name === 'AbortError'
}

export function latestOnly() {
  let current = null
  return (run) => {
    current?.abort()
    const controller = new AbortController()
    current = controller
    return run(controller.signal).then(
      (value) => ({ value, stale: controller !== current }),
      (error) => {
        if (isAbort(error) || controller !== current) return { stale: true }
        throw error
      },
    )
  }
}

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value)
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const PLAN_UNKNOWN = ''
export const PLAN_LABEL_MAX = 100

export function planChoices(tool) {
  const tiers = tool?.plan_tiers
  if (tiers?.status !== 'present' || !Array.isArray(tiers.value)) return []
  return tiers.value.map(String)
}

export function isSingleOffering(tool) {
  return tool?.offering?.status === 'present' && tool.offering.value === 'single'
}

// Plans for tools the owner no longer has are dropped here, so a stale plan never reaches the recommendation.
export function ownedProfile(trade, ownedIds, plans = {}) {
  return {
    trade: trade || null,
    owned: ownedIds.map((id) => {
      const plan = String(plans[id] ?? PLAN_UNKNOWN).trim().slice(0, PLAN_LABEL_MAX)
      return { tool_id: id, plan: plan || null }
    }),
  }
}

function owner(token) {
  return { Authorization: `Bearer ${token}` }
}

// One id per confirm click. Reusing it on a retry or double click returns the first saved plan instead of a copy.
export function newRequestId() {
  return crypto.randomUUID()
}

export const api = {
  account: (token) => request('/api/auth/me', { headers: owner(token), cache: 'no-store' }),
  logoutAccount: (token) => request('/api/auth/logout', { method: 'POST', headers: owner(token) }),
  claimLegacyPlans: (token, legacyToken) => request('/api/plans/claim-legacy', { method: 'POST', headers: owner(token), body: JSON.stringify({ legacy_token: legacyToken }) }),
  loadChatHistory: (token) => request('/api/chat/history', { headers: owner(token), cache: 'no-store' }),
  saveChatHistory: (token, snapshot) => request('/api/chat/history', { method: 'PUT', headers: owner(token), cache: 'no-store', body: JSON.stringify(snapshot) }),
  validateChat: (payload, token) => request('/api/chat/validate', { method: 'POST', headers: token ? owner(token) : {}, body: JSON.stringify(payload) }),
  trades: (signal) => request('/api/trades', { signal }),
  categories: (signal) => request('/api/categories', { signal }),
  problems: (trade, category, signal) => request(`/api/problems${query({ trade, category })}`, { signal }),
  tools: (trade, category, signal) => request(`/api/tools${query({ trade, category })}`, { signal }),
  toolFacts: (toolId, signal) => request(`/api/tools/${encodeURIComponent(toolId)}/facts`, { signal }),
  recommend: (profile, problemId, signal) =>
    request('/api/recommend', { method: 'POST', body: JSON.stringify({ profile, problem_id: problemId }), signal }),
  resolveTask: (text, signal) => request('/api/tasks/resolve', { method: 'POST', body: JSON.stringify({ text }), signal }),
  compare: (profile, problemIds, toolIds, assignments = {}, signal) =>
    request('/api/compare', { method: 'POST', body: JSON.stringify({ profile, problem_ids: problemIds, tool_ids: toolIds, assignments }), signal }),
  stackCheck: (toolIds, signal) => request('/api/stack/check', { method: 'POST', body: JSON.stringify({ tool_ids: toolIds }), signal }),
  startSession: (signal) => request('/api/sessions', { method: 'POST', signal }),
  endSession: (token, signal) => request('/api/sessions/current', { method: 'DELETE', headers: owner(token), signal }),
  plans: (token, signal) => request('/api/plans', { headers: owner(token), signal }),
  savePlan: (token, profile, problemIds, toolIds, requestId, assignments = {}, signal) =>
    request('/api/plans', {
      method: 'POST',
      headers: owner(token),
      body: JSON.stringify({ profile, problem_ids: problemIds, tool_ids: toolIds, request_id: requestId, assignments }),
      signal,
    }),
  plan: (token, planId, signal) => request(`/api/plans/${encodeURIComponent(planId)}`, { headers: owner(token), signal }),
  refreshPlan: (token, planId, signal) =>
    request(`/api/plans/${encodeURIComponent(planId)}/refresh`, { method: 'POST', headers: owner(token), signal }),
}
