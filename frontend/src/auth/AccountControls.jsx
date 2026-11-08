import React, { useState } from 'react'
import './account.css'
import { signOut } from './accountActions'
import { here, navigate, signInHref } from './route'

// Signed out: the button opens the sign-in page. Signed in: a small menu with the email and Sign out.
export default function AccountControls({ auth }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function leave() {
    if (!auth.client || busy) return
    setBusy(true); setMessage('')
    const result = await signOut(auth)
    setBusy(false)
    if (result.ok) setOpen(false)
    setMessage(result.message)
  }

  function onTrigger() {
    if (auth.user) setOpen((current) => !current)
    else navigate(signInHref(here()))
  }

  return <div className="owner-account">
    {auth.error && <p role="status">{auth.error}</p>}
    <button type="button" className="owner-account-trigger" onClick={onTrigger} disabled={!auth.client || !auth.ready}
      aria-expanded={auth.user ? open : undefined} aria-label={auth.user ? 'Your account' : auth.configured ? 'Sign in' : 'Accounts are coming soon'}
      title={!auth.configured ? 'Accounts are coming soon' : undefined}>
      {auth.user ? 'Account' : auth.configured && (!auth.ready || auth.client) ? 'Sign in' : 'Account'}
    </button>
    {open && auth.user && <div className="owner-account-popover">
      <div className="owner-account-label">YOUR ACCOUNT</div>
      <p className="owner-account-email">{auth.user.email || 'Signed in'}</p>
      <button type="button" onClick={leave} disabled={busy}>{busy ? 'Finishing…' : 'Sign out'}</button>
      {message && <p className="owner-account-message" role="status">{message}</p>}
    </div>}
    {!open && message && <span className="owner-account-status" role="status">{message}</span>}
  </div>
}
