import React, { useEffect, useId, useRef, useState } from 'react'
import { createAccount, sendPasswordReset, setNewPassword, signIn, signOut } from './accountActions'
import { passwordChecks, passwordProblem, PASSWORD_MAX, PASSWORD_MIN } from './passwordPolicy'
import { navigate, RESET_PATH, safeNext, signInHref } from './route'
import MainStreetBrand from '../components/MainStreetBrand'
import StreetHeaderScene from '../components/StreetHeaderScene'
import './signin.css'

const HEADINGS = {
  signin: ['Welcome back', 'Sign in to see your saved plans.'],
  create: ['Create your account', 'Save plans and pick up where you left off.'],
  forgot: ['Reset your password', "Enter your email and we'll send you a link."],
  reset: ['Choose a new password', 'You followed a reset link. Pick a new password below.'],
}

function readQuery() {
  const query = new URLSearchParams(window.location.search)
  const mode = query.get('mode')
  return { mode: ['create', 'forgot'].includes(mode) ? mode : 'signin', next: safeNext(query.get('next')) }
}

function PasswordField({ label, value, onChange, autoComplete, showRules, invalid }) {
  const [visible, setVisible] = useState(false)
  const id = useId()
  const rulesId = `${id}-rules`
  return (
    <div className="signin-field-group">
      <div className="field signin-field">
        <label className="signin-label" htmlFor={id}>{label}</label>
        <div className="signin-password">
          <input id={id} type={visible ? 'text' : 'password'} autoComplete={autoComplete} required value={value}
            onChange={(event) => onChange(event.target.value)} aria-invalid={invalid || undefined}
            aria-describedby={showRules ? rulesId : undefined} />
          <button type="button" className="signin-show" aria-pressed={visible} aria-label={visible ? 'Hide password' : 'Show password'} onClick={() => setVisible((current) => !current)}>
            {visible ? 'Hide' : 'Show'}
          </button>
        </div>
      </div>
      {showRules && (
        <ul className="signin-rules" id={rulesId} aria-label="Password needs">
          {passwordChecks(value).map((rule) => (
            <li key={rule.id} className={rule.met ? 'is-met' : ''}>
              <span aria-hidden="true">{rule.met ? '✓' : '○'}</span>{rule.label}<span className="sr-only">{rule.met ? ', done' : ', not yet'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function SignInPage({ auth, path }) {
  const isReset = path === RESET_PATH
  const [{ mode: startMode, next }] = useState(readQuery)
  const [mode, setMode] = useState(isReset ? 'reset' : startMode)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [done, setDone] = useState(false)
  const heading = useRef(null)
  const first = useRef(true)

  useEffect(() => { document.title = `${HEADINGS[mode][0]} | Creed AI` }, [mode])
  useEffect(() => {
    // Move focus to the new heading when the mode changes, so screen readers hear the new form.
    if (first.current) { first.current = false; return }
    heading.current?.focus()
  }, [mode])

  function switchTo(nextMode) {
    setMode(nextMode); setError(''); setNotice(''); setPassword(''); setConfirm(''); setDone(false)
    window.history.replaceState({}, '', signInHref(next, nextMode === 'signin' ? undefined : nextMode))
    window.dispatchEvent(new window.PopStateEvent('popstate'))
  }

  function goBack() { navigate(next) }

  async function submit(event) {
    event.preventDefault()
    if (busy || !auth.client) return
    setError(''); setNotice('')
    if ((mode === 'create' || mode === 'reset')) {
      const problem = passwordProblem(password)
      if (problem) { setError(problem); return }
      if (password !== confirm) { setError("The two passwords don't match."); return }
    }
    setBusy(true)
    let result
    if (mode === 'signin') result = await signIn(auth.client, email, password)
    else if (mode === 'create') result = await createAccount(auth.client, email, password)
    else if (mode === 'forgot') result = await sendPasswordReset(auth.client, email)
    else result = await setNewPassword(auth.client, password)
    setBusy(false)
    setPassword(''); setConfirm('')
    if (!result.ok) { setError(result.message); return }
    if (mode === 'signin' || (mode === 'create' && !result.confirm)) { navigate(next); return }
    setNotice(result.message)
    setDone(true)
  }

  async function leaveAccount() {
    if (busy) return
    setBusy(true)
    const result = await signOut(auth)
    setBusy(false)
    if (!result.ok) setError(result.message)
    else if (result.message) setNotice(result.message)
  }

  const [title, subtitle] = HEADINGS[mode]
  let body
  if (!auth.configured) {
    body = <p className="signin-note">Accounts are coming soon. You can still find and compare tools as a guest.</p>
  } else if (!auth.ready) {
    body = <p className="signin-note" role="status">Checking your sign-in…</p>
  } else if (mode === 'reset' && !auth.session && !done) {
    body = <>
      <p className="signin-note">This reset link has expired or was already used.</p>
      <button type="button" className="signin-primary" onClick={() => switchTo('forgot')}>Send a new link</button>
    </>
  } else if (auth.user && mode !== 'reset') {
    body = <>
      <p className="signin-note">You're signed in as <strong>{auth.user.email || 'your account'}</strong>.</p>
      <button type="button" className="signin-primary" onClick={goBack}>Continue to Creed AI</button>
      <button type="button" className="signin-link" onClick={leaveAccount} disabled={busy}>{busy ? 'Signing out…' : 'Sign out'}</button>
    </>
  } else if (done) {
    body = <>
      <p className="signin-success" role="status">{notice}</p>
      {mode === 'reset'
        ? <button type="button" className="signin-primary" onClick={() => navigate('/')}>Continue to Creed AI</button>
        : <button type="button" className="signin-primary" onClick={() => switchTo('signin')}>Back to sign in</button>}
    </>
  } else {
    body = (
      <form className="signin-form" onSubmit={submit} noValidate>
        {mode !== 'reset' && (
          <div className="field signin-field">
            <label className="signin-label" htmlFor="signin-email">Email</label>
            <input id="signin-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
        )}
        {mode !== 'forgot' && (
          <PasswordField label={mode === 'signin' ? 'Password' : 'New password'} value={password} onChange={setPassword}
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} showRules={mode !== 'signin'}
            invalid={Boolean(error) && mode !== 'signin' && Boolean(passwordProblem(password))} />
        )}
        {(mode === 'create' || mode === 'reset') && (
          <PasswordField label="Type it again" value={confirm} onChange={setConfirm} autoComplete="new-password"
            invalid={Boolean(error) && confirm !== password} />
        )}
        {mode === 'signin' && <button type="button" className="signin-link signin-forgot" onClick={() => switchTo('forgot')}>Forgot password?</button>}
        {error && <p className="signin-error" role="alert">{error}</p>}
        <button type="submit" className="signin-primary" disabled={busy}>
          {busy ? 'Working…' : mode === 'signin' ? 'Sign in' : mode === 'create' ? 'Create account' : mode === 'forgot' ? 'Send reset link' : 'Save new password'}
        </button>
        {mode === 'signin' && <p className="signin-switch">New here? <button type="button" className="signin-link" onClick={() => switchTo('create')}>Create an account</button></p>}
        {mode === 'create' && <p className="signin-switch">Already have an account? <button type="button" className="signin-link" onClick={() => switchTo('signin')}>Sign in</button></p>}
        {mode === 'forgot' && <p className="signin-switch">Remembered it? <button type="button" className="signin-link" onClick={() => switchTo('signin')}>Back to sign in</button></p>}
      </form>
    )
  }

  return (
    <div className="site-shell signin-page">
      <header className="sidebar street-header signin-header" onClickCapture={(event) => {
        // The shared logo links to "#"; on this page it should go back to the site's home.
        if (event.target.closest('.mainstreet-brand')) { event.preventDefault(); navigate('/') }
      }}>
        <StreetHeaderScene />
        <MainStreetBrand />
        <button type="button" className="nav-quick-compare signin-back" onClick={goBack}><span aria-hidden="true">←</span> Back to the site</button>
      </header>
      <main className="signin-main" id="main">
        <section className="signin-intro section-heading" aria-label="Why make an account">
          <div className="section-kicker">YOUR ACCOUNT <span /> SAVE YOUR PLAN</div>
          <h2>Keep your plan in one place.</h2>
          <ul>
            <li>Save the tools you picked and what they cost.</li>
            <li>Come back later and pick up where you left off.</li>
            <li>Browsing and comparing still work without an account.</li>
          </ul>
        </section>
        <section className="form-card signin-card" aria-labelledby="signin-title">
          <h1 id="signin-title" ref={heading} tabIndex={-1}>{title}</h1>
          <p className="signin-sub">{subtitle}</p>
          {(mode === 'create' || mode === 'reset') && !done && auth.configured && <p className="signin-policy">Passwords need {PASSWORD_MIN} to {PASSWORD_MAX} characters and at least one number.</p>}
          {body}
        </section>
      </main>
      <footer className="signin-footer"><span>Creed AI: a clearer way to choose AI</span></footer>
    </div>
  )
}
