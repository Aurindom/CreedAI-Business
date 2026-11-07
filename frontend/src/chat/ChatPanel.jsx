import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api, isSingleOffering, newRequestId, planChoices } from '../api'
import { DraftBuilder, DraftCard } from './AssistantDraft'
import { createChatAdapter, EMPTY_MEMORY, loadCatalog } from './chatAdapter'
import { withOwner } from './ownerSession'
import { AlternativesCard, PlanQuestion, SavedPlanCard } from './ResultExtras'
import ChatErrorBoundary from './ChatErrorBoundary'
import ChatResult from './ChatResult'
import { clearSession, greetingFor, historyFor, loadSession, newConversationId, saveSession } from './chatSession'
import ChatSummary from './ChatSummary'
import PennyAvatar from './PennyAvatar'
import PennyMemory from './PennyMemory'
import SpeechInput from './SpeechInput'
import { useDraggable, useIsPhone } from './useDraggable'
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
const WANTS_ASSISTANT = /\b(custom|own|build|make|create|draft)\b.*\b(assistant|helper|bot|chatbot)\b/i
const PLAN_ROUTES = ['check_plan', 'plan_upgrade']

// Adds plans the owner picked in chat to the tools they already have.
function withPlans(profile, plans = {}) {
  return {
    ...profile,
    owned: (profile?.owned || []).map((entry) => (plans[entry.tool_id] ? { ...entry, plan: plans[entry.tool_id] } : entry)),
  }
}

function latestResult(list) {
  return [...list].reverse().find((message) => message.kind === 'result' && message.problemId)
}

// What Penny is talking about right now, so a follow-up like "how much is it?" stays on topic.
function contextFor(list) {
  const result = latestResult(list)
  if (!result) return {}
  const { recommendation } = result
  const winner = [...recommendation.options, ...recommendation.check_first].find((option) => option.tool_id === recommendation.winner_tool_id)
  return {
    problemId: result.problemId,
    problemTitle: result.problemTitle,
    winnerId: recommendation.winner_tool_id || null,
    winnerName: winner?.tool_name || null,
  }
}

let nextId = 0
const newId = (prefix) => `${prefix}_${Date.now()}_${nextId++}`

