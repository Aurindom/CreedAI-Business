const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')
const Module = require('node:module')
const { JSDOM } = require('jsdom')
const { buildSync } = require('esbuild')

test('page handoff waits for account restoration, preserves history, and does not follow another owner', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
  const React = require('react')
  const { createRoot } = require('react-dom/client')
  const code = buildSync({ entryPoints: [path.join(__dirname, '../src/chat/ChatPanel.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
  const compiled = new Module(path.join(__dirname, '../selection-test.cjs'), module)
  compiled.filename = path.join(__dirname, '../selection-test.cjs')
  compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
  compiled._compile(code, compiled.filename)
  const ChatPanel = compiled.exports.default
  const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../../backend/data/catalog.json'), 'utf8'))
  let restoreAlice
  const pendingHistory = new Promise(resolve => { restoreAlice = resolve })
  const requests = []
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, body: options.body ? JSON.parse(options.body) : null, token: options.headers?.Authorization })
    if (url === '/api/chat/status') return Response.json({ available: false })
    if (url === '/api/trades') return Response.json(catalog.trades)
    if (url === '/api/problems') return Response.json(catalog.problem_cards)
    if (url === '/api/tools') return Response.json(catalog.tools)
    if (url === '/api/chat/history' && options.method === 'PUT') return new Response(null, { status: 204 })
    if (url === '/api/chat/history') return options.headers.Authorization === 'Bearer alice-token' ? pendingHistory : Response.json(null)
    if (url === '/api/recommend') return Response.json({ problem_id: 'missed_calls', outcome: 'no_match', message: 'No confirmed match in this test catalog.', options: [], check_first: [], set_aside: [] })
    throw new Error(`Unexpected request ${url}`)
  }
  const auth = id => ({ configured: true, ready: true, user: { id }, session: { access_token: `${id}-token` } })
  const profile = { trade: 'HVAC', owned: [{ tool_id: 'jobber', plan: 'Grow' }], budget_monthly_usd: 75 }
  const root = createRoot(document.getElementById('root'))
  try {
    await React.act(async () => root.render(React.createElement(ChatPanel, { auth: auth('alice'), profile })))
    await React.act(async () => window.dispatchEvent(new window.CustomEvent('penny:open', { detail: { profile, problemIds: ['missed_calls'] } })))
    assert.equal(requests.filter(request => request.url === '/api/recommend').length, 0)
    await React.act(async () => restoreAlice(Response.json({ conversationId: 'alice-existing', messages: [{ id: 'old', kind: 'user', text: 'Earlier account conversation' }], memory: { pending_question: 'business' } })))
    assert.match(document.querySelector('.msc-log').textContent, /Earlier account conversation/)
    assert.match(document.querySelector('.msc-log').textContent, /Help me with my selected task/)
    assert.equal(document.querySelectorAll('.msc-result').length, 1)
    assert.equal(document.querySelector('.msc-starters'), null)
    assert.deepEqual(requests.filter(request => request.url === '/api/recommend').map(request => request.body), [{ profile, problem_id: 'missed_calls' }])
    await React.act(async () => new Promise(resolve => setTimeout(resolve, 350)))
    const saved = requests.filter(request => request.url === '/api/chat/history' && request.body).at(-1).body
    assert.equal(saved.conversationId, 'alice-existing')
    assert.deepEqual(saved.memory.active_task_ids, ['missed_calls'])
    assert.equal(saved.memory.pending_question, null)
    assert.equal(saved.memory.plans.jobber, 'Grow')
    await React.act(async () => root.render(React.createElement(ChatPanel, { auth: auth('bob'), profile })))
    assert.doesNotMatch(document.querySelector('.msc-log').textContent, /Earlier account conversation|Help me with my selected task/)
    assert.equal(requests.filter(request => request.url === '/api/recommend').length, 1)
    assert.equal(requests.filter(request => request.url === '/api/chat').length, 0)
  } finally {
    await React.act(async () => root.unmount())
    dom.window.close()
  }
})
