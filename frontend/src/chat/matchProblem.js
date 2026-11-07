// Demo mode only. This stands in for the agent until /api/chat exists: it maps
// an owner's words to a problem card. It never picks, ranks or prices a tool.

const PROBLEM_TERMS = {
  missed_calls: {
    phrases: ['missed call', 'missed calls', 'miss calls', 'miss call', 'missing calls', 'voicemail', 'phone rings', 'phone keeps ringing', 'answer the phone', 'answering the phone', 'pick up the phone', 'nobody picks up', 'unanswered calls', 'calls go unanswered'],
    words: ['phone', 'phones', 'calls', 'call', 'receptionist'],
  },
  slow_lead_replies: {
    phrases: ['new customers wait', 'get back to', 'quote requests', 'asking for a quote', 'ask for a quote', 'losing leads', 'slow to reply', 'reply to leads', 'respond to leads', 'follow up with leads'],
    words: ['leads', 'lead', 'quote', 'quotes', 'estimates', 'inquiries'],
  },
  review_requests: {
    phrases: ['more reviews', 'too few reviews', 'few reviews', 'not enough reviews', 'get reviews', 'getting reviews', 'ask for reviews', 'asking for reviews', 'ask for a review', 'leave a review', 'leave reviews'],
    words: ['reviews', 'review', 'ratings'],
  },
  review_replies: {
    phrases: ['reply to reviews', 'replying to reviews', 'respond to reviews', 'responding to reviews', 'answer reviews', 'answering reviews', 'reviews go unanswered', 'bad reviews'],
    words: ['reviews', 'review'],
  },
  job_scheduling: {
    phrases: ['schedule jobs', 'scheduling jobs', 'job schedule', 'book jobs', 'booking jobs', 'jobs on paper', 'dispatch', 'dispatching', 'work orders', 'book appointments', 'service calls'],
    words: ['jobs', 'schedule', 'scheduling', 'appointments', 'calendar', 'bookings'],
  },
  staff_scheduling: {
    phrases: ['staff schedule', 'staff scheduling', 'employee schedule', 'schedule staff', 'schedule my staff', 'schedule my team', 'shift swaps', 'swap shifts', 'build the schedule', 'making the schedule', 'work schedule'],
    words: ['shifts', 'shift', 'schedule', 'scheduling', 'roster', 'rota'],
  },
  invoicing: {
    phrases: ['getting paid', 'get paid', 'chase payments', 'chasing payments', 'chase people', 'chasing people', 'late payments', 'send invoices', 'sending invoices', 'overdue invoices'],
    words: ['invoice', 'invoices', 'invoicing', 'billing', 'bills'],
  },
  bookkeeping: {
    phrases: ['the books', 'my books', 'keep the books', 'track expenses', 'tracking expenses', 'tax time', 'do my taxes'],
    words: ['bookkeeping', 'bookkeeper', 'accounting', 'receipts', 'expenses', 'taxes'],
  },
  point_of_sale: {
    phrases: ['point of sale', 'cash register', 'the register', 'take payments', 'taking payments', 'ring up'],
    words: ['register', 'pos', 'checkout', 'orders'],
  },
  email_marketing: {
    phrases: ['email marketing', 'email list', 'customer list', 'past customers', 'repeat customers', 'customers come back', 'bring customers back', 'send newsletters', 'do marketing', 'for marketing'],
    words: ['marketing', 'newsletter', 'newsletters', 'promotions', 'promote', 'advertising'],
  },
}

const TRADE_TERMS = {
  auto: ['auto shop', 'mechanic', 'car repair', 'garage'],
  bakery: ['bakery', 'baker'],
  bar: ['bar', 'pub', 'brewery'],
  cleaning: ['cleaning company', 'cleaning business', 'cleaners', 'maid service', 'janitorial'],
  medical: ['clinic', 'vet', 'veterinary', 'dentist', 'dental office', 'doctors office'],
  coffee_shop: ['coffee shop', 'coffee house', 'coffeehouse', 'cafe', 'coffee', 'barista', 'baristas'],
  electrical: ['electrician', 'electrical contractor', 'electrical business'],
  food_truck: ['food truck'],
  fitness: ['gym', 'fitness studio', 'yoga studio', 'pilates studio'],
  hvac: ['hvac', 'heating and cooling', 'air conditioning', 'ac repair', 'furnace'],
  handyman: ['handyman', 'repair business'],
  landscaping: ['landscaping', 'landscaper', 'lawn care', 'mowing'],
  pet_care: ['pet care', 'dog grooming', 'dog groomer', 'dog walking', 'pet sitting'],
  plumbing: ['plumbing', 'plumber'],
  professional_services: ['law office', 'accounting firm', 'consulting firm'],
  restaurant: ['restaurant', 'diner', 'pizzeria', 'pizza shop', 'mom and pop restaurant'],
  retail: ['retail', 'gift shop', 'boutique', 'hardware store', 'clothing store'],
  salon: ['salon', 'barber', 'barbershop', 'barber shop', 'hair stylist'],
  spa: ['spa', 'massage', 'wellness center'],
}

