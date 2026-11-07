async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ? `${response.status}: ${JSON.stringify(body.detail)}` : `Request failed with ${response.status}`)
  }
  return response.json()
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

export const api = {
  trades: () => request('/api/trades'),
  categories: () => request('/api/categories'),
  problems: (trade, category) => request(`/api/problems${query({ trade, category })}`),
  tools: (trade, category) => request(`/api/tools${query({ trade, category })}`),
  toolFacts: (toolId) => request(`/api/tools/${encodeURIComponent(toolId)}/facts`),
  recommend: (profile, problemId) => request('/api/recommend', { method: 'POST', body: JSON.stringify({ profile, problem_id: problemId }) }),
  stackCheck: (toolIds) => request('/api/stack/check', { method: 'POST', body: JSON.stringify({ tool_ids: toolIds }) }),
}
