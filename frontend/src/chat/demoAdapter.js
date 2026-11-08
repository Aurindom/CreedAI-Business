// Local Demo mode only. Turn it on with VITE_CHAT_MODE=demo. Production never uses scripted answers.
import { api } from '../api.js'
import { smallTalk } from './smallTalk.js'
import { detectMentionedTools, detectOwnedTools, detectRuledOutTools, detectTrade, matchProblem, normalize, parseBudget, suggestedProblems } from './matchProblem.js'

const UNAVAILABLE = 'Penny is unavailable right now. You can still browse and compare tools on this page.'
const SOMETHING_ELSE = 'Something else'
const SKIP = 'Skip these questions'
const GET_STARTED = 'Start with a few questions'
const ANOTHER_PROBLEM = 'A different problem'
const WORDS = (text) => (text ? text.split(' ').length : 0)
const INTENTS = {
  thanks: /\b(thanks|thank you|thx|appreciate it)\b|^(great|perfect|awesome|cool|nice|got it|ok great)$/,
  greeting: /^(hi|hello|hey|hiya|good (morning|afternoon|evening))\b/,
  yes: /^(yes|yeah|yep|sure|ok|okay|sounds good|please|yes please)$/,
  no: /^(no|nope|nah|not really|no thanks|not now)$/,
  another: /\b(another|different|new|other) (problem|issue|thing|question)\b|^a different problem$|^something else$/,
  compare: /\b(alternatives?|other options?|other tools?|compare|cheaper|instead|something else like)\b/,
  save: /\b(save|set (it|this|that) up|setup|set up|get started|next steps?)\b/,
  cost: /\b(cost|costs|price|prices|pricing|how much|expensive|cheap)\b/,
  question: /\?|^(what|how|does|do|is|can|tell me|what about|any)\b/,
}

const INTAKE_QUESTIONS = {
  trade: { question: 'First, what kind of business do you run?', choices: ['Coffee shop', 'Restaurant', 'HVAC', 'Landscaping or lawn care', SOMETHING_ELSE, SKIP] },
  software: { question: 'What software do you already pay for? Pick the main one.', choices: ['Square for Restaurants', 'QuickBooks Online', 'Jobber', 'Google Business Profile', 'None of these', SKIP] },
  budget: { question: 'Roughly what could you spend each month on a new tool?', choices: ['Free only', 'Under $25', 'Under $50', 'Under $100', 'Not sure', SKIP] },
}

const EMPTY_MEMORY = { trade: null, owned: [], ruled_out: [], budget_monthly_usd: null, background_done: false, plans: {} }

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

function appliesTo(problem, trade) {
  return !trade || !problem.trades || problem.trades.includes('all') || problem.trades.includes(trade)
}

// Uses the backend's task resolver, so Penny and the search box land on the same problem cards.
// The local keyword match is only a backup for when the resolver can't be reached.
async function findProblem(message, problems, trade, resolve) {
  try {
    const found = await resolve(String(message).slice(0, 300))
    const known = (ids) => ids.map((id) => problems.find((problem) => problem.id === id)).filter(Boolean)
    if (found.status === 'matched' && found.problem_id) {
      const [problem] = known([found.problem_id])
      if (problem) return { result: 'confident', problem, candidates: [problem] }
    }
    if (found.status === 'ambiguous') {
      const all = known((found.choices || []).map((choice) => choice.id))
      const fitting = all.filter((problem) => appliesTo(problem, trade))
      const candidates = fitting.length ? fitting : all
      if (candidates.length === 1) return { result: 'confident', problem: candidates[0], candidates }
      if (candidates.length) return { result: 'unsure', problem: null, candidates: candidates.slice(0, 3) }
    }
    if (found.status === 'unsupported') return matchProblem(message, problems, trade)
  } catch {
    // Fall through to the local match.
  }
  return matchProblem(message, problems, trade)
}

function factsText(name, facts) {
  const lines = facts.slice(0, 4).map((fact) => `${fact.label}: ${fact.known ? fact.value : 'unknown'}${fact.inferred ? ' (estimate, confirm with the vendor)' : ''}`)
  return `Here's what we've checked about ${name}:\n${lines.join('\n')}`
}

