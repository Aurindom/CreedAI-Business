import { api } from '../api.js'
import { detectMentionedTools, detectOwnedTools, detectRuledOutTools, detectTrade, matchProblem, normalize, parseBudget, suggestedProblems } from './matchProblem.js'

const UNAVAILABLE = 'Penny is unavailable right now. You can still browse and compare tools on this page.'
const SOMETHING_ELSE = 'Something else'
const SKIP = 'Skip these questions'
const GET_STARTED = 'Start with a few questions'
const INTAKE_QUESTIONS = {
  trade: { question: 'First, what kind of business do you run?', choices: ['Coffee shop', 'Restaurant', 'HVAC', 'Landscaping or lawn care', SOMETHING_ELSE, SKIP] },
  software: { question: 'What software do you already pay for? Pick the main one.', choices: ['Square for Restaurants', 'QuickBooks Online', 'Jobber', 'Google Business Profile', 'None of these', SKIP] },
  budget: { question: 'Roughly what could you spend each month on a new tool?', choices: ['Free only', 'Under $25', 'Under $50', 'Under $100', 'Not sure', SKIP] },
}

export const EMPTY_MEMORY = { trade: null, owned: [], ruled_out: [], budget_monthly_usd: null, background_done: false }

function chatMode() {
  const mode = import.meta.env?.VITE_CHAT_MODE
  return mode === 'http' || mode === 'mock' ? mode : 'auto'
}

let catalog = null

// Reads the same public catalog the rest of the site uses.
export async function loadCatalog() {
  if (!catalog) {
    catalog = Promise.all([api.trades(), api.problems(), api.tools()])
      .then(([trades, problems, tools]) => ({ trades, problems, tools }))
      .catch((error) => {
        catalog = null
        throw error
      })
  }
  return catalog
}

function mergeProfile(profile, memory) {
  const owned = [...(profile?.owned || [])]
  const ownedIds = [...(profile?.owned_tool_ids || []), ...memory.owned]
  ownedIds.forEach((tool_id) => {
    if (!owned.some((entry) => entry.tool_id === tool_id)) owned.push({ tool_id })
  })
  const { owned_tool_ids: _unused, ...rest } = profile || {}
  return {
    ...rest,
    trade: memory.trade || profile?.trade || null,
    owned,
    ...(memory.budget_monthly_usd === null || memory.budget_monthly_usd === undefined ? {} : { budget_monthly_usd: memory.budget_monthly_usd }),
  }
}