function Panel({ profile, open, onClose, drag, phone }) {
  const adapter = useMemo(() => createChatAdapter(), [])
  const [restored] = useState(() => loadSession(EMPTY_MEMORY))
  const [conversationId, setConversationId] = useState(() => restored?.conversationId || newConversationId())
  const [messages, setMessages] = useState(() => restored?.messages || [])
  const [memory, setMemory] = useState(() => restored?.memory || EMPTY_MEMORY)
  const [resumed, setResumed] = useState(() => Boolean(restored?.messages.length))
  const [names, setNames] = useState({ tools: {}, trades: {} })
  const [toolsById, setToolsById] = useState({})
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
      .then((data) => {
        setNames({
          tools: Object.fromEntries(data.tools.map((tool) => [tool.id, tool.name])),
          trades: Object.fromEntries(data.trades.map((trade) => [trade.id, trade.name])),
        })
        setToolsById(Object.fromEntries(data.tools.map((tool) => [tool.id, tool])))
      })
      .catch(() => {})
    return () => clearTimeout(speakTimer.current)
  }, [adapter])

  useEffect(() => {
    if (!input && inputRef.current) inputRef.current.style.height = ''
  }, [input])

  useEffect(() => {
    saveSession({ conversationId, messages, memory })
  }, [conversationId, messages, memory])

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    drag.reclamp()
  }, [open, drag])

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

  const lastResultId = latestResult(messages)?.id
  const quick = quickReplies()
  const addMessage = (message) => setMessages((current) => [...current, { id: newId('m'), ...message }])
  const replaceMessage = (id, next) => setMessages((current) => current.map((item) => (item.id === id ? { id, ...next } : item)))

  async function fetchRecommendation(problemId, givenProfile, run, existingId) {
    const recommendProfile = withPlans(givenProfile, memoryRef.current.plans)
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
        problemId,
        profile: recommendProfile,
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
    if (!isRetry && WANTS_ASSISTANT.test(text)) {
      setMessages((current) => [...current, { id: newId('m'), kind: 'user', text }, { id: newId('m'), kind: 'draft-builder', topic: '' }])
      setInput('')
      setInputError('')
      setResumed(false)
      return
    }
    const run = begin()
    setInputError('')
    setNotice('')
    setMessages((current) => current.map((item) => (item.kind === 'clarify' ? { id: item.id, kind: 'assistant', text: item.text } : item)))
    setResumed(false)

    const pending = []
    const actions = []
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
      if (event.type === 'memory') setMemory((current) => ({ ...EMPTY_MEMORY, ...event.memory, plans: { ...current.plans, ...(event.memory.plans || {}) } }))
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
      if (event.type === 'action' && ['compare', 'save'].includes(event.action)) actions.push(event.action)
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
      await adapter.sendMessage({ conversationId, message: text, profile, memory: memoryRef.current, history, isRetry, context: contextFor(messagesRef.current) }, onEvent)
    } catch {
      if (run === runRef.current) addMessage({ kind: 'error', text: UNAVAILABLE, retry: { type: 'send', text } })
    }
    await Promise.allSettled(pending)
    finish(run)
    const target = latestResult(messagesRef.current)
    if (run === runRef.current && target) {
      if (actions.includes('compare')) compareAlternatives(target)
      else if (actions.includes('save') && target.recommendation.winner_tool_id) savePlan(target)
    }
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

  async function runAction(work) {
    if (busyRef.current) return
    const run = begin()
    try {
      await work(run)
    } finally {
      finish(run)
    }
  }

  function pickPlan(message, toolId, plan) {
    const plans = { ...memoryRef.current.plans, [toolId]: plan || '' }
    memoryRef.current = { ...memoryRef.current, plans }
    setMemory((current) => ({ ...current, plans }))
    const toolName = toolsById[toolId]?.name || 'that tool'
    addMessage({ kind: 'user', text: plan ? `I'm on ${plan}` : "I don't know my plan" })
    if (!plan) {
      addMessage({ kind: 'assistant', text: `No problem. Check your ${toolName} plan before paying for anything new. You can find it in your account or billing settings.` })
      return
    }
    runAction((run) => fetchRecommendation(message.problemId, message.profile, run))
  }

  function compareAlternatives(message) {
    runAction(async (run) => {
      const id = newId('m')
      setMessages((current) => [...current, { id, kind: 'alternatives', state: 'loading', forResult: message.id }])
      try {
        const { recommendation, problemId, profile: currentProfile } = message
        const winner = recommendation.winner_tool_id
        const skip = new Set([winner, ...memoryRef.current.ruled_out])
        const idsFrom = (found) => [...found.options, ...found.check_first].map((option) => option.tool_id).filter((toolId) => !skip.has(toolId))
        let others = idsFrom(recommendation)
        if (others.length < 2 && currentProfile.owned.some((entry) => entry.tool_id === winner)) {
          const asNewBuyer = await api.recommend({ ...currentProfile, owned: currentProfile.owned.filter((entry) => entry.tool_id !== winner) }, problemId)
          others = [...new Set([...others, ...idsFrom(asNewBuyer)])]
        }
        others = others.slice(0, 2)
        if (run !== runRef.current) return
        if (!others.length) {
          replaceMessage(id, { kind: 'alternatives', state: 'none', forResult: message.id })
          return
        }
        const comparison = await api.compare(currentProfile, [problemId], [winner, ...others].filter(Boolean).slice(0, 3))
        if (run !== runRef.current) return
        replaceMessage(id, { kind: 'alternatives', state: 'ready', comparison, forResult: message.id })
      } catch {
        if (run === runRef.current) replaceMessage(id, { kind: 'error', text: "I couldn't check alternatives just now. Try again in a moment." })
      }
    })
  }

  function savePlan(message) {
    runAction(async (run) => {
      const id = newId('m')
      setMessages((current) => [...current, { id, kind: 'loading' }])
      try {
        const requestId = newRequestId()
        const plan = await withOwner(api, (token) => api.savePlan(token, message.profile, [message.problemId], [message.recommendation.winner_tool_id], requestId))
        if (run !== runRef.current) return
        replaceMessage(id, { kind: 'saved-plan', plan, forResult: message.id })
      } catch {
        if (run === runRef.current) replaceMessage(id, { kind: 'error', text: "I couldn't save the plan just now. Your results are still here. Try again in a moment." })
      }
    })
  }

  function askAnother() {
    addMessage({ kind: 'assistant', text: "Sure. What else is getting in the way? Tell me in your own words, and I'll keep what I know about your business." })
    inputRef.current?.focus()
  }

  function quickReplies() {
    if (busy) return []
    const last = [...messages].reverse().find((message) => message.kind !== 'loading')
    if (!last || ['clarify', 'draft-builder', 'user'].includes(last.kind)) return []
    const result = latestResult(messages)
    if (!result) {
      return last.kind === 'assistant'
        ? STARTERS.map((starter) => ({ label: starter, run: () => send(starter) }))
        : []
    }
    const { recommendation } = result
    const winner = recommendation.winner_tool_id
    const saved = messages.some((message) => message.kind === 'saved-plan' && message.forResult === result.id)
    const compared = messages.some((message) => message.kind === 'alternatives' && message.forResult === result.id)
    const drafted = messages.some((message) => message.kind === 'draft')
    const choices = recommendation.options.length + recommendation.check_first.length
    return [
      winner && !saved && { label: 'Save this plan', run: () => savePlan(result) },
      !compared && (winner || choices > 1) && { label: 'Compare alternatives', run: () => compareAlternatives(result) },
      !drafted && { label: 'Build a custom assistant', run: () => openBuilder(result.problemTitle) },
      { label: 'Ask about another problem', run: askAnother },
    ].filter(Boolean)
  }

  function openBuilder(topic) {
    setMessages((current) => [...current.filter((item) => item.kind !== 'draft-builder'), { id: newId('m'), kind: 'draft-builder', topic }])
  }

  function buildDraft(builderId, draft) {
    setMessages((current) => [...current.filter((item) => item.id !== builderId), { id: newId('m'), kind: 'draft', draft }])
  }

  function forget({ field, id }) {
    setMemory((current) => {
      if (id) return { ...current, [field]: current[field].filter((item) => item !== id) }
      if (field === 'trade') return { ...current, trade: null }
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
      <section className="msc-panel" role="dialog" aria-label="Chat with Penny" hidden={!open} ref={drag.ref} style={phone ? undefined : drag.style}>
        <header className={`msc-header${phone ? '' : ' msc-drag-handle'}`} {...(phone ? {} : drag.handleProps)}>
          <div className="msc-identity">
            <PennyAvatar size={44} state={busy ? 'thinking' : speaking ? 'speaking' : 'idle'} />
            <div className="msc-title">
              <h2>Penny</h2>
              <p><span className={live ? 'msc-live' : 'msc-demo'}>{live ? 'Live AI' : 'Demo mode'}</span> Your AI guide</p>
            </div>
          </div>
          <div className="msc-header-actions">
            {!phone && (
              <button type="button" className="msc-move" data-drag-ok onKeyDown={drag.onKeyDown} aria-label="Move chat window with arrow keys" title="Drag the top bar, or use arrow keys here">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3" /></svg>
              </button>
            )}
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
            if (message.kind === 'loading') return null
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
            if (message.kind === 'alternatives') return <AlternativesCard key={message.id} message={message} />
            if (message.kind === 'saved-plan') return <SavedPlanCard key={message.id} plan={message.plan} />
            if (message.kind === 'draft') return <DraftCard key={message.id} draft={message.draft} />
            if (message.kind === 'draft-builder') {
              return (
                <DraftBuilder
                  key={message.id}
                  topic={message.topic}
                  disabled={busy}
                  onBuild={(draft) => buildDraft(message.id, draft)}
                  onCancel={() => setMessages((current) => current.filter((item) => item.id !== message.id))}
                />
              )
            }
            if (message.kind !== 'result') return null
            const latest = message.id === lastResultId
            const askPlan = latest && message.recommendation.options.concat(message.recommendation.check_first).find((option) => (
              PLAN_ROUTES.includes(option.route)
              && !(option.tool_id in memory.plans)
              && planChoices(toolsById[option.tool_id]).length
              && !isSingleOffering(toolsById[option.tool_id])
            ))
            return (
              <div className="msc-result-block" key={message.id}>
                <ChatResult
                  recommendation={message.recommendation}
                  statuses={message.statuses}
                  ruledOut={memory.ruled_out}
                  onPrint={() => setPrintData({ ...message, isDemo: !live })}
                />
                {askPlan && (
                  <PlanQuestion
                    toolName={askPlan.tool_name}
                    choices={planChoices(toolsById[askPlan.tool_id])}
                    disabled={busy}
                    onPick={(plan) => pickPlan(message, askPlan.tool_id, plan)}
                  />
                )}
              </div>
            )
          })}

          {busy && (
            <div className="msc-typing" role="status">
              <PennyAvatar size={28} state="thinking" />
              <span className="msc-dots" aria-hidden="true"><i /><i /><i /></span>
              <small>{slow ? 'Still working. Thanks for waiting.' : status || 'Penny is typing'}</small>
            </div>
          )}
        </div>

        {quick.length > 0 && (
          <div className="msc-quick" aria-label="Suggested replies">
            {quick.map((item) => <button type="button" key={item.label} onClick={item.run}>{item.label}</button>)}
          </div>
        )}

        <form className="msc-form" onSubmit={submit} noValidate>
          {(inputError || notice) && <p className="msc-input-note" role="alert">{inputError || notice}</p>}
          <div className="msc-input-row">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              maxLength={MAX_LENGTH}
              placeholder="Tell Penny what's going on"
              aria-label="Tell Penny what's going on"
              onChange={(event) => {
                setInput(event.target.value)
                setInputError('')
              }}
              onInput={(event) => {
                event.currentTarget.style.height = 'auto'
                event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 120)}px`
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
            <button type="submit" className="msc-send" disabled={busy} aria-label="Send message">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            </button>
          </div>
        </form>
      </section>
      <ChatSummary data={printData} />
    </>
  )
}

const GREETING_KEY = 'main-street-penny-greeting-closed-v1'

function greetingClosed() {
  try {
    return window.sessionStorage.getItem(GREETING_KEY) === '1'
  } catch {
    return false
  }
}

function ChatPanelInner({ profile }) {
  const [open, setOpen] = useState(false)
  const [showGreeting, setShowGreeting] = useState(() => !greetingClosed())
  const phone = useIsPhone()
  const bubble = useDraggable({ storageKey: 'main-street-penny-bubble-v1' })
  const chatWindow = useDraggable({ storageKey: 'main-street-penny-window-v1', enabled: !phone })
  const launcher = useRef(null)
  const wasOpen = useRef(false)
  const anchor = useRef(null)
  const close = useMemo(() => () => setOpen(false), [])

  useEffect(() => {
    if (wasOpen.current && !open) launcher.current?.focus()
    wasOpen.current = open
  }, [open])

  useEffect(() => {
    if (!open || chatWindow.position || !bubble.position || !anchor.current) return undefined
    const frame = requestAnimationFrame(() => chatWindow.placeNear(anchor.current))
    return () => cancelAnimationFrame(frame)
  }, [open, chatWindow, bubble.position])

  function hideGreeting() {
    setShowGreeting(false)
    try {
      window.sessionStorage.setItem(GREETING_KEY, '1')
    } catch {
      // Not remembering this only means the greeting shows again.
    }
  }

  function openChat() {
    if (bubble.wasDragged()) return
    anchor.current = bubble.ref.current?.getBoundingClientRect() || null
    hideGreeting()
    setOpen(true)
  }

  const spot = bubble.position
  const nearTop = spot ? spot.y < 170 : false
  const nearLeft = spot ? spot.x < 260 : false

  return (
    <div className="msc-root">
      {!open && (
        <div className="msc-bubble" ref={bubble.ref} style={bubble.style} {...bubble.handleProps}>
          {showGreeting && (
            <div className={`msc-greeting${nearTop ? ' msc-greeting-below' : ''}${nearLeft ? ' msc-greeting-right' : ''}`}>
              <button type="button" className="msc-greeting-text" onClick={openChat}>
                Hi, I'm Penny. How can I help you today?
              </button>
              <button type="button" className="msc-greeting-close" onClick={hideGreeting} aria-label="Hide Penny's greeting">×</button>
            </div>
          )}
          <button
            type="button"
            className="msc-launcher"
            data-drag-ok
            ref={launcher}
            onClick={openChat}
            onKeyDown={bubble.onKeyDown}
            aria-label="Chat with Penny. Drag to move, or use arrow keys."
            title="Chat with Penny. Drag to move."
          >
            <PennyAvatar size={56} />
          </button>
        </div>
      )}
      <Panel profile={profile} open={open} onClose={close} drag={chatWindow} phone={phone} />
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
