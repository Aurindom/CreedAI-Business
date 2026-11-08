// Account steps shared by the sign-in page and the account menu, so both behave the same.
// Each returns { ok, message } and never throws.
import { api } from '../api'
import { flushHistory, forgetQueuedHistory } from '../chat/historyCache'
import { passwordProblem } from './passwordPolicy'

const UNREACHABLE = 'We could not reach the sign-in service. Check your connection and try again.'

// Supabase's wording is technical; these read better for owners. Anything else is shown as Supabase wrote it.
function friendly(error) {
  const text = error?.message || ''
  if (/invalid login credentials/i.test(text)) return "That email and password don't match. Try again, or reset your password."
  if (/email not confirmed/i.test(text)) return 'Please confirm your email first. Check your inbox or spam folder for the link.'
  if (/already registered|already been registered/i.test(text)) return 'An account with this email already exists. Sign in instead.'
  if (/rate limit|too many/i.test(text)) return 'Too many tries. Please wait a minute and try again.'
  return text || UNREACHABLE
}

export async function signIn(client, email, password) {
  try {
    const { error } = await client.auth.signInWithPassword({ email: email.trim(), password })
    return error ? { ok: false, message: friendly(error) } : { ok: true, message: '' }
  } catch {
    return { ok: false, message: UNREACHABLE }
  }
}

export async function createAccount(client, email, password) {
  const problem = passwordProblem(password)
  if (problem) return { ok: false, message: problem }
  try {
    const { data, error } = await client.auth.signUp({ email: email.trim(), password, options: { emailRedirectTo: window.location.origin } })
    if (error) return { ok: false, message: friendly(error) }
    // With email confirmation on, Supabase returns no session until the owner clicks the link.
    if (!data?.session) return { ok: true, confirm: true, message: 'Check your inbox or spam folder for a confirmation link. Then come back and sign in.' }
    return { ok: true, message: '' }
  } catch {
    return { ok: false, message: UNREACHABLE }
  }
}

export async function sendPasswordReset(client, email) {
  try {
    const { error } = await client.auth.resetPasswordForEmail(email.trim(), { redirectTo: `${window.location.origin}/reset-password` })
    if (error) return { ok: false, message: friendly(error) }
    // Same answer whether or not the email has an account, so the page doesn't reveal who signed up.
    return { ok: true, message: 'If that email has an account, a reset link is on its way. Check your inbox or spam folder.' }
  } catch {
    return { ok: false, message: UNREACHABLE }
  }
}

export async function setNewPassword(client, password) {
  const problem = passwordProblem(password)
  if (problem) return { ok: false, message: problem }
  try {
    const { error } = await client.auth.updateUser({ password })
    return error ? { ok: false, message: friendly(error) } : { ok: true, message: 'Your password is updated.' }
  } catch {
    return { ok: false, message: UNREACHABLE }
  }
}

// Saves Penny's chat history, closes the server session, then ends the Supabase session in this browser.
export async function signOut(auth) {
  let saved = true
  try { await flushHistory() } catch { saved = false }
  let serverClosed = true
  try {
    const result = await api.logoutAccount(auth.session?.access_token)
    if (!result.cache_expiry_confirmed) saved = false
  } catch { serverClosed = false }
  try {
    const { error } = await auth.client.auth.signOut({ scope: 'local' })
    forgetQueuedHistory()
    if (error) return { ok: false, message: error.message }
    if (!serverClosed) return { ok: true, message: 'Signed out on this browser. Server sign-out could not be confirmed.' }
    if (!saved) return { ok: true, message: 'Signed out. Conversation recovery or cache cleanup could not be confirmed.' }
    return { ok: true, message: '' }
  } catch {
    return { ok: false, message: 'Could not sign out. Please try again.' }
  }
}
