import React, { useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { api, newRequestId } from '../api'
import { DraftBuilder, DraftCard } from './AssistantDraft'
import { createChatAdapter, EMPTY_MEMORY, loadCatalog } from './chatAdapter'
import ChatErrorBoundary from './ChatErrorBoundary'
import ChatResult, { safeUrl } from './ChatResult'
import { clearSession, historyFor, loadSession, memoryForRequest, newConversationId, saveSession, visibleMessages } from './chatSession'
import { queueHistory, deleteSavedHistory } from './historyCache'
import ChatSummary from './ChatSummary'
import PennyAvatar from './PennyAvatar'
import PennyMemory from './PennyMemory'
import { AlternativesCard, SavedPlanCard } from './ResultExtras'
import SpeechInput from './SpeechInput'
import { useDraggable, useIsPhone } from './useDraggable'
import './chat.css'

const ACTION_LABELS = {
  succeeded: 'Done.',
  failed: 'That step did not work. Nothing was changed for you.',
  not_executed: 'That step did not run. Nothing was changed for you.',
  unconfirmed: 'We could not confirm that step finished. Please check before relying on it.',
}

// Why the safety check before sending failed, in words the owner can act on.
export function checkFailureMessage(error) {
  const status = error?.status
  const detail = typeof error?.detail === 'string' ? error.detail : ''
  if (error?.offline) return "We could not check this message safely because Penny can't reach the server. Check your connection, then try again."
  if (status === 401) return 'Your sign-in has expired. Sign in again to keep chatting with Penny.'
  if (status === 429) return "That's a lot of messages in a short time. Wait a minute, then try again."
  if (status === 503 && /account verification/i.test(detail)) return "We couldn't check your sign-in right now. Try again in a moment, or sign out to chat as a guest."
  if (status === 422) return "That message couldn't be sent. Start a new chat, then try again."
  return 'We could not check this message safely. Please try again, or use the tool finder.'
}

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
import { OTHER_CHOICE, otherHint } from './choices'
const WANTS_ASSISTANT = /\b(custom|own|build|make|create|draft)\b.*\b(assistant|helper|bot|chatbot)\b/i

// A recommendation can arrive as a plain result or as an A2UI recommendation card.
function resultInfo(message) {
  if (message?.kind === 'result' && message.recommendation?.problem_id) {
    return { id: message.id, recommendation: message.recommendation, problemTitle: message.problemTitle }
  }
  if (message?.kind === 'a2ui' && message.surface === 'recommendation') {
    const component = message.protocol?.[1]?.updateComponents?.components?.[0]
    const recommendation = component?.recommendation
    if (recommendation?.problem_id && Array.isArray(recommendation.options) && Array.isArray(recommendation.check_first)) {
      return { id: message.id, recommendation, problemTitle: component.problemTitle || 'Your problem' }
    }
  }
  return null
}

function latestResult(list) {
  for (let index = list.length - 1; index >= 0; index -= 1) {
    const info = resultInfo(list[index])
    if (info) return info
  }
  return null
}

let nextId = 0
const newId = (prefix) => `${prefix}_${Date.now()}_${nextId++}`

function Panel({ profile, auth, open, onClose, onActivityChange, drag, phone, handoff }) {
  const adapter = useMemo(() => createChatAdapter(), [])
  const [restored] = useState(() => auth?.configured ? null : loadSession(EMPTY_MEMORY))
  const [conversationId, setConversationId] = useState(() => restored?.conversationId || newConversationId())
  const [messages, setMessages] = useState(() => restored?.messages || [])
  const [memory, setMemory] = useState(() => restored?.memory || EMPTY_MEMORY)
  const [resumed, setResumed] = useState(() => Boolean(restored?.messages.length))
  const [hydratedFor, setHydratedFor] = useState(null)
  const [historyReady, setHistoryReady] = useState(false)
  const [deletingHistory, setDeletingHistory] = useState(false)
  const [names, setNames] = useState({ tools: {}, trades: {}, urls: {} })
  const [live, setLive] = useState(null)
  const [speaking, setSpeaking] = useState(false)
  const [input, setInput] = useState('')
  const [typingHint, setTypingHint] = useState('')
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
  const handledHandoff = useRef(null)

  messagesRef.current = messages
  memoryRef.current = memory

  useEffect(() => {
    adapter.isLive().then(setLive).catch(() => setLive(false))
    if (auth?.configured) clearSession()
    loadCatalog()
      .then((data) => setNames({
        tools: Object.fromEntries(data.tools.map((tool) => [tool.id, tool.name])),
        trades: Object.fromEntries(data.trades.map((trade) => [trade.id, trade.name])),
        urls: Object.fromEntries(data.tools.map((tool) => [tool.id, tool.url])),
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
    if (userId && authToken && hydratedFor === userId && historyReady && !deletingHistory) {
      queueHistory(authToken, { conversationId, messages: messages.filter((item) => item.kind !== 'loading').slice(-40), memory }).catch(() => {
        setNotice('Penny could not save this short chat history. Please try again before signing out.')
      })
    }
  }, [auth?.configured, userId, authToken, hydratedFor, historyReady, deletingHistory, conversationId, messages, memory])

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    drag.reclamp()
  }, [open, drag])

  useEffect(() => {
    if (!input && inputRef.current) inputRef.current.style.height = ''
  }, [input])

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

  function printSummary(data) {
    // Keep printing in the click's user activation, after the portal is committed.
    // The visible preview remains available if this browser blocks native print.
    flushSync(() => setPrintData(data))
    try { window.print() } catch { /* The preview includes browser-menu guidance. */ }
  }

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

  // "Other": nothing is sent. The owner types their own answer, with a hint that fits the question.
  function typeOwnAnswer(question) {
    setTypingHint(otherHint(question))
    setInputError('')
    inputRef.current?.focus()
  }

  // A page selection is already a resolved catalog task. Load its actual results
  // directly, after account hydration, and carry the same context into live chat.
  useEffect(() => {
    if (!handoff || handledHandoff.current === handoff.key || busy || deletingHistory) return
    if (auth?.configured && (!auth.ready || (userId && hydratedFor !== userId))) return
    handledHandoff.current = handoff.key
    const run = begin()
    const selectedProfile = handoff.profile
    loadCatalog().then(async (catalog) => {
      if (run !== runRef.current) return
      const tasks = handoff.problemIds.map(id => catalog.problems.find(problem => problem.id === id)).filter(Boolean)
      if (!tasks.length) return
      setMemory(current => ({
        ...current,
        trade: selectedProfile.trade || null,
        owned: selectedProfile.owned.map(entry => entry.tool_id),
        plans: Object.fromEntries(selectedProfile.owned.filter(entry => entry.plan).map(entry => [entry.tool_id, entry.plan])),
        budget_monthly_usd: selectedProfile.budget_monthly_usd ?? null,
        active_task_ids: tasks.map(task => task.id),
        pending_question: null,
        pending_task_ids: [],
        background_done: true,
      }))
      setResumed(false)
      addMessage({ kind: 'user', text: `Help me with my selected ${tasks.length === 1 ? 'task' : 'tasks'}: ${tasks.map(task => task.title).join('; ')}.` })
      await Promise.all(tasks.map(task => fetchRecommendation(task.id, selectedProfile, run)))
    }).catch(() => {
      if (run === runRef.current) setNotice('Could not load your selected tasks. Your selections are still on the page. Please try again.')
    }).finally(() => finish(run))
  }, [handoff, auth?.configured, auth?.ready, userId, hydratedFor, busy, deletingHistory])

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
    if (!isRetry && WANTS_ASSISTANT.test(text)) {
      setMessages((current) => [...current, { id: newId('m'), kind: 'user', text }, { id: newId('m'), kind: 'draft-builder', topic: '' }])
      setInput('')
      setTypingHint('')
      setInputError('')
      setResumed(false)
      return
    }
    const run = begin()
    setInputError('')
    try {
      const validation = await api.validateChat({ conversation_id: conversationId, message: text, profile, memory: memoryForRequest(memory), history: historyFor(messagesRef.current, { dropLastUser: isRetry }) }, authToken)
      if (run !== runRef.current) return
      if (!validation.allowed) { setInputError(validation.message); finish(run); return }
    } catch (error) {
      if (error?.status === 422 && Array.isArray(error.detail)) {
        // Dynamic dictionary keys in error locations may themselves contain private data.
        console.warn('Penny: request validation failed; rejected field count:', error.detail.length)
      }
      setInputError(checkFailureMessage(error))
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
      setTypingHint('')
    }

    function onEvent(event) {
      if (run !== runRef.current) return
      if (receivedA2UIRecommendation && event.validation === 'validated' && event.presentation === 'recommendation_evidence') {
        return
      }
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
      if (event.type === 'action' && ACTION_LABELS[event.status]) addMessage({ kind: 'action', status: event.status, text: event.message || ACTION_LABELS[event.status] })
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
      await adapter.sendMessage({ conversationId, message: text, profile, memory: memoryForRequest(memoryRef.current), history, isRetry, accessToken: authToken, signal: abortRef.current.signal }, onEvent)
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
    setTypingHint('')
    setInputError('')
    setNotice('')
    inputRef.current?.focus()
  }

  async function deleteHistory() {
    if (!authToken || !historyReady || busyRef.current || deletingHistory) return
    const run = begin()
    setDeletingHistory(true)
    try {
      await deleteSavedHistory(authToken)
      if (run !== runRef.current) return
      startOver()
      setNotice('Your saved chat history was deleted. Your favourite tools are unchanged.')
    } catch {
      if (run === runRef.current) setNotice('Could not delete your chat history. Please retry.')
    } finally {
      if (run === runRef.current) finish(run)
      setDeletingHistory(false)
    }
  }

  // The owner's details as Penny knows them, for comparing or saving outside the chat stream.
  function currentProfile() {
    const known = memoryRef.current
    const owned = [...(profile?.owned || [])]
    ;(known.owned || []).forEach((toolId) => {
      if (!owned.some((entry) => entry.tool_id === toolId)) owned.push({ tool_id: toolId })
    })
    return {
      trade: known.trade || profile?.trade || null,
      owned: owned.map(entry => ({ ...entry, plan: entry.plan || known.plans?.[entry.tool_id] || null })),
      budget_monthly_usd: known.budget_monthly_usd ?? profile?.budget_monthly_usd ?? null,
    }
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

  function compareAlternatives(info) {
    runAction(async (run) => {
      const id = newId('m')
      setMessages((current) => [...current, { id, kind: 'alternatives', state: 'loading', forResult: info.id }])
      try {
        const { recommendation } = info
        const problemId = recommendation.problem_id
        const owner = currentProfile()
        const winner = recommendation.winner_tool_id
        const skip = new Set([winner, ...(memoryRef.current.ruled_out || [])])
        const idsFrom = (found) => [...found.options, ...found.check_first].map((option) => option.tool_id).filter((toolId) => !skip.has(toolId))
        let others = idsFrom(recommendation)
        if (others.length < 2 && owner.owned.some((entry) => entry.tool_id === winner)) {
          const asNewBuyer = await api.recommend({ ...owner, owned: owner.owned.filter((entry) => entry.tool_id !== winner) }, problemId)
          others = [...new Set([...others, ...idsFrom(asNewBuyer)])]
        }
        others = others.slice(0, 2)
        if (run !== runRef.current) return
        if (!others.length) {
          replaceMessage(id, { kind: 'alternatives', state: 'none', forResult: info.id })
          return
        }
        const comparison = await api.compare(owner, [problemId], [winner, ...others].filter(Boolean).slice(0, 3))
        if (run !== runRef.current) return
        replaceMessage(id, { kind: 'alternatives', state: 'ready', comparison, forResult: info.id })
      } catch {
        if (run === runRef.current) replaceMessage(id, { kind: 'error', text: "I couldn't check alternatives just now. Try again in a moment." })
      }
    })
  }

  function savePlan(info) {
    const winner = info.recommendation.winner_tool_id
    if (!winner) {
      addMessage({ kind: 'assistant', text: "I can't save a plan until one tool is confirmed. Want me to compare the options first?" })
      return
    }
    if (!authToken) {
      addMessage({
        kind: 'assistant',
        text: auth?.configured
          ? 'Sign in with your account to save plans. Your chat stays right here.'
          : "Saving plans needs an account, and accounts aren't set up on this server yet.",
      })
      return
    }
    runAction(async (run) => {
      const id = newId('m')
      setMessages((current) => [...current, { id, kind: 'loading' }])
      try {
        const plan = await api.savePlan(authToken, currentProfile(), [info.recommendation.problem_id], [winner], newRequestId())
        if (run !== runRef.current) return
        replaceMessage(id, { kind: 'saved-plan', plan, forResult: info.id })
      } catch {
        if (run === runRef.current) replaceMessage(id, { kind: 'error', text: "I couldn't save the plan just now. Your results are still here. Try again in a moment." })
      }
    })
  }

  function askAnother() {
    addMessage({ kind: 'assistant', text: "Sure. What else is getting in the way? Tell me in your own words, and I'll keep what I know about your business." })
    inputRef.current?.focus()
  }

  function openBuilder(topic) {
    setMessages((current) => [...current.filter((item) => item.kind !== 'draft-builder'), { id: newId('m'), kind: 'draft-builder', topic }])
  }

  function buildDraft(builderId, draft) {
    setMessages((current) => [...current.filter((item) => item.id !== builderId), { id: newId('m'), kind: 'draft', draft }])
  }

  function quickReplies() {
    if (busy) return []
    const last = [...messages].reverse().find((message) => message.kind !== 'loading')
    if (!last || ['clarify', 'draft-builder', 'user'].includes(last.kind) || (last.kind === 'a2ui' && last.surface === 'question')) return []
    const result = latestResult(messages)
    if (!result) return []
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

  const quick = quickReplies()

  function forget({ field, id }) {
    setMemory((current) => {
      if (id && field === 'owned') {
        const plans = { ...(current.plans || {}) }
        delete plans[id]
        return { ...current, owned: current.owned.filter((item) => item !== id), plans }
      }
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
      <section className="msc-panel" id="penny-chat-panel" role="dialog" aria-label="Chat with Penny" hidden={!open} ref={drag.ref} style={phone ? undefined : drag.style}>
        <header className={`msc-header${phone ? '' : ' msc-drag-handle'}`} {...(phone ? {} : drag.handleProps)}>
          <div className="msc-identity">
            <span className="penny-panel-mark" data-state={avatarState} aria-hidden="true"><PennyAvatar size={36} state={avatarState} /><span /></span>
            <div className="penny-panel-heading">
              <span className="penny-panel-eyebrow">MAIN STREET / ASSISTANT</span>
              <h2>Penny</h2>
              <span className={live ? 'msc-live' : 'msc-unavailable'}>{live === null ? 'Checking connection' : live ? 'Live AI' : 'Unavailable'}</span>
            </div>
          </div>
          <div className="msc-header-actions">
            {!phone && (
              <button type="button" className="msc-move" data-drag-ok onKeyDown={drag.onKeyDown} aria-label="Move chat window with arrow keys" title="Drag the top bar, or use arrow keys here">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3" /></svg>
              </button>
            )}
            <button type="button" className="msc-text-button" onClick={startOver} disabled={deletingHistory}>New chat</button>
            <button type="button" className="msc-close" onClick={onClose} aria-label="Close chat">×</button>
          </div>
        </header>

        <details className="penny-boundaries"><summary>What Penny will not do</summary><p>Penny will not buy or connect tools, handle payments, reveal private instructions, or accept phone numbers and email addresses. She uses catalog evidence, which means facts we have checked, and tells you when something is unknown.</p></details>
        {live === false && <p className="penny-unavailable-note" role="status">Penny is currently unavailable. You can still browse or compare tools while the connection is restored.</p>}
        <PennyMemory memory={memory} names={names} onRemove={forget} />
        {userId && <div className="msc-history-controls"><span>History kept for up to 30 days</span><button type="button" onClick={deleteHistory} disabled={busy || !historyReady}>{deletingHistory ? 'Deleting…' : 'Delete history'}</button></div>}

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

          {visibleMessages(messages).map((message) => {
            if (message.kind === 'user') return <div className="msc-row msc-row-user" key={message.id}><p>{message.text}</p></div>
            if (message.kind === 'assistant') return <div className="msc-row" key={message.id}><span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} /></span><p>{message.text}</p></div>
            if (message.kind === 'a2ui') return <React.Suspense key={message.id} fallback={<div className="msc-loading">Loading result…</div>}><A2UISurface protocol={message.protocol} onSelect={send} onOther={typeOwnAnswer} busy={busy} ruledOut={memory.ruled_out} serviceUrls={names.urls} onPrint={printSummary} /></React.Suspense>
            if (message.kind === 'loading') return <div className="msc-loading" key={message.id}>Checking the catalog...</div>
            if (message.kind === 'clarify') {
              return (
                <div className="msc-row msc-clarify" key={message.id}>
                  {message.progress && <span className="msc-progress">{message.progress}</span>}
                  <div className="msc-clarify-question"><span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} /></span><p>{message.text}</p></div>
                  <div className="msc-choices">
                    {message.choices.map((choice) => <button type="button" key={choice} onClick={() => (choice === OTHER_CHOICE ? typeOwnAnswer(message.text) : send(choice))} disabled={busy}>{choice}</button>)}
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
            if (message.kind === 'action') return <p className="msc-action" data-status={message.status} role="status" key={message.id}>{message.text}</p>
            if (message.kind === 'alternatives') return <AlternativesCard key={message.id} message={message} serviceUrls={names.urls} />
            if (message.kind === 'saved-plan') return <SavedPlanCard key={message.id} plan={message.plan} serviceUrls={names.urls} />
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
                serviceUrls={names.urls}
                ruledOut={memory.ruled_out}
                onPrint={() => printSummary(message)}
              />
            )
          })}

          {busy && (
            <div className="msc-typing" role="status">
              <span className="penny-message-mark" aria-hidden="true"><PennyAvatar size={24} state="thinking" /></span>
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
              placeholder={typingHint || "Type what is slowing you down..."}
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
            <button type="submit" className="msc-send" disabled={busy}>{busy ? 'Working' : 'Send'}</button>
          </div>
          <p className="penny-composer-note">Penny uses checked facts. Confirm prices with the company before you pay.</p>
        </form>
      </section>
      <ChatSummary data={printData} serviceUrls={names.urls} onClose={() => setPrintData(null)} onPrint={() => printSummary(printData)} />
    </>
  )
}

const LAUNCHER_KEY = 'main-street-penny-launcher-v1'

function savedLauncher() {
  try {
    const mode = window.sessionStorage.getItem(LAUNCHER_KEY)
    return mode === 'hidden' ? 'hidden' : 'figure'
  } catch {
    return 'figure'
  }
}

function ChatPanelInner({ profile, auth, pageProblemIds }) {
  const [open, setOpen] = useState(false)
  const [activity, setActivity] = useState('idle')
  const [handoff, setHandoff] = useState(null)
  const [launcherMode, setLauncherMode] = useState(savedLauncher)
  const showFigure = launcherMode === 'figure' && !open
  const phone = useIsPhone()
  const bubble = useDraggable({ storageKey: 'main-street-penny-bubble-v1' })
  const chatWindow = useDraggable({ storageKey: 'main-street-penny-window-v1', enabled: !phone })
  const launcher = useRef(null)
  const wasOpen = useRef(false)
  const anchor = useRef(null)
  const close = useMemo(() => () => setOpen(false), [])

  const returnFocus = useRef(false)

  useEffect(() => {
    if (wasOpen.current && !open) {
      returnFocus.current = true
    }
    wasOpen.current = open
  }, [open])

  // Runs after the launcher has re-rendered, so focus lands on the button that is actually on screen.
  useEffect(() => {
    if (!returnFocus.current || open || !launcher.current) return
    returnFocus.current = false
    launcher.current.focus()
  })

  function changeLauncher(mode) {
    setLauncherMode(mode)
    try {
      window.sessionStorage.setItem(LAUNCHER_KEY, mode)
    } catch {
      // Only remembered for convenience.
    }
  }

  useEffect(() => {
    if (!open || chatWindow.position || !bubble.position || !anchor.current) return undefined
    const frame = requestAnimationFrame(() => chatWindow.placeNear(anchor.current))
    return () => cancelAnimationFrame(frame)
  }, [open, chatWindow, bubble.position])

  useEffect(() => {
    function openFromPage(event) {
      anchor.current = bubble.ref.current?.getBoundingClientRect() || null
      takeSelection(event.detail)
      setOpen(true)
    }
    window.addEventListener('penny:open', openFromPage)
    return () => window.removeEventListener('penny:open', openFromPage)
  }, [bubble.ref, profile, pageProblemIds])

  function takeSelection(selection = {}) {
    const problemIds = [...new Set(selection?.problemIds || pageProblemIds || [])].filter(id => typeof id === 'string').slice(0, 3)
    if (!problemIds.length) return
    const sourceProfile = selection?.profile || profile
    const selectedProfile = { trade: sourceProfile.trade || null, owned: sourceProfile.owned || [], budget_monthly_usd: sourceProfile.budget_monthly_usd ?? null }
    const context = { problemIds, profile: selectedProfile }
    setHandoff({ ...context, key: JSON.stringify(context) })
  }

  function openChat() {
    if (bubble.wasDragged()) return
    anchor.current = bubble.ref.current?.getBoundingClientRect() || null
    takeSelection()
    setOpen(true)
  }

  return (
    <div className="msc-root">
      {!open && launcherMode === 'hidden' && (
        <button type="button" className="penny-show-tab" ref={launcher} onClick={() => changeLauncher('figure')} aria-label="Show Penny, your AI guide">
          <PennyAvatar size={28} />
          <span>Penny</span>
        </button>
      )}
      {!open && launcherMode !== 'hidden' && (
        <div className={`msc-bubble${showFigure ? '' : ' msc-bubble-compact'}`} ref={bubble.ref} style={bubble.style} {...bubble.handleProps}>
          {showFigure ? (
            <button type="button" className={`msc-launcher penny-character-launcher penny-is-${activity}`} data-drag-ok ref={launcher} onClick={openChat} onKeyDown={bubble.onKeyDown} aria-label="Talk to Penny. Drag to move, or use arrow keys." title="Talk to Penny. Drag to move." aria-expanded={open} aria-controls="penny-chat-panel">
              <span className="penny-speech"><strong>Hi, I'm Penny.</strong><span>{activity === 'thinking' ? 'Checking the catalog...' : activity === 'speaking' ? 'Your answer is coming in' : 'Ask me what is slowing you down.'}</span></span>
              <span className="penny-character-stage"><span className="penny-stage-glow" aria-hidden="true" /><PennyAvatar size={130} variant="figure" state={activity} /></span>
              <span className="penny-nameplate"><span className="penny-presence" aria-hidden="true" />Talk to Penny <span aria-hidden="true">&#8599;</span></span>
            </button>
          ) : (
            <button type="button" className="penny-compact-launcher" data-drag-ok ref={launcher} onClick={openChat} onKeyDown={bubble.onKeyDown} aria-label="Talk to Penny, your AI guide. Drag to move, or use arrow keys." title="Talk to Penny" aria-expanded={open} aria-controls="penny-chat-panel">
              <PennyAvatar size={48} state={activity} />
              <span className="penny-compact-label">Ask Penny</span>
            </button>
          )}
          <button type="button" className="penny-hide" onClick={() => changeLauncher('hidden')} aria-label="Hide Penny" title="Hide Penny">×</button>
        </div>
      )}
      <Panel key={auth?.configured ? auth.user?.id || 'signed-out' : 'guest'} profile={profile} auth={auth} open={open} onClose={close} onActivityChange={setActivity} drag={chatWindow} phone={phone} handoff={handoff} />
    </div>
  )
}

function ChatPanel({ profile = {}, auth, pageProblemIds = [] }) {
  return (
    <ChatErrorBoundary>
      <ChatPanelInner key={auth?.configured ? auth.user?.id || 'signed-out' : 'guest'} profile={profile} auth={auth} pageProblemIds={pageProblemIds} />
    </ChatErrorBoundary>
  )
}

export default ChatPanel
