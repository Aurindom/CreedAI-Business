import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { createChatAdapter, EMPTY_MEMORY, loadCatalog } from './chatAdapter'
import ChatErrorBoundary from './ChatErrorBoundary'
import ChatResult from './ChatResult'
import { clearSession, greetingFor, historyFor, loadSession, newConversationId, saveSession } from './chatSession'
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

let nextId = 0
const newId = (prefix) => `${prefix}_${Date.now()}_${nextId++}`

function Panel({ profile, open, onClose }) {
  const adapter = useMemo(() => createChatAdapter(), [])
  const [restored] = useState(() => loadSession(EMPTY_MEMORY))
  const [conversationId, setConversationId] = useState(() => restored?.conversationId || newConversationId())
  const [messages, setMessages] = useState(() => restored?.messages || [])
  const [memory, setMemory] = useState(() => restored?.memory || EMPTY_MEMORY)
  const [resumed, setResumed] = useState(() => Boolean(restored?.messages.length))
  const [names, setNames] = useState({ tools: {}, trades: {} })
  const [live, setLive] = useState(false)
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

  messagesRef.current = messages
  memoryRef.current = memory

  useEffect(() => {
    adapter.isLive().then(setLive).catch(() => setLive(false))
    loadCatalog()
      .then((data) => setNames({
        tools: Object.fromEntries(data.tools.map((tool) => [tool.id, tool.name])),
        trades: Object.fromEntries(data.trades.map((trade) => [trade.id, trade.name])),
      }))
      .catch(() => {})
    return () => clearTimeout(speakTimer.current)
  }, [adapter])

  useEffect(() => {
    saveSession({ conversationId, messages, memory })
  }, [conversationId, messages, memory])

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
    if (messages[messages.length - 1]?.kind === 'result' && latest) {
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
    const text = rawText.trim()
    if (!text) {
      setInputError("Tell me what's going on first.")
      return
    }
    if (busyRef.current) return
    const run = begin()
    setInputError('')
    setNotice('')
    setMessages((current) => current.map((item) => (item.kind === 'clarify' ? { id: item.id, kind: 'assistant', text: item.text } : item)))
    setResumed(false)

    const pending = []
    let replyId = null
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
      if (event.type === 'message_delta') {
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
      if (event.type === 'clarify') addMessage({ kind: 'clarify', text: event.question, choices: event.choices || [], progress: event.progress || '' })
      if (event.type === 'recommendation') pending.push(fetchRecommendation(event.problem_id, event.profile, run))
      if (event.type === 'sources') addMessage({ kind: 'sources', items: event.items || [] })
      if (event.type === 'error') {
        addMessage({
          kind: 'error',
          text: event.message || UNAVAILABLE,
          retry: event.retryable ? { type: 'send', text } : null,
        })
      }
    }

    try {
      await adapter.sendMessage({ conversationId, message: text, profile, memory: memoryRef.current, history, isRetry }, onEvent)
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
    runRef.current += 1
    busyRef.current = false
    clearSession()
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
      <section className="msc-panel" role="dialog" aria-label="Chat with Penny" hidden={!open}>
        <header className="msc-header">
          <div className="msc-identity">
            <PennyAvatar size={44} state={busy ? 'thinking' : speaking ? 'speaking' : 'idle'} />
            <div>
              <h2>Penny</h2>
              <span className={live ? 'msc-live' : 'msc-demo'}>{live ? 'Live AI' : 'Demo mode'}</span>
            </div>
          </div>
          <div className="msc-header-actions">
            <button type="button" className="msc-text-button" onClick={startOver}>Start over</button>
            <button type="button" className="msc-close" onClick={onClose} aria-label="Close chat">×</button>
          </div>
        </header>

        <PennyMemory memory={memory} names={names} onRemove={forget} />

        <div className="msc-log" ref={logRef} role="log" aria-live="polite" aria-busy={busy}>
          {messages.length === 0 && (
            <div className="msc-welcome">
              <h3>{greetingFor(conversationId)}</h3>
              <p>Tell me about your business or what's getting in the way. I'm an AI guide: I'll ask a few questions first, then check real tools and show where each fact came from.</p>
              <div className="msc-starters">
                {STARTERS.map((starter) => <button type="button" key={starter} onClick={() => send(starter)}>{starter}</button>)}
              </div>
            </div>
          )}

          {resumed && <p className="msc-resume">Picked up where you left off.</p>}

          {messages.map((message) => {
            if (message.kind === 'user') return <div className="msc-row msc-row-user" key={message.id}><p>{message.text}</p></div>
            if (message.kind === 'assistant') return <div className="msc-row" key={message.id}><PennyAvatar size={28} /><p>{message.text}</p></div>
            if (message.kind === 'loading') return <div className="msc-loading" key={message.id}>Checking the catalog...</div>
            if (message.kind === 'clarify') {
              return (
                <div className="msc-row msc-clarify" key={message.id}>
                  {message.progress && <span className="msc-progress">{message.progress}</span>}
                  <div className="msc-clarify-question"><PennyAvatar size={28} /><p>{message.text}</p></div>
                  <div className="msc-choices">
                    {message.choices.map((choice) => <button type="button" key={choice} onClick={() => send(choice)} disabled={busy}>{choice}</button>)}
                  </div>
                </div>
              )
            }
            if (message.kind === 'sources') {
              return (
                <ul className="msc-sources" key={message.id}>
                  {message.items.map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer noopener">{item.title}</a>{item.checked ? `, checked ${item.checked}` : ''}</li>)}
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
                statuses={message.statuses}
                ruledOut={memory.ruled_out}
                onPrint={() => setPrintData({ ...message, isDemo: !live })}
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
              placeholder="Tell Penny what's going on"
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
        </form>
      </section>
      <ChatSummary data={printData} />
    </>
  )
}

function ChatPanelInner({ profile }) {
  const [open, setOpen] = useState(false)
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
        <button type="button" className="msc-launcher" ref={launcher} onClick={() => setOpen(true)}>
          <PennyAvatar size={40} />
          Talk to Penny
        </button>
      )}
      <Panel profile={profile} open={open} onClose={close} />
    </div>
  )
}

function ChatPanel({ profile = {} }) {
  return (
    <ChatErrorBoundary>
      <ChatPanelInner profile={profile} />
    </ChatErrorBoundary>
  )
}

export default ChatPanel