function factSources(name, facts) {
  return facts
    .filter((fact) => fact.known && /^https?:\/\//.test(fact.source_url || ''))
    .slice(0, 3)
    .map((fact) => ({ title: `${name}: ${fact.label}`, url: fact.source_url, checked: fact.checked || '' }))
}

export function createMockAdapter({
  delayMs = 350,
  slowMs = 9000,
  load,
  resolve = (text) => api.resolveTask(text),
  facts = (toolId) => api.toolFacts(toolId),
} = {}) {
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

  async function sendMessage({ conversationId, message, profile, memory: given, isRetry = false, context = {} }, onEvent) {
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
      if (state.candidates?.length) {
        onEvent({ type: 'clarify', question: 'Thanks. Which of these is closest?', choices: [...state.candidates.map((p) => p.title), SOMETHING_ELSE] })
        onEvent({ type: 'done' })
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
      const aside = !learned && !detectMentionedTools(message, data.tools).length && parseBudget(message) === null ? smallTalk(text) : null
      if (aside) {
        await say(aside.replace(/ (Want to keep going|What's getting in the way|Tell me what's slowing).*$/, ''), onEvent)
        await askNext(intake, 'Back to my quick question:')
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
        const answerMatch = await findProblem(message, data.problems, memory.trade || profile?.trade || null, resolve)
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

    const match = await findProblem(message, data.problems, trade, resolve)

    // Everyday chat gets a friendly reply that leads back to the business, unless it also names a problem.
    const chatter = match.result === 'confident' || learned ? null : smallTalk(text, context.problemTitle || lastProblem?.title || '')
    if (chatter) {
      await say(chatter, onEvent)
      onEvent({ type: 'done' })
      return
    }
    const wantsStart = text === normalize(GET_STARTED)
    if (!memory.background_done && text !== 'slow reply' && (wantsStart || !trade)) {
      const steps = stepsLeft()
      const state = {
        steps,
        index: 0,
        problem: match.result === 'confident' ? match.problem : null,
        candidates: match.result === 'unsure' ? match.candidates : [],
      }
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
    const topic = context.problemTitle || lastProblem?.title || ''
    const words = WORDS(text)

    async function reply(textOut, extra = []) {
      await say(textOut, onEvent)
      extra.forEach((event) => onEvent(event))
      onEvent({ type: 'done' })
    }

    async function showFacts(toolId) {
      const name = data.tools.find((tool) => tool.id === toolId)?.name || 'that tool'
      try {
        const list = await facts(toolId)
        await reply(factsText(name, list), [{ type: 'sources', items: factSources(name, list) }])
      } catch {
        await reply(`I couldn't load what we know about ${name} just now. Try again in a moment.`)
      }
    }

    if (match.result === 'none' && learned && lastProblem) {
      await recommend(conversationId, lastProblem, profile, memory, "Good to know. I'll check that again with what you just told me.", onEvent)
      return
    }
    if (INTENTS.no.test(text)) {
      await reply("No problem. I'm here if anything else comes up. You can describe a new problem anytime.")
      return
    }
    if (match.result !== 'confident' && words <= 6 && INTENTS.thanks.test(text)) {
      await reply(topic ? `You're welcome! Anything else about "${topic}", or something new on your plate?` : "You're welcome! What else can I help with?")
      return
    }
    if (match.result !== 'confident' && words <= 4 && INTENTS.greeting.test(text)) {
      await reply(topic ? `Hi again! Still thinking about "${topic}", or is something else getting in the way?` : "Hi! What's getting in the way at your business?")
      return
    }
    if (INTENTS.yes.test(text)) {
      await reply(topic ? 'Great. Pick one of the options below, or tell me what you want to do next.' : "Great. What's getting in the way at your business?")
      return
    }
    if (match.result !== 'confident' && INTENTS.another.test(text)) {
      await reply("Sure. What else is getting in the way? Tell me in your own words, and I'll keep what I know about your business.")
      return
    }

    const mentioned = detectMentionedTools(message, data.tools).filter((id) => !owned.includes(id) && !ruledOut.includes(id))
    if (mentioned.length && match.result !== 'confident' && (INTENTS.cost.test(text) || INTENTS.question.test(text) || words <= 4)) {
      await showFacts(mentioned[0])
      return
    }
    if (context.problemId && match.result !== 'confident' && INTENTS.compare.test(text)) {
      await reply('Let me pull up other checked tools for this job.', [{ type: 'action', action: 'compare' }])
      return
    }
    if (context.problemId && match.result !== 'confident' && INTENTS.save.test(text)) {
      if (context.winnerId) await reply(`I'll save a plan with ${context.winnerName || 'that tool'} and its setup steps.`, [{ type: 'action', action: 'save' }])
      else await reply("I can't save a plan until one tool is confirmed. Want me to compare the options first?")
      return
    }
    if (context.winnerId && match.result !== 'confident' && INTENTS.cost.test(text)) {
      await showFacts(context.winnerId)
      return
    }

    if (match.result === 'confident') {
      const switching = lastProblem && lastProblem.id !== match.problem.id
      const intro = switching
        ? `Got it, let's look at "${match.problem.title}" now. I'll keep what I know about your business.`
        : `Sounds like "${match.problem.title}". Let's see what's worth your money.`
      await recommend(conversationId, match.problem, profile, memory, intro, onEvent)
      return
    }
    if (match.result === 'none' && learned) {
      await say("Got it, I'll keep that in mind.", onEvent)
      onEvent({
        type: 'clarify',
        question: "What's getting in the way right now? Pick one, or tell me in your own words.",
        choices: [...suggestedProblems(data.problems, trade).map((p) => p.title), SOMETHING_ELSE],
      })
      onEvent({ type: 'done' })
      return
    }
    if (match.result === 'unsure') {
      onEvent({ type: 'clarify', question: 'I can help with a few things that sound like that. Which is closest?', choices: [...match.candidates.map((p) => p.title), SOMETHING_ELSE] })
      onEvent({ type: 'done' })
      return
    }
    if (topic) {
      await say(`I'm not sure I followed. Is this about "${topic}", or something new?`, onEvent)
      onEvent({
        type: 'clarify',
        question: 'What would help most?',
        choices: [
          ...(context.problemId ? ['Compare alternatives'] : []),
          ...(context.winnerId ? ['Save this plan'] : []),
          ANOTHER_PROBLEM,
        ],
      })
      onEvent({ type: 'done' })
      return
    }
    onEvent({
      type: 'clarify',
      question: "I'm not sure I followed. Do any of these sound close?",
      choices: [...suggestedProblems(data.problems, trade).map((p) => p.title), SOMETHING_ELSE],
    })
    onEvent({ type: 'done' })
  }

  return { sendMessage }
}
