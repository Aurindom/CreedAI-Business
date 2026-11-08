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
  window: dom.window, document: dom.window.document,
  HTMLElement: dom.window.HTMLElement, Element: dom.window.Element,
  IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })

const entry = path.join(__dirname, '../src/chat/A2UISurface.jsx')
const code = buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
const compiled = new Module(path.join(__dirname, '../a2ui-surface-test.cjs'), module)
compiled.filename = path.join(__dirname, '../a2ui-surface-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(code, compiled.filename)
const A2UISurface = compiled.exports.default

function protocol(kind, component, properties) {
  const surfaceId = `penny-${kind}-test`
  return [
    { version: 'v0.9', createSurface: { surfaceId, catalogId: 'https://mainstreet.ai/catalogs/penny/v1' } },
    { version: 'v0.9', updateComponents: { surfaceId, components: [{ id: 'root', component, ...properties }] } },
  ]
}

async function render(surface, props = {}) {
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(A2UISurface, { protocol: surface, onSelect: () => {}, onPrint: () => {}, ruledOut: [], ...props })))
  return root
}

test('A2UI renders Penny text as escaped text', async () => {
  const root = await render(protocol('text', 'PennyText', { text: '<script>alert(1)</script>' }))
  assert.match(document.querySelector('.msc-row').textContent, /<script>alert\(1\)<\/script>/)
  assert.equal(document.querySelector('script'), null)
  await React.act(async () => root.unmount())
})

test('A2UI renders only safe source links', async () => {
  const root = await render(protocol('sources', 'PennySources', { items: [{ title: 'Vendor facts', url: 'https://example.com/facts', checked: '2026-11-07' }] }))
  assert.equal(document.querySelector('.msc-sources a').href, 'https://example.com/facts')
  await React.act(async () => root.unmount())
  const bad = await render(protocol('sources', 'PennySources', { items: [{ title: 'Bad', url: 'javascript:alert(1)' }] }))
  assert.equal(document.querySelector('a'), null)
  await React.act(async () => bad.unmount())
})

test('A2UI recommendation retains the print action', async () => {
  const recommendation = { outcome: 'no_match', message: 'Check these options.', options: [], check_first: [], set_aside: [] }
  const printed = []
  const root = await render(protocol('recommendation', 'PennyRecommendation', { recommendation, problemTitle: 'Bookkeeping', statuses: {} }), { onPrint: (data) => printed.push(data) })
  assert.match(document.querySelector('.msc-result').textContent, /Check these options/)
  await React.act(async () => document.querySelector('.msc-print-button').click())
  assert.equal(printed[0].problemTitle, 'Bookkeeping')
  assert.equal(printed[0].recommendation, recommendation)
  await React.act(async () => root.unmount())
})
