export const DRAFT_MAX = { name: 60, purpose: 200, knowledge: 4000, limits: 600, question: 200 }
export const DEFAULT_LIMITS = 'Only answer from these notes. If the answer is not in them, say so and suggest asking a manager. Never guess about allergies, safety, money, legal or medical questions.'

const SECRET = /\b(password|passcode|passwd|pin code|security code|routing number|account number|ssn|social security)\b|\b(?:\d[ -]?){13,19}\b/i
const STOP = new Set(['the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'is', 'are', 'do', 'does', 'how', 'what', 'when', 'where', 'i', 'we', 'you', 'my', 'our', 'it', 'with', 'at', 'be', 'can', 'should', 'make', 'get'])

export function validateDraft(draft) {
  const errors = {}
  if (!draft.name.trim()) errors.name = 'Give your assistant a name.'
  if (draft.purpose.trim().length < 10) errors.purpose = 'Say what it should help with, in a sentence.'
  if (draft.knowledge.trim().length < 20) errors.knowledge = 'Add a few lines it should know, like recipes or steps.'
  if (SECRET.test(`${draft.knowledge} ${draft.limits} ${draft.purpose}`)) {
    errors.knowledge = 'Remove passwords, card numbers or account details. Assistants should never hold those.'
  }
  Object.entries(DRAFT_MAX).forEach(([field, max]) => {
    if ((draft[field] || '').length > max) errors[field] = `Keep this under ${max} characters.`
  })
  return errors
}

export function slug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'my-assistant'
}

function words(text) {
  return new Set(text.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter((word) => word.length > 2 && !STOP.has(word)))
}

// Shows which of the owner's own lines would answer a question. It never writes new facts.
export function sampleAnswer(knowledge, question) {
  const asked = words(question)
  if (!asked.size) return null
  const lines = knowledge.split(/\n+|(?<=[.!?])\s+/).map((line) => line.trim()).filter(Boolean)
  let best = null
  lines.forEach((line) => {
    const score = [...words(line)].filter((word) => asked.has(word)).length
    if (score && (!best || score > best.score)) best = { line, score }
  })
  return best ? best.line : null
}

export function buildSkill(draft) {
  const description = draft.purpose.trim().replace(/\s+/g, ' ').replace(/"/g, "'")
  return [
    '---',
    `name: ${slug(draft.name)}`,
    `description: "${description}"`,
    '---',
    '',
    `# ${draft.name.trim()}`,
    '',
    '## What this assistant does',
    draft.purpose.trim(),
    '',
    '## How to answer',
    '- Answer in short, plain steps a new staff member can follow.',
    '- Use only the notes below.',
    '',
    '## Limits',
    draft.limits.trim() || DEFAULT_LIMITS,
    '',
    '## Notes from the business',
    draft.knowledge.trim(),
    '',
    '_Draft made with Main Street AI. Review it before anyone relies on it._',
    '',
  ].join('\n')
}
