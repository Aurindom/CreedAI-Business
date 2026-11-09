const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const React = require('react')
const { createRoot } = require('react-dom/client')
const { JSDOM } = require('jsdom')

const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Element: dom.window.Element,
  Node: dom.window.Node,
  customElements: dom.window.customElements,
  IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })

const entry = path.join(__dirname, '../src/chat/A2UIQuestion.jsx')
const code = buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
const compiled = new Module(path.join(__dirname, '../a2ui-test.cjs'), module)
compiled.filename = path.join(__dirname, '../a2ui-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(code, compiled.filename)
const A2UIQuestion = compiled.exports.default

test('Arkadio renders the approved A2UI follow-up with model choices as text', async () => {
  const surfaceId = 'penny-question-test'
  const protocol = [
    { version: 'v0.9', createSurface: { surfaceId, catalogId: 'https://mainstreet.ai/catalogs/penny/v1' } },
    { version: 'v0.9', updateComponents: { surfaceId, components: [{ id: 'root', component: 'PennyQuestion', question: 'What task matters most?', choices: ['Missed calls', 'Bookkeeping'], progress: 'Question 1 of 1' }] } },
  ]
  const selected = []
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(A2UIQuestion, { protocol, onSelect: (choice) => selected.push(choice), busy: false })))
  const html = document.getElementById('root').innerHTML
  assert.match(html, /What task matters most/)
  assert.match(html, /Missed calls/)
  assert.match(html, /Bookkeeping/)
  assert.match(html, /Question 1 of 1/)
  assert.doesNotMatch(html, /<script/)
  await React.act(async () => document.querySelector('.msc-a2ui-question button').click())
  assert.deepEqual(selected, ['Missed calls'])
  await React.act(async () => root.unmount())
})

test('A2UI treats model text as text, not executable markup', async () => {
  const surfaceId = 'penny-question-escape'
  const protocol = [
    { version: 'v0.9', createSurface: { surfaceId, catalogId: 'https://mainstreet.ai/catalogs/penny/v1' } },
    { version: 'v0.9', updateComponents: { surfaceId, components: [{ id: 'root', component: 'PennyQuestion', question: '<script>alert(1)</script>', choices: ['A', 'B'] }] } },
  ]
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(A2UIQuestion, { protocol, onSelect: () => {}, busy: false })))
  assert.equal(document.querySelector('.msc-a2ui-question script'), null)
  assert.match(document.querySelector('.msc-a2ui-question').textContent, /<script>alert\(1\)<\/script>/)
  await React.act(async () => root.unmount())
})

test('A2UI refuses a component outside Arkadio catalog', async () => {
  const surfaceId = 'penny-question-unapproved'
  const protocol = [
    { version: 'v0.9', createSurface: { surfaceId, catalogId: 'https://mainstreet.ai/catalogs/penny/v1' } },
    { version: 'v0.9', updateComponents: { surfaceId, components: [{ id: 'root', component: 'HTML', html: '<img src=x>' }] } },
  ]
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(A2UIQuestion, { protocol, onSelect: () => {}, busy: false })))
  assert.match(document.getElementById('root').textContent, /could not show those choices/i)
  assert.equal(document.querySelector('img'), null)
  await React.act(async () => root.unmount())
})
