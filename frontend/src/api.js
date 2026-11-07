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

export const api = {
  trades: () => request('/api/trades'),
  categories: () => request('/api/categories'),
  problems: (trade, category) => request(`/api/problems${query({ trade, category })}`),
  tools: (trade, category) => request(`/api/tools${query({ trade, category })}`),
  recommend: (profile, problemId) => request('/api/recommend', { method: 'POST', body: JSON.stringify({ profile, problem_id: problemId }) }),
  stackCheck: (toolIds) => request('/api/stack/check', { method: 'POST', body: JSON.stringify({ tool_ids: toolIds }) }),
}
