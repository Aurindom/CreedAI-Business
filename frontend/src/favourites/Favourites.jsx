import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import './favourites.css'

const FavouritesContext = createContext({ items: [], ready: false, signedIn: false, pending: new Set(), toggle: () => {} })
export const useFavourites = () => useContext(FavouritesContext)

export function FavouritesProvider({ auth, children }) {
  const userId = auth?.user?.id || null
  const token = auth?.session?.access_token
  const [saved, setSaved] = useState({ userId: null, items: [], ready: false })
  const [error, setError] = useState('')
  const [pending, setPending] = useState(new Set())
  const [attempt, setAttempt] = useState(0)
  const generation = useRef(0)
  const pendingRef = useRef(new Set())
  const signedIn = Boolean(userId && token && auth?.ready)
  const items = saved.userId === userId ? saved.items : []
  const ready = signedIn && saved.userId === userId && saved.ready

  useEffect(() => {
    const run = ++generation.current
    const controller = new AbortController()
    pendingRef.current = new Set()
    setPending(new Set()); setError('')
    setSaved({ userId, items: [], ready: false })
    if (signedIn) api.favourites(token, controller.signal).then(items => {
      if (run === generation.current) setSaved({ userId, items, ready: true })
    }).catch(error => {
      if (run === generation.current && error.name !== 'AbortError') setError('Could not load your favourite tools. Please retry.')
    })
    return () => { generation.current += 1; controller.abort() }
  // A token refresh keeps the same owner and must not race a pending mutation
  // against a new list request. Mutations use the latest rendered token.
  }, [userId, signedIn, attempt])

  async function toggle(id) {
    if (!ready || pendingRef.current.has(id)) return
    const run = generation.current
    const exists = items.some(item => item.tool_id === id)
    pendingRef.current.add(id); setPending(new Set(pendingRef.current)); setError('')
    try {
      const item = exists ? await api.removeFavourite(token, id) : await api.saveFavourite(token, id)
      if (run !== generation.current) return
      setSaved(current => ({ ...current, items: exists ? current.items.filter(item => item.tool_id !== id) : [item, ...current.items.filter(row => row.tool_id !== id)] }))
    } catch {
      if (run === generation.current) setError(exists ? 'Could not remove this favourite. Please retry.' : 'Could not save this favourite. Please retry.')
    } finally {
      if (run === generation.current) { pendingRef.current.delete(id); setPending(new Set(pendingRef.current)) }
    }
  }

  return <FavouritesContext.Provider value={{ items, ready, signedIn, pending, toggle, error, retry: () => setAttempt(value => value + 1) }}>{children}{signedIn && ready && error && <div className="favourites-toast" role="alert">{error}<button type="button" onClick={() => setError('')}>Dismiss</button></div>}</FavouritesContext.Provider>
}

export function FavouriteButton({ toolId, name }) {
  const favourites = useFavourites()
  const selected = favourites.items.some(item => item.tool_id === toolId)
  const saving = favourites.pending.has(toolId)
  const label = !favourites.signedIn ? `Sign in to save ${name} as a favourite` : `${selected ? 'Remove' : 'Save'} ${name} ${selected ? 'from' : 'to'} favourites`
  return <button type="button" className={`favourite-button${selected ? ' is-favourite' : ''}`} aria-label={label} title={label} aria-pressed={selected} aria-busy={saving} disabled={!favourites.ready || saving} onClick={() => favourites.toggle(toolId)}>
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" /></svg>
  </button>
}

export function FavouriteTools({ toolsById, renderTool }) {
  const { items, ready, signedIn, error, retry } = useFavourites()
  return <>
    {!signedIn && <p className="favourites-empty">Sign in to keep your favourite tools and find them here next time.</p>}
    {signedIn && !ready && !error && <p role="status">Loading your favourites…</p>}
    {error && <div className="favourites-error" role="alert">{error} <button type="button" onClick={retry}>Retry favourites</button></div>}
    {ready && items.length === 0 && <p className="favourites-empty">Tap the heart on any tool to save it here. Your favourites stay with your account until you remove them.</p>}
    {signedIn && items.length > 0 && <div className="tool-grid favourites-grid">{items.map(item => {
      const tool = toolsById[item.tool_id]
      return tool && item.available && tool.status !== 'rejected' ? renderTool(tool) : <article className="tool-card" key={item.tool_id}><div className="tool-card-head"><h3>{item.tool_name}</h3><FavouriteButton toolId={item.tool_id} name={item.tool_name} /></div><p>{item.available ? 'Tool details are unavailable right now. You can keep or remove this favourite.' : 'This tool is no longer listed in the directory. You can remove it from your favourites.'}</p></article>
    })}</div>}
  </>
}
