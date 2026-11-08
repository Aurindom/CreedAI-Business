import { useEffect, useState } from 'react'

const url = import.meta.env.VITE_SUPABASE_URL
const publishable = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY
export const authConfigured = Boolean(url && publishable)
let clientPromise

function loadClient() {
  if (!clientPromise) clientPromise = import('@supabase/supabase-js').then(({ createClient }) => createClient(url, publishable, {
    auth: { autoRefreshToken: true, persistSession: true, detectSessionInUrl: true },
  }))
  return clientPromise
}

export function useOwnerAuth() {
  const [session, setSession] = useState(null)
  const [client, setClient] = useState(null)
  const [ready, setReady] = useState(!authConfigured)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!authConfigured) return undefined
    let active = true
    let subscription
    let version = 0
    loadClient().then((loaded) => {
      if (!active) return
      setClient(loaded)
      subscription = loaded.auth.onAuthStateChange((_event, next) => {
        version += 1
        if (active) { setSession(next); setReady(true) }
      }).data.subscription
      const initialVersion = version
      loaded.auth.getSession().then(({ data }) => {
        if (active && version === initialVersion) { setSession(data.session); setReady(true) }
      }).catch(() => { if (active) { setReady(true); setError('Could not restore your sign-in. Please sign in again.') } })
    }).catch(() => { if (active) { setReady(true); setError('Account sign-in is unavailable. Please try again.') } })
    return () => { active = false; subscription?.unsubscribe() }
  }, [])

  return { configured: authConfigured, ready, client, session, user: session?.user || null, error }
}
