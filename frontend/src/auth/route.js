// A tiny page switcher for the two account pages. The rest of the site stays one page.
import { useEffect, useState } from 'react'

export const SIGN_IN_PATH = '/signin'
export const RESET_PATH = '/reset-password'

export function isAccountPath(path) {
  return path === SIGN_IN_PATH || path === RESET_PATH
}

export function navigate(to) {
  window.history.pushState({}, '', to)
  window.dispatchEvent(new window.PopStateEvent('popstate'))
}

export function usePath() {
  const [path, setPath] = useState(() => window.location.pathname)
  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  return path
}

// Only same-site paths are allowed as a return address, so a link can't send someone to another site.
export function safeNext(raw) {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/'
  return isAccountPath(raw.split(/[?#]/)[0]) ? '/' : raw
}

export function signInHref(next = '/', mode) {
  const query = new URLSearchParams()
  if (mode) query.set('mode', mode)
  if (next && next !== '/') query.set('next', next)
  const text = query.toString()
  return text ? `${SIGN_IN_PATH}?${text}` : SIGN_IN_PATH
}

// Where the owner is now, to come back to after signing in.
export function here() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}
