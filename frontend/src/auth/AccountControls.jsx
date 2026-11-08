import React, { useState } from 'react'
import { flushHistory, forgetQueuedHistory } from '../chat/historyCache'
import './account.css'

export default function AccountControls({ auth }) {
  const [open, setOpen] = useState(false)
  const [create, setCreate] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function submit(event) {
    event.preventDefault()
    if (!auth.client || busy) return
    setBusy(true); setMessage('')
    try {
      const result = create
        ? await auth.client.auth.signUp({ email: email.trim(), password })
        : await auth.client.auth.signInWithPassword({ email: email.trim(), password })
      setPassword('')
      if (result.error) setMessage(result.error.message)
      else if (create && !result.data.session) setMessage('Check your email to confirm your account, then sign in.')
      else { setOpen(false); setMessage('') }
    } catch { setMessage('Could not reach account sign in. Please try again.') }
    finally { setBusy(false) }
  }

  async function signOut() {
    if (!auth.client || busy) return
    setBusy(true); setMessage('')
    let saved = true
    try { await flushHistory(true) } catch { saved = false }
    try {
      const { error } = await auth.client.auth.signOut({ scope: 'local' })
      if (error) setMessage(error.message)
      else {
        forgetQueuedHistory()
        setOpen(false); setEmail(''); setPassword('')
        if (!saved) setMessage('Signed out. This chat may not be available when you return.')
      }
    } catch { setMessage('Could not sign out. Please try again.') }
    finally { setBusy(false) }
  }

  return <div className="owner-account">
    <button type="button" className="owner-account-trigger" onClick={() => setOpen((current) => !current)} disabled={!auth.client || !auth.ready} aria-expanded={open} aria-label={auth.user ? 'Your account' : auth.configured ? 'Sign in to save Penny chat' : 'Account setup pending'} title={!auth.configured ? 'Account setup pending' : undefined}>{auth.user ? 'Account' : auth.configured && (!auth.ready || auth.client) ? 'Sign in' : 'Account'}</button>
    {open && <div className="owner-account-popover">
      {auth.user ? <>
        <div className="owner-account-label">YOUR ACCOUNT</div>
        <p className="owner-account-email">{auth.user.email || 'Signed in'}</p>
        <p className="owner-account-hint">Penny chat can be restored for five minutes after sign out.</p>
        <button type="button" onClick={signOut} disabled={busy}>{busy ? 'Finishing…' : 'Sign out'}</button>
      </> : <>
        <div className="owner-account-label">SAVE YOUR PENNY CHAT</div>
        <p className="owner-account-hint">Sign in to return to your conversation for five minutes after signing out.</p>
        <form onSubmit={submit} className="owner-account-form">
          <h3>{create ? 'Create your account' : 'Welcome back'}</h3>
          <label>Email<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Password<input type="password" autoComplete={create ? 'new-password' : 'current-password'} required minLength={6} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <button type="submit" disabled={busy}>{busy ? 'Working…' : create ? 'Create account' : 'Sign in'}</button>
          <button type="button" className="owner-account-switch" onClick={() => { setCreate((current) => !current); setMessage('') }}>{create ? 'I already have an account' : 'Create an account'}</button>
        </form>
      </>}
      {message && <p className="owner-account-message" role="status">{message}</p>}
    </div>}
    {!open && message && <span className="owner-account-status" role="status">{message}</span>}
  </div>
}
