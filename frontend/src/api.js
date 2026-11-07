async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ? `${response.status}: ${JSON.stringify(body.detail)}` : `Request failed with ${response.status}`)
  }
  return response.status === 204 ? null : response.json()
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
  trades: () => request('/api/trades'),
  categories: () => request('/api/categories'),
  problems: (trade, category) => request(`/api/problems${query({ trade, category })}`),
  tools: (trade, category) => request(`/api/tools${query({ trade, category })}`),
  toolFacts: (toolId) => request(`/api/tools/${encodeURIComponent(toolId)}/facts`),
  recommend: (profile, problemId) => request('/api/recommend', { method: 'POST', body: JSON.stringify({ profile, problem_id: problemId }) }),
  resolveTask: (text) => request('/api/tasks/resolve', { method: 'POST', body: JSON.stringify({ text }) }),
  compare: (profile, problemIds, toolIds, assignments = {}) =>
    request('/api/compare', { method: 'POST', body: JSON.stringify({ profile, problem_ids: problemIds, tool_ids: toolIds, assignments }) }),
  stackCheck: (toolIds) => request('/api/stack/check', { method: 'POST', body: JSON.stringify({ tool_ids: toolIds }) }),
  startSession: () => request('/api/sessions', { method: 'POST' }),
  endSession: (token) => request('/api/sessions/current', { method: 'DELETE', headers: owner(token) }),
  plans: (token) => request('/api/plans', { headers: owner(token) }),
  savePlan: (token, profile, problemIds, toolIds, requestId, assignments = {}) =>
    request('/api/plans', {
      method: 'POST',
      headers: owner(token),
      body: JSON.stringify({ profile, problem_ids: problemIds, tool_ids: toolIds, request_id: requestId, assignments }),
    }),
  plan: (token, planId) => request(`/api/plans/${encodeURIComponent(planId)}`, { headers: owner(token) }),
  refreshPlan: (token, planId) => request(`/api/plans/${encodeURIComponent(planId)}/refresh`, { method: 'POST', headers: owner(token) }),
}
