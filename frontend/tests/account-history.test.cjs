const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { JSDOM } = require('jsdom')
const { buildSync } = require('esbuild')

const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
const React = require('react')
const { createRoot } = require('react-dom/client')
const code = buildSync({ entryPoints: [path.join(__dirname, '../src/chat/ChatPanel.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
const compiled = new Module(path.join(__dirname, '../account-history-test.cjs'), module)
compiled.filename = path.join(__dirname, '../account-history-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(code, compiled.filename)
const ChatPanel = compiled.exports.default

function auth(id) {
  return { configured: true, ready: true, user: id ? { id } : null, session: id ? { access_token: `${id}-token` } : null }
}

test('chat restore follows the authenticated owner and never exposes Alice history to Bob', async () => {
  window.sessionStorage.setItem('main-street-penny-session-v2', JSON.stringify({ conversationId: 'old-guest', messages: [{ id: 'old', kind: 'user', text: 'Old guest chat' }], memory: {} }))
  const reads = []
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/chat/status') return Response.json({ available: false })
    if (url === '/api/chat/history' && options.method !== 'PUT') {
      reads.push(options.headers.Authorization)
      return Response.json(options.headers.Authorization === 'Bearer alice-token'
        ? { conversationId: 'alice-chat', messages: [{ id: 'm1', kind: 'user', text: 'Alice bakery question' }], memory: {} }
        : null)
    }
    if (url === '/api/chat/history' && options.method === 'PUT') return new Response(null, { status: 204 })
    if (url === '/api/trades' || url === '/api/problems' || url === '/api/tools') return Response.json([])
    throw new Error(`Unexpected fetch: ${url}`)
  }
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(ChatPanel, { auth: auth('alice') })))
  assert.match(document.querySelector('.msc-log').textContent, /Alice bakery question/)
  assert.doesNotMatch(document.querySelector('.msc-log').textContent, /Old guest chat/)
  assert.equal(window.sessionStorage.getItem('main-street-penny-session-v2'), null)
  await React.act(async () => root.render(React.createElement(ChatPanel, { auth: auth('bob') })))
  assert.doesNotMatch(document.querySelector('.msc-log').textContent, /Alice bakery question/)
  await React.act(async () => root.render(React.createElement(ChatPanel, { auth: auth('alice') })))
  assert.match(document.querySelector('.msc-log').textContent, /Alice bakery question/)
  assert.deepEqual(reads, ['Bearer alice-token', 'Bearer bob-token', 'Bearer alice-token'])
  await React.act(async () => root.unmount())
  dom.window.close()
})
