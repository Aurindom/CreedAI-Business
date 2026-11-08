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
    if (url === '/api/chat/status') return Response.json({ available: true })
    if (url === '/api/chat') {
      const events = replies.shift()
      return new Response(events.map(event => `data: ${JSON.stringify(event)}

`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
    }
    if (url === '/api/chat/validate') {
      if (validation instanceof Error) throw validation
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
afterEach(async () => { await act(async () => root.unmount()) })
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
const OUTAGE = { type: 'error', code: 'agent_unavailable', message: "Penny's AI is unavailable.", retryable: true }

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

test('unknown action statuses are not rendered as progress', async () => {
  replies.push([{ type: 'action', action: 'save_plan', status: 'done-ish', message: 'Saved!' }, { type: 'done' }])
  await submit('Save my plan')
  assert.equal(document.querySelector('.msc-action'), null)
})
