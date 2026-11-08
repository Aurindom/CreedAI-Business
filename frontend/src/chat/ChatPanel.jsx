import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { createChatAdapter, EMPTY_MEMORY, loadCatalog } from './chatAdapter'
import ChatErrorBoundary from './ChatErrorBoundary'
import ChatResult, { safeUrl } from './ChatResult'
import { clearSession, historyFor, loadSession, newConversationId, saveSession } from './chatSession'
import { queueHistory } from './historyCache'
import ChatSummary from './ChatSummary'
import PennyAvatar from './PennyAvatar'
import PennyMemory from './PennyMemory'
import SpeechInput from './SpeechInput'
import './chat.css'

const STARTERS = [
  'Start with a few questions',
  'I keep missing calls while I\'m on a job',
  'I never get around to replying to reviews',
  'My books are behind, and we use QuickBooks',
]
const MAX_LENGTH = 500
const SLOW_AFTER_MS = 8000
const SPEAKING_MS = 1400
const UNAVAILABLE = 'Penny is unavailable right now. You can still browse and compare tools on this page.'
const A2UISurface = React.lazy(() => import('./A2UISurface'))

let nextId = 0
const newId = (prefix) => `${prefix}_${Date.now()}_${nextId++}`

function Panel({ profile, auth, open, onClose, onActivityChange }) {
  const adapter = useMemo(() => createChatAdapter(), [])
  const [restored] = useState(() => auth?.configured ? null : loadSession(EMPTY_MEMORY))
  const [conversationId, setConversationId] = useState(() => restored?.conversationId || newConversationId())
  const [messages, setMessages] = useState(() => restored?.messages || [])
  const [memory, setMemory] = useState(() => restored?.memory || EMPTY_MEMORY)
  const [resumed, setResumed] = useState(() => Boolean(restored?.messages.length))
  const [hydratedFor, setHydratedFor] = useState(null)
  const [historyReady, setHistoryReady] = useState(false)
  const [names, setNames] = useState({ tools: {}, trades: {} })
  const [live, setLive] = useState(null)
  const [speaking, setSpeaking] = useState(false)
  const [input, setInput] = useState('')
  const [inputError, setInputError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [slow, setSlow] = useState(false)
  const [printData, setPrintData] = useState(null)
  const busyRef = useRef(false)
  const runRef = useRef(0)
  const logRef = useRef(null)
  const inputRef = useRef(null)
  const messagesRef = useRef(messages)
  const memoryRef = useRef(memory)
  const speakTimer = useRef(null)
  const abortRef = useRef(null)

  messagesRef.current = messages
  memoryRef.current = memory

  useEffect(() => {
    adapter.isLive().then(setLive).catch(() => setLive(false))
    if (auth?.configured) clearSession()
    loadCatalog()
      .then((data) => setNames({
        tools: Object.fromEntries(data.tools.map((tool) => [tool.id, tool.name])),
        trades: Object.fromEntries(data.trades.map((trade) => [trade.id, trade.name])),
      }))
      .catch(() => {})
    return () => { clearTimeout(speakTimer.current); abortRef.current?.abort(); runRef.current += 1 }
  }, [adapter])

  const userId = auth?.user?.id || null
  const authToken = auth?.session?.access_token || null

  useEffect(() => {
    if (!auth?.configured || !auth.ready || !userId || !authToken) return undefined
    let active = true
    api.loadChatHistory(authToken).then((saved) => {
      if (!active) return
      if (saved?.conversationId && Array.isArray(saved.messages)) {
        setConversationId(saved.conversationId)
        setMessages(saved.messages)
        setMemory({ ...EMPTY_MEMORY, ...saved.memory })
        setResumed(saved.messages.length > 0)
      }
      setHydratedFor(userId)
      setHistoryReady(true)
    }).catch(() => {
      if (active) {
        setHydratedFor(userId)
        setNotice('Could not restore your short chat history. Penny is still available, but this chat is not being saved.')
      }
    })
    return () => { active = false }
  }, [auth?.configured, auth?.ready, userId])

  useEffect(() => {
    if (!auth?.configured) { saveSession({ conversationId, messages, memory }); return }
    if (userId && authToken && hydratedFor === userId && historyReady) {
      queueHistory(authToken, { conversationId, messages: messages.filter((item) => item.kind !== 'loading').slice(-40), memory }).catch(() => {
        setNotice('Penny could not save this short chat history. Please try again before signing out.')
      })
    }
  }, [auth?.configured, userId, authToken, hydratedFor, historyReady, conversationId, messages, memory])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    const log = logRef.current
    if (!log) return
    const results = log.querySelectorAll('.msc-result')
    const latest = results[results.length - 1]
    if ((messages[messages.length - 1]?.kind === 'result' || messages[messages.length - 1]?.surface === 'recommendation') && latest) {
      log.scrollTop += latest.getBoundingClientRect().top - log.getBoundingClientRect().top - 8
    } else {
      log.scrollTop = log.scrollHeight
    }
  }, [messages, status, open])

  useEffect(() => {
    if (!busy) return undefined
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => {
      clearTimeout(timer)
      setSlow(false)
    }
  }, [busy])

  useEffect(() => {
    if (!printData) return undefined
    const clear = () => {
      document.body.classList.remove('msc-printing')
      setPrintData(null)
    }
    document.body.classList.add('msc-printing')
    window.addEventListener('afterprint', clear, { once: true })
    window.print()
    return () => {
      window.removeEventListener('afterprint', clear)
      document.body.classList.remove('msc-printing')
    }
  }, [printData])

  const avatarState = speaking ? 'speaking' : busy ? 'thinking' : input.trim() ? 'listening' : 'idle'
  useEffect(() => { onActivityChange(avatarState) }, [avatarState, onActivityChange])

  const addMessage = (message) => setMessages((current) => [...current, { id: newId('m'), ...message }])
  const replaceMessage = (id, next) => setMessages((current) => current.map((item) => (item.id === id ? { id, ...next } : item)))

  async function fetchRecommendation(problemId, recommendProfile, run, existingId) {
    const id = existingId || newId('m')
    const loading = { kind: 'loading' }
    if (existingId) replaceMessage(id, loading)
    else setMessages((current) => [...current, { id, ...loading }])
    try {
      const [recommendation, data] = await Promise.all([
        api.recommend(recommendProfile, problemId),
        loadCatalog().catch(() => ({ problems: [], tools: [] })),
      ])
      if (run !== runRef.current) return
      replaceMessage(id, {
        kind: 'result',
        recommendation,
        problemTitle: data.problems.find((problem) => problem.id === problemId)?.title || 'Your problem',
        statuses: Object.fromEntries(data.tools.map((tool) => [tool.id, tool.status])),
      })
    } catch {
      if (run !== runRef.current) return
      replaceMessage(id, {
        kind: 'error',
        text: "I couldn't load the tools just now. Try again, or browse them on this page.",
        retry: { type: 'recommend', problemId, profile: recommendProfile, messageId: id },
      })
    }
  }

  function begin() {
    busyRef.current = true
    setBusy(true)
    runRef.current += 1
    return runRef.current
  }

  function finish(run) {
    if (run !== runRef.current) return
    busyRef.current = false
    setBusy(false)
    setStatus('')
  }

  async function send(rawText, { isRetry = false } = {}) {
    if (auth?.configured && (!auth.ready || (userId && hydratedFor !== userId))) {
      setInputError('Restoring your account conversation. Please wait a moment.')
      return
    }
    const text = rawText.trim()
    if (!text) {
      setInputError("Tell me what's going on first.")
      return
    }
    if (busyRef.current) return
    const run = begin()
    setInputError('')
    try {
      const validation = await api.validateChat({ conversation_id: conversationId, message: text, profile, memory, history: historyFor(messagesRef.current, { dropLastUser: isRetry }) }, authToken)
      if (run !== runRef.current) return
      if (!validation.allowed) { setInputError(validation.message); finish(run); return }
    } catch {
      setInputError('We could not check this message safely. Please try again, or use the tool finder.')
      finish(run)
      return
    }
    setNotice('')
    setMessages((current) => current.map((item) => (item.kind === 'clarify' || (item.kind === 'a2ui' && (!item.surface || item.surface === 'question')) ? { id: item.id, kind: 'assistant', text: item.text } : item)))
    setResumed(false)

    const pending = []
    let replyId = null
    let receivedA2UIQuestion = false
    let receivedA2UIRecommendation = false
    let receivedA2UIText = false
    let receivedA2UISources = false
    const history = historyFor(messagesRef.current, { dropLastUser: isRetry })
    if (!isRetry) {
      addMessage({ kind: 'user', text })
      setInput('')
    }

    function onEvent(event) {
      if (run !== runRef.current) return
      if (event.type === 'status') setStatus(event.text)
      if (event.type === 'mode') setLive(event.live)
      if (event.type === 'memory') setMemory({ ...EMPTY_MEMORY, ...event.memory })
      if (event.type === 'message_delta' && !receivedA2UIText) {
        setSpeaking(true)
        clearTimeout(speakTimer.current)
        speakTimer.current = setTimeout(() => setSpeaking(false), SPEAKING_MS)
        if (replyId) {
          setMessages((current) => current.map((item) => (item.id === replyId ? { ...item, text: item.text + event.text } : item)))
        } else {
          replyId = newId('m')
          const id = replyId
          setMessages((current) => [...current, { id, kind: 'assistant', text: event.text }])
        }
      }
      if (event.type === 'a2ui') {
        const surface = ['recommendation', 'text', 'sources'].includes(event.surface) ? event.surface : 'question'
        if (surface === 'recommendation') receivedA2UIRecommendation = true
        if (surface === 'question') receivedA2UIQuestion = true
        if (surface === 'text') {
          receivedA2UIText = true
          setSpeaking(true)
          clearTimeout(speakTimer.current)
          speakTimer.current = setTimeout(() => setSpeaking(false), SPEAKING_MS)
        }
        if (surface === 'sources') receivedA2UISources = true
        addMessage({ kind: 'a2ui', surface, text: event.question || event.message, protocol: event.messages })
      }
      if (event.type === 'clarify' && !receivedA2UIQuestion) addMessage({ kind: 'clarify', text: event.question, choices: event.choices || [], progress: event.progress || '' })
      if (event.type === 'recommendation' && !receivedA2UIRecommendation) pending.push(fetchRecommendation(event.problem_id, event.profile, run))
      if (event.type === 'sources' && !receivedA2UISources) addMessage({ kind: 'sources', items: event.items || [] })
      if (event.type === 'error') {
        addMessage({
          kind: 'error',
          text: event.message || UNAVAILABLE,
          retry: event.retryable ? { type: 'send', text } : null,
        })
      }
    }

    try {
      abortRef.current = new AbortController()
      await adapter.sendMessage({ conversationId, message: text, profile, memory: memoryRef.current, history, isRetry, accessToken: authToken, signal: abortRef.current.signal }, onEvent)
    } catch {
      if (run === runRef.current) addMessage({ kind: 'error', text: UNAVAILABLE, retry: { type: 'send', text } })
    }
    await Promise.allSettled(pending)
    finish(run)
  }

  async function retry(message) {
    if (busyRef.current) return
    setMessages((current) => current.map((item) => (item.id === message.id ? { ...item, retry: null } : item)))
    if (message.retry.type === 'send') {
      send(message.retry.text, { isRetry: true })
      return
    }
    const run = begin()
    await fetchRecommendation(message.retry.problemId, message.retry.profile, run, message.retry.messageId)
    finish(run)
  }

  function startOver() {
    abortRef.current?.abort()
    runRef.current += 1
    busyRef.current = false
    if (!auth?.configured) clearSession()
    setConversationId(newConversationId())
    setBusy(false)
    setStatus('')
    setMessages([])
    setMemory(EMPTY_MEMORY)
    setResumed(false)
    setInput('')
    setInputError('')
    setNotice('')
    inputRef.current?.focus()
  }

  function forget({ field, id }) {
    setMemory((current) => {
      if (id) return { ...current, [field]: current[field].filter((item) => item !== id) }
      return { ...current, [field]: null }
    })
  }

  function submit(event) {
    event.preventDefault()
    send(input)
  }

  function onInputKey(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send(input)
    }
  }

  return (
    <>
      <section className="msc-panel" id="penny-chat-panel" role="dialog" aria-label="Chat with Penny" hidden={!open}>
        <header className="msc-header">
          <div className="msc-identity">
            <span className="penny-panel-mark" data-state={avatarState} aria-hidden="true"><PennyAvatar size={36} state={avatarState} /><span /></span>
            <div className="penny-panel-heading">
              <span className="penny-panel-eyebrow">MAIN STREET / ASSISTANT</span>
              <h2>Penny</h2>
              <span className={live ? 'msc-live' : 'msc-unavailable'}>{live === null ? 'Checking connection' : live ? 'Live AI' : 'Unavailable'}</span>
            </div>
          </div>
          <div className="msc-header-actions">
            <button type="button" className="msc-text-button" onClick={startOver}>New chat</button>
            <button type="button" className="msc-close" onClick={onClose} aria-label="Close chat">×</button>
          </div>
        </header>

        <details className="penny-boundaries"><summary>What Penny will not do</summary><p>Penny will not buy or connect tools, handle payments, reveal private instructions, or accept phone numbers and email addresses. She uses catalog evidence and flags unknowns.</p></details>
        {live === false && <p className="penny-unavailable-note" role="status">Penny is currently unavailable. You can still browse or compare tools while the connection is restored.</p>}
        <PennyMemory memory={memory} names={names} onRemove={forget} />

        <div className="msc-log" ref={logRef} role="log" aria-live="polite" aria-busy={busy}>
          {messages.length === 0 && (
            <div className="msc-welcome">
              <p className="penny-welcome-kicker">A LITTLE CLARITY GOES A LONG WAY</p><h3>Your business.<br />A clearer next step.</h3>
              <p>Explore tools, check what your current plan includes, or work through a business challenge. Answers stay grounded in the catalog and its sources.</p>
              <div className="msc-starters">
                {STARTERS.map((starter) => <button type="button" key={starter} onClick={() => send(starter)}><span>{starter}</span><span className="penny-starter-arrow" aria-hidden="true">&#8599;</span></button>)}
              </div>
            </div>
          )}

          {resumed && <p className="msc-resume">Picked up where you left off.</p>}

          {messages.map((message) => {
            if (message.kind === 'user') return <div className="msc-row msc-row-user" key={message.id}><p>{message.text}</p></div>
            if (message.kind === 'assistant') return <div className="msc-row" key={message.id}><span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} /></span><p>{message.text}</p></div>
            if (message.kind === 'a2ui') return <React.Suspense key={message.id} fallback={<div className="msc-loading">Loading result…</div>}><A2UISurface protocol={message.protocol} onSelect={send} busy={busy} ruledOut={memory.ruled_out} onPrint={setPrintData} /></React.Suspense>
            if (message.kind === 'loading') return <div className="msc-loading" key={message.id}>Checking the catalog...</div>
            if (message.kind === 'clarify') {
              return (
                <div className="msc-row msc-clarify" key={message.id}>
                  {message.progress && <span className="msc-progress">{message.progress}</span>}
                  <div className="msc-clarify-question"><span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} /></span><p>{message.text}</p></div>
                  <div className="msc-choices">
                    {message.choices.map((choice) => <button type="button" key={choice} onClick={() => send(choice)} disabled={busy}>{choice}</button>)}
                  </div>
                </div>
              )
            }
            if (message.kind === 'sources') {
              return (
                <ul className="msc-sources" key={message.id}>
                  {message.items.filter((item) => safeUrl(item.url)).map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer noopener">{item.title}</a>{item.checked ? `, checked ${item.checked}` : ''}</li>)}
                </ul>
              )
            }
            if (message.kind === 'error') {
              return (
                <div className="msc-error" role="alert" key={message.id}>
                  <p>{message.text}</p>
                  {message.retry && <button type="button" className="msc-secondary" onClick={() => retry(message)} disabled={busy}>Try again</button>}
                </div>
              )
            }
            return (
              <ChatResult
                key={message.id}
                recommendation={message.recommendation}
                problemTitle={message.problemTitle}
                statuses={message.statuses}
                ruledOut={memory.ruled_out}
                onPrint={() => setPrintData(message)}
              />
            )
          })}

          {busy && <div className="msc-loading" role="status">{slow ? 'Still working. Thanks for waiting.' : status || 'Working on it...'}</div>}
        </div>

        <form className="msc-form" onSubmit={submit} noValidate>
          {(inputError || notice) && <p className="msc-input-note" role="alert">{inputError || notice}</p>}
          <div className="msc-input-row">
            <textarea
              ref={inputRef}
              rows={2}
              value={input}
              maxLength={MAX_LENGTH}
              placeholder="Ask about a tool or business task..."
              aria-label="Tell Penny what's going on"
              onChange={(event) => {
                setInput(event.target.value)
                setInputError('')
              }}
              onKeyDown={onInputKey}
            />
            <SpeechInput
              value={input}
              onText={(text) => {
                setInput(text)
                setInputError('')
              }}
              onNotice={(text) => {
                setNotice(text)
                setInputError('')
              }}
              disabled={busy}
            />
            <button type="submit" className="msc-send" disabled={busy}>{busy ? 'Working' : 'Send'}</button>
          </div>
          <p className="penny-composer-note">Catalog-backed guidance. Verify details before subscribing.</p>
        </form>
      </section>
      <ChatSummary data={printData} />
    </>
  )
}

