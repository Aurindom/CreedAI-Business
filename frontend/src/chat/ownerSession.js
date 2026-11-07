// Holds the private session token for saved plans. It stays in this browser tab only
// and is never shown on screen or sent anywhere except our own backend.
const KEY = 'main-street-penny-owner-v1'

function read() {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(KEY) || 'null')
    return saved?.token && Date.parse(saved.expires_at) > Date.now() ? saved.token : null
  } catch {
    return null
  }
}

async function start(api) {
  const session = await api.startSession()
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ token: session.token, expires_at: session.expires_at }))
  } catch {
    // The token still works for this request even if it can't be remembered.
  }
  return session.token
}

export function forgetOwner() {
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // Nothing to forget.
  }
}

// Runs a private request, starting a new session once if the old one has ended.
export async function withOwner(api, run) {
  const token = read() || (await start(api))
  try {
    return await run(token)
  } catch (error) {
    if (!String(error?.message || '').startsWith('401')) throw error
    forgetOwner()
    return run(await start(api))
  }
}