const TOOL_TERMS = {
  google_business_profile: ['google business', 'google listing', 'google business profile'],
  quickbooks_online: ['quickbooks', 'quick books', 'qbo'],
  ruby_receptionists: ['ruby', 'ruby receptionists'],
  smith_ai: ['smith ai', 'smithai'],
  square_restaurants: ['square', 'square for restaurants'],
  lmn: ['lmn', 'granum'],
  seven_shifts: ['7shifts', '7 shifts', 'seven shifts'],
  when_i_work: ['when i work'],
}

const OWNED_BEFORE = /\b(use|uses|using|used|have|has|pay|paying|got|already|run|runs|running|on)\b/
const OWNED_AFTER = /\b(we use|i use|we have|i have|we pay|i pay|already)\b/
const NEGATED = /\b(dont|do not|doesnt|didnt|not|never|no|without|stopped|cancelled|canceled|quit|dropped|instead of)\b/
const RULED_OUT_BEFORE = /\b(dont want|do not want|dont like|not interested in|rule out|ruled out|no to|not|skip|avoid|hate|without)\b/

export function normalize(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/[^a-z0-9$]+/g, ' ')
    .trim()
}

function contains(text, term) {
  return ` ${text} `.includes(` ${term} `)
}

function appliesTo(problem, trade) {
  return !trade || problem.trades.includes('all') || problem.trades.includes(trade)
}

// result: 'confident' (one clear card), 'unsure' (candidates to ask about) or 'none'.
export function matchProblem(message, problems, trade = null) {
  const text = normalize(message)
  const exact = problems.find((p) => normalize(p.title) === text)
  if (exact) return { result: 'confident', problem: exact, candidates: [exact] }

  const scored = problems
    .filter((problem) => appliesTo(problem, trade))
    .map((problem) => {
      const terms = PROBLEM_TERMS[problem.id] || { phrases: [], words: [] }
      const phraseScore = terms.phrases.filter((term) => contains(text, normalize(term))).length * 3
      const wordScore = terms.words.filter((term) => contains(text, term)).length
      return { problem, score: phraseScore + wordScore }
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)

  if (!scored.length) return { result: 'none', problem: null, candidates: [] }
  const [top, second] = scored
  const clearLead = top.score - (second ? second.score : 0) >= 2
  if (top.score >= 3 && clearLead) return { result: 'confident', problem: top.problem, candidates: [top.problem] }
  const candidates = scored.filter((entry) => entry.score >= top.score - 1).slice(0, 3).map((entry) => entry.problem)
  return { result: candidates.length === 1 ? 'confident' : 'unsure', problem: candidates.length === 1 ? candidates[0] : null, candidates }
}

export function suggestedProblems(problems, trade = null, count = 3) {
  return problems.filter((problem) => appliesTo(problem, trade)).slice(0, count)
}

export function detectTrade(message, trades) {
  const text = normalize(message)
  let best = null
  trades.forEach((trade) => {
    const terms = [trade.name, ...(TRADE_TERMS[trade.id] || [])].map(normalize)
    terms.filter((term) => contains(text, term)).forEach((term) => {
      if (!best || term.length > best.length) best = { id: trade.id, length: term.length }
    })
  })
  return best ? best.id : null
}

function ownsAt(words, index, length) {
  const before = words.slice(Math.max(0, index - 5), index).join(' ')
  const after = words.slice(index + length, index + length + 4).join(' ')
  if (NEGATED.test(before) || NEGATED.test(after)) return false
  return OWNED_BEFORE.test(before) || OWNED_AFTER.test(after)
}

function findTools(message, tools, accept) {
  const words = normalize(message).split(' ')
  return tools
    .filter((tool) => {
      const terms = [tool.name, ...(TOOL_TERMS[tool.id] || [])].map(normalize)
      return terms.some((term) => {
        const termWords = term.split(' ')
        return words.some((_, index) => (
          termWords.every((word, offset) => words[index + offset] === word)
          && accept(words, index, termWords.length)
        ))
      })
    })
    .map((tool) => tool.id)
}

// Only counts software the owner says they already have, not software they're asking about.
export function detectOwnedTools(message, tools) {
  return findTools(message, tools, ownsAt)
}

// For direct answers like "QuickBooks and Square", where no "we use" is needed.
export function detectMentionedTools(message, tools) {
  return findTools(message, tools, () => true)
}

export function parseBudget(message) {
  const text = normalize(message)
  if (/\b(free|nothing|0)\b/.test(text) && !/\d{2,}/.test(text)) return 0
  const found = text.match(/\$?\s?(\d{1,5})/)
  return found ? Number(found[1]) : null
}

export function detectRuledOutTools(message, tools) {
  return findTools(message, tools, (words, index) => RULED_OUT_BEFORE.test(words.slice(Math.max(0, index - 4), index).join(' ')))
}
