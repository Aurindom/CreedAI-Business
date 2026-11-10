const { test, before, beforeEach, afterEach, after } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')
const Module = require('node:module')
const { JSDOM } = require('jsdom')
const { buildSync } = require('esbuild')

let dom, root, React, act, ChatPanel, validation, requests, replies
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../../backend/data/catalog.json'), 'utf8'))

before(() => {
  dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
  React = require('react')
  act = React.act
  const code = buildSync({ entryPoints: [path.join(__dirname, '../src/chat/ChatPanel.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
  const compiled = new Module(path.join(__dirname, '../action-test.cjs'), module)
  compiled.filename = path.join(__dirname, '../action-test.cjs')
  compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
  compiled._compile(code, compiled.filename)
  ChatPanel = compiled.exports.default
})

beforeEach(async () => {
  requests = []
  replies = []
  validation = { allowed: true, message: null }
  window.sessionStorage.clear()
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, body: options.body ? JSON.parse(options.body) : null })
    if (url === '/api/chat/status') return Response.json(globalThis.chatStatus || { available: true })
    if (url === '/api/chat') {
      const events = replies.shift()
      if (events instanceof Response) return events
      return new Response(events.map(event => `data: ${JSON.stringify(event)}

`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
    }
    if (url === '/api/chat/validate') {
      if (validation instanceof Error) throw validation
      if (validation.status) return Response.json(validation.body, { status: validation.status })
      return Response.json(validation)
    }
    if (url === '/api/trades') return Response.json(catalog.trades)
    if (url === '/api/problems') return Response.json(catalog.problem_cards)
    if (url === '/api/tools') return Response.json(catalog.tools)
    throw new Error('Unexpected request in action test')
  }
  root = require('react-dom/client').createRoot(document.getElementById('root'))
  await act(async () => root.render(React.createElement(ChatPanel)))
  await act(async () => document.querySelector('.msc-launcher').click())
})
afterEach(async () => { await act(async () => root.unmount()); globalThis.chatStatus = null })

async function reopen(status) {
  globalThis.chatStatus = status
  await act(async () => root.unmount())
  root = require('react-dom/client').createRoot(document.getElementById('root'))
  await act(async () => root.render(React.createElement(ChatPanel)))
  await act(async () => document.querySelector('.msc-launcher').click())
}

test('a paused model shows Limited, explains what still works, and keeps sending open', async () => {
  await reopen({ available: true, model_available: false })
  assert.equal(document.querySelector('.msc-live'), null)
  assert.equal(document.querySelector('.msc-unavailable').textContent, 'Limited')
  assert.match(document.querySelector('.penny-unavailable-note').textContent, /AI answers are paused.*saved tools/)
  replies.push([{ type: 'message_delta', text: 'You told me your business is a bakery.' }, { type: 'done' }])
  await submit('what business do I have?')
  assert.match(document.querySelector('.msc-log').textContent, /your business is a bakery/)
  assert.equal(document.querySelector('.msc-unavailable').textContent, 'Limited')
})

test('the badge follows the server after a turn, in both directions', async () => {
  assert.equal(document.querySelector('.msc-live').textContent, 'Ready')
  globalThis.chatStatus = { available: true, model_available: false }
  replies.push([{ type: 'error', code: 'ai_budget_reached', message: 'The AI budget is used up.', retryable: false }, { type: 'done' }])
  await submit('How do I attract customers?')
  assert.equal(document.querySelector('.msc-unavailable').textContent, 'Limited')
  globalThis.chatStatus = { available: true, model_available: true }
  replies.push([{ type: 'message_delta', text: 'Hello again.' }, { type: 'done' }])
  await submit('hello')
  assert.equal(document.querySelector('.msc-live').textContent, 'Ready')
  assert.equal(document.querySelector('.penny-unavailable-note'), null)
})

test('one failed reply does not change the badge while the server still reports ready', async () => {
  replies.push([OUTAGE, { type: 'done' }])
  await submit('Help with scheduling')
  assert.equal(document.querySelector('.msc-live').textContent, 'Ready')
})
after(() => dom.window.close())

async function submit(text) {
  const field = document.querySelector('textarea')
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(field, text)
    field.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  await act(async () => document.querySelector('.msc-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
}


const NOT_RUN = { type: 'action', action: 'save_plan', status: 'not_executed', code: 'action_not_executed', message: 'That step did not run. Nothing was changed for you.' }
const UNCONFIRMED = { type: 'action', action: 'save_plan', status: 'unconfirmed', code: 'action_unconfirmed', message: 'We could not confirm that step finished. Please check before relying on it.' }
const OUTAGE = { type: 'error', code: 'agent_unavailable', message: "Arkadio's AI is unavailable.", retryable: true }

test('a step that did not run is shown to the owner, not hidden behind the answer', async () => {
  replies.push([NOT_RUN, { type: 'message_delta', text: 'Here is what I found.' }, { type: 'done' }])
  await submit('Save my plan')
  const status = document.querySelector('.msc-action')
  assert.equal(status.dataset.status, 'not_executed')
  assert.match(status.textContent, /did not run/)
  assert.equal(status.getAttribute('role'), 'status')
})

test('an unconfirmed step never reads as nothing changed', async () => {
  replies.push([UNCONFIRMED, { type: 'done' }])
  await submit('Save my plan')
  const status = document.querySelector('.msc-action')
  assert.equal(status.dataset.status, 'unconfirmed')
  assert.doesNotMatch(status.textContent, /Nothing was changed/)
})

test('retrying after an outage resends once without a second user message', async () => {
  replies.push([OUTAGE, { type: 'done' }], [{ type: 'message_delta', text: 'Jobber handles scheduling.' }, { type: 'done' }])
  await submit('Help with scheduling')
  assert.match(document.querySelector('.msc-error').textContent, /unavailable/)
  await act(async () => document.querySelector('.msc-error button').click())
  assert.equal(document.querySelectorAll('.msc-row-user').length, 1)
  assert.equal(requests.filter(request => request.url === '/api/chat').length, 2)
  assert.match(document.querySelector('.msc-panel').textContent, /Jobber handles scheduling/)
})

test('a daily refusal after successful validation preserves the chat and keeps the agent ready', async () => {
  replies.push(Response.json({ detail: 'daily chat limit reached' }, { status: 429 }))
  await submit('hi')
  assert.match(document.querySelector('.msc-error').textContent, /today.*AI request limit/)
  assert.equal(document.querySelector('.msc-error button'), null)
  assert.equal(document.querySelector('.msc-live').textContent, 'Ready')
  assert.equal(document.querySelector('.penny-unavailable-note'), null)
  replies.push([{ type: 'message_delta', text: 'Hello! What can I help with?' }, { type: 'done' }])
  await submit('hello')
  assert.equal(document.querySelectorAll('.msc-row-user').length, 2)
  assert.match(document.querySelector('.msc-log').textContent, /Hello! What can I help with/)
  assert.equal(document.querySelector('.msc-live').textContent, 'Ready')
})

test('unknown action statuses are not rendered as progress', async () => {
  replies.push([{ type: 'action', action: 'save_plan', status: 'done-ish', message: 'Saved!' }, { type: 'done' }])
  await submit('Save my plan')
  assert.equal(document.querySelector('.msc-action'), null)
})


for (const [status, body, expected] of [
  [401, { detail: 'Sign in again to continue' }, /sign-in has expired/],
  [429, { detail: 'Too many chat requests. Please try again shortly.' }, /Wait a minute/],
  [503, { detail: 'Account verification is unavailable' }, /couldn't check your sign-in/],
]) {
  test(`a ${status} from the safety check says what to do instead of a generic error`, async () => {
    validation = { status, body }
    await submit('The books are behind')
    assert.match(document.querySelector('.msc-panel').textContent, expected)
    assert.equal(requests.filter(request => request.url === '/api/chat').length, 0)
  })
}

test('tapping Other lets the owner type their business instead of sending "Other"', async () => {
  replies.push([{ type: 'clarify', question: 'What kind of business do you run?', choices: ['Auto shop', 'Bakery', 'Bar or brewery', 'Other', 'Skip these questions'] }, { type: 'done' }])
  await submit('Start with a few questions')
  const sent = requests.filter(request => request.url === '/api/chat').length
  const other = [...document.querySelectorAll('.msc-choices button')].find(button => button.textContent === 'Other')
  assert.ok(other, 'the Other choice is shown')
  await act(async () => other.click())
  assert.equal(requests.filter(request => request.url === '/api/chat').length, sent, 'nothing is sent')
  const field = document.querySelector('textarea')
  assert.match(field.getAttribute('placeholder'), /kind of business/)
  assert.equal(document.activeElement, field)
})

test('an over-long memory from the backend is trimmed so the next message is not rejected', async () => {
  const five = ['bookkeeping', 'invoicing', 'email_marketing', 'review_replies', 'missed_calls']
  replies.push([{ type: 'memory', memory: { pending_question: 'task', pending_task_ids: five, active_task_ids: [] } }, { type: 'message_delta', text: 'Which one?' }, { type: 'done' }])
  await submit('Help me decide')
  replies.push([{ type: 'message_delta', text: 'Here you go.' }, { type: 'done' }])
  await submit('The books are behind')
  const sent = requests.filter(request => request.url === '/api/chat/validate').at(-1).body
  assert.equal(sent.memory.pending_task_ids.length, 3)
  assert.equal(requests.filter(request => request.url === '/api/chat').at(-1).body.memory.pending_task_ids.length, 3)
})


test('account history restoration blocks sending until the stored context is ready', async () => {
  await act(async () => root.unmount())
  root = require('react-dom/client').createRoot(document.getElementById('root'))
  let restore
  const previous = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (url === '/api/chat/history') return new Promise(resolve => { restore = resolve })
    if (url === '/api/chat/conversations') return Response.json({ conversations: [] })
    return previous(url, options)
  }
  const auth = { configured: true, ready: true, user: { id: 'fixture-owner' }, session: { access_token: 'fixture-token' } }
  await act(async () => root.render(React.createElement(ChatPanel, { auth })))
  await act(async () => document.querySelector('.msc-launcher').click())
  assert.equal(document.querySelector('.msc-send').disabled, true)
  assert.equal(document.querySelector('.msc-send').textContent, 'Restoring')
  assert.equal(document.querySelector('textarea').disabled, true)
  await act(async () => restore(Response.json({ conversationId: 'restored', messages: [], memory: { business_description: 'bakery' } })))
  assert.equal(document.querySelector('.msc-send').disabled, false)
  assert.equal(document.querySelector('textarea').disabled, false)
  globalThis.fetch = previous
})