export function createMockAdapter({ delayMs = 350, slowMs = 9000, load = loadCatalog } = {}) {
  const lastProblems = new Map()
  const intakes = new Map()
  const failures = new Set()
  const wait = (ms = delayMs) => new Promise((resolve) => setTimeout(resolve, ms))

  async function say(text, onEvent) {
    onEvent({ type: 'message_delta', text })
    await wait(delayMs / 2)
  }

  async function recommend(conversationId, problem, profile, memory, intro, onEvent) {
    lastProblems.set(conversationId, problem)
    await say(intro, onEvent)
    onEvent({ type: 'status', text: 'Penny is checking the catalog' })
    await wait()
    onEvent({ type: 'recommendation', problem_id: problem.id, profile: mergeProfile(profile, memory) })
    onEvent({ type: 'done' })
  }

  async function sendMessage({ conversationId, message, profile, memory: given, isRetry = false }, onEvent) {
    const text = normalize(message)
    onEvent({ type: 'status', text: 'Penny is reading that' })
    await wait()

    if (text === 'offline') {
      onEvent({ type: 'error', code: 'agent_unavailable', message: UNAVAILABLE, retryable: false })
      onEvent({ type: 'done' })
      return
    }
    if (text === 'fail' && !isRetry && !failures.has(conversationId)) {
      failures.add(conversationId)
      await say('Let me look into that.', onEvent)
      onEvent({ type: 'error', code: 'demo_failure', message: 'Something interrupted my reply. Try again.', retryable: true })
      onEvent({ type: 'done' })
      return
    }
    if (text === 'slow reply') await wait(slowMs)

    let data
    try {
      data = await load()
    } catch {
      onEvent({ type: 'error', code: 'agent_unavailable', message: UNAVAILABLE, retryable: true })
      onEvent({ type: 'done' })
      return
    }

    const before = { ...EMPTY_MEMORY, ...given }
    const newTrade = detectTrade(message, data.trades)
    const owned = detectOwnedTools(message, data.tools)
    const ruledOut = detectRuledOutTools(message, data.tools)
    const memory = {
      ...before,
      trade: newTrade || before.trade,
      owned: [...new Set([...before.owned, ...owned])].filter((id) => !ruledOut.includes(id)),
      ruled_out: [...new Set([...before.ruled_out, ...ruledOut])].filter((id) => !owned.includes(id)),
    }
    const learned = memory.trade !== before.trade
      || memory.owned.length !== before.owned.length
      || memory.ruled_out.length !== before.ruled_out.length
    const trade = memory.trade || profile?.trade || null
    const lastProblem = lastProblems.get(conversationId)
    const intake = intakes.get(conversationId)

    function stepsLeft() {
      return [
        ...(memory.trade || profile?.trade ? [] : ['trade']),
        ...(memory.owned.length || profile?.owned?.length || profile?.owned_tool_ids?.length ? [] : ['software']),
        ...(memory.budget_monthly_usd !== null && memory.budget_monthly_usd !== undefined ? [] : ['budget']),
      ]
    }

    async function askNext(state, intro) {
      const step = state.steps[state.index]
      if (intro) await say(intro, onEvent)
      const { question, choices } = INTAKE_QUESTIONS[step]
      onEvent({ type: 'clarify', question, choices, progress: `Question ${state.index + 1} of ${state.steps.length}` })
      onEvent({ type: 'done' })
    }

    async function finishIntake(state) {
      intakes.delete(conversationId)
      memory.background_done = true
      onEvent({ type: 'memory', memory })
      if (state.problem) {
        await recommend(conversationId, state.problem, profile, memory, "Thanks, that's what I needed. Here's what fits your business.", onEvent)
        return
      }
      onEvent({
        type: 'clarify',
        question: "Thanks. Now, what's taking up the most of your time?",
        choices: [...suggestedProblems(data.problems, memory.trade || profile?.trade || null).map((p) => p.title), SOMETHING_ELSE],
      })
      onEvent({ type: 'done' })
    }

    if (intake) {
      if (text === normalize(SKIP)) {
        await finishIntake(intake)
        return
      }
      const step = intake.steps[intake.index]
      if (step === 'software' && text !== 'none of these') {
        memory.owned = [...new Set([...memory.owned, ...detectMentionedTools(message, data.tools)])]
      }
      if (step === 'budget') {
        const budget = parseBudget(message)
        if (budget !== null) memory.budget_monthly_usd = budget
      }
      if (!intake.problem) {
        const answerMatch = matchProblem(message, data.problems, memory.trade || profile?.trade || null)
        if (answerMatch.result === 'confident') intake.problem = answerMatch.problem
      }
      onEvent({ type: 'memory', memory })
      intake.index += 1
      if (intake.index >= intake.steps.length) await finishIntake(intake)
      else await askNext(intake)
      return
    }

    if (learned) onEvent({ type: 'memory', memory })

    if (text === normalize(SOMETHING_ELSE)) {
      await say("I can't match that to a problem we've checked yet. You can browse every tool on this page, or tell me more in your own words.", onEvent)
      onEvent({ type: 'done' })
      return
    }

    const match = matchProblem(message, data.problems, trade)
    const wantsStart = text === normalize(GET_STARTED)
    if (!memory.background_done && text !== 'slow reply' && (wantsStart || !trade)) {
      const steps = stepsLeft()
      const state = { steps, index: 0, problem: match.result === 'confident' ? match.problem : null }
      if (steps.length) {
        intakes.set(conversationId, state)
        const count = steps.length === 1 ? 'one quick question' : `${steps.length} quick questions`
        await askNext(state, state.problem
          ? `I can help with "${state.problem.title}". First, ${count} so I can tailor this to you.`
          : `Happy to help. First, ${count} so I can tailor this to you.`)
        return
      }
      await finishIntake(state)
      return
    }
    if (match.result === 'confident') {
      await recommend(conversationId, match.problem, profile, memory, `Sounds like "${match.problem.title}". Let's see what's worth your money.`, onEvent)
      return
    }
    if (match.result === 'none' && learned && lastProblem) {
      await recommend(conversationId, lastProblem, profile, memory, "Good to know. I'll check that again with what you just told me.", onEvent)
      return
    }
    if (match.result === 'none' && learned) {
      await say("Got it, I'll keep that in mind.", onEvent)
    }
    if (match.result === 'unsure') {
      onEvent({ type: 'clarify', question: 'Which of these is closest?', choices: [...match.candidates.map((p) => p.title), SOMETHING_ELSE] })
      onEvent({ type: 'done' })
      return
    }
    onEvent({
      type: 'clarify',
      question: "What's taking up the most of your time?",
      choices: [...suggestedProblems(data.problems, trade).map((p) => p.title), SOMETHING_ELSE],
    })
    onEvent({ type: 'done' })
  }

  return { sendMessage }
}

export function createHttpAdapter({ fetcher = (...args) => fetch(...args) } = {}) {
  async function sendMessage({ conversationId, message, profile, memory, history }, onEvent) {
    const response = await fetcher('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ conversation_id: conversationId, message, profile, memory, history }),
    })
    if (!response.ok || !response.body) throw new Error(`Chat request failed with ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finished = false

    function handle(block) {
      const payload = block.split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n')
      if (!payload) return
      const event = JSON.parse(payload)
      if (event.type === 'done') finished = true
      onEvent(event)
    }

    while (!finished) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop()
      blocks.forEach(handle)
    }
    if (!finished && buffer.trim()) handle(buffer)
    if (!finished) throw new Error('The reply ended early')
  }

  return { sendMessage }
}

export async function checkLiveChat(fetcher = (...args) => fetch(...args)) {
  try {
    const response = await fetcher('/api/chat/status')
    if (!response.ok) return false
    return (await response.json()).available === true
  } catch {
    return false
  }
}

// Uses the real agent when it's available, and drops to Demo mode if it fails or hits a limit.
export function createResilientAdapter({ live, demo, checkLive }) {
  let liveState = null

  async function isLive() {
    if (liveState === null) liveState = await checkLive()
    return liveState
  }

  async function sendMessage(request, onEvent) {
    if (!(await isLive())) {
      await demo.sendMessage(request, onEvent)
      return
    }

    let failed = false
    let answered = false
    try {
      await live.sendMessage(request, (event) => {
        if (event.type === 'error' && event.fallback) failed = true
        if (failed) return
        if (['message_delta', 'recommendation', 'clarify'].includes(event.type)) answered = true
        onEvent(event)
      })
    } catch {
      failed = true
    }
    if (!failed) return

    liveState = false
    onEvent({ type: 'mode', live: false })
    if (answered) onEvent({ type: 'done' })
    else await demo.sendMessage(request, onEvent)
  }

  return { sendMessage, isLive }
}

export function createChatAdapter() {
  const mode = chatMode()
  return createResilientAdapter({
    live: createHttpAdapter(),
    demo: createMockAdapter(),
    checkLive: mode === 'auto' ? checkLiveChat : async () => mode === 'http',
  })
}