function ChatPanelInner({ profile, auth }) {
  const [open, setOpen] = useState(false)
  const [activity, setActivity] = useState('idle')
  const launcher = useRef(null)
  const wasOpen = useRef(false)
  const close = useMemo(() => () => setOpen(false), [])

  useEffect(() => {
    if (wasOpen.current && !open) launcher.current?.focus()
    wasOpen.current = open
  }, [open])

  return (
    <div className="msc-root">
      {!open && (
        <button type="button" className={`msc-launcher penny-character-launcher penny-is-${activity}`} ref={launcher} onClick={() => setOpen(true)} aria-label="Talk to Penny" aria-expanded={open} aria-controls="penny-chat-panel">
          <span className="penny-speech"><strong>Hi, I'm Penny.</strong><span>{activity === 'thinking' ? 'Checking the catalog...' : activity === 'speaking' ? 'Your answer is coming in' : 'Your business. A little backup.'}</span></span>
          <span className="penny-character-stage"><span className="penny-stage-glow" aria-hidden="true" /><PennyAvatar size={130} variant="figure" state={activity} /></span>
          <span className="penny-nameplate"><span className="penny-presence" aria-hidden="true" />Talk to Penny <span aria-hidden="true">&#8599;</span></span>
        </button>
      )}
      <Panel key={auth?.configured ? auth.user?.id || 'signed-out' : 'guest'} profile={profile} auth={auth} open={open} onClose={close} onActivityChange={setActivity} />
    </div>
  )
}

function ChatPanel({ profile = {}, auth }) {
  return (
    <ChatErrorBoundary>
      <ChatPanelInner profile={profile} auth={auth} />
    </ChatErrorBoundary>
  )
}

export default ChatPanel
