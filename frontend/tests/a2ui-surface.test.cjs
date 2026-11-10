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

test('A2UI renders Arkadio text as escaped text', async () => {
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

test('A2UI shows a concise task-specific tool shortlist with expandable detail', async () => {
  const options = Array.from({ length: 5 }, (_, index) => ({
    tool_id: `tool-${index}`, tool_name: `Option ${index + 1}`, route: 'separate_tool',
    added_monthly_usd: null, cost_note: 'Check the required plan.', fit_note: 'Made for this business type.', facts: [],
  }))
  const recommendation = { outcome: 'verify_with_vendor', message: 'Check the required plan before buying.', options, check_first: [], set_aside: [] }
  const root = await render(protocol('recommendation', 'PennyRecommendation', {
    recommendation, problemTitle: 'Calls go unanswered', taskPurpose: 'answering phone calls', statuses: {},
  }))
  assert.match(document.querySelector('.msc-answer').textContent, /Tools for: Calls go unanswered/)
  assert.match(document.querySelector('.msc-answer').textContent, /These are alternatives/)
  assert.equal(document.querySelectorAll('.msc-result > .msc-option').length, 3)
  assert.match(document.querySelector('.msc-option').textContent, /answering phone calls/)
  const more = [...document.querySelectorAll('details')].find((item) => item.querySelector('summary')?.textContent === 'More alternatives (2)')
  assert.ok(more)
  assert.equal(more.open, false)
  assert.equal(document.querySelector('.msc-option details'), null)
  await React.act(async () => root.unmount())
})

test('missing prices and facts offer the actual service link without unknown labels', async () => {
  const option = { tool_id: 'service', tool_name: 'Example service', service_url: 'https://example.com/', route: 'separate_tool', added_monthly_usd: null, cost_note: 'The billing period is not published.', fit_note: 'Check the required workflow.', facts: [{ label: 'Privacy', known: false, value: 'Unknown', note: 'Ask about retention.' }] }
  const root = await render(protocol('recommendation', 'PennyRecommendation', { recommendation: { outcome: 'verify_with_vendor', message: 'Check the plan before buying.', options: [option], check_first: [], set_aside: [] }, problemTitle: 'Calls go unanswered', statuses: {} }))
  assert.doesNotMatch(document.querySelector('.msc-result').textContent, /unknown/i)
  assert.equal(document.querySelector('.msc-cost'), null)
  assert.equal(document.querySelector('.msc-service-link').href, 'https://example.com/')
  assert.equal(document.querySelector('.msc-facts'), null)
  assert.doesNotMatch(document.querySelector('.msc-result').textContent, /Check the required workflow|billing period is not published|Needs checking/)
  await React.act(async () => root.unmount())
})

test('cached cards recover the service link from the catalog and reject unsafe URLs', async () => {
  const option = { tool_id: 'cached', tool_name: 'Cached service', service_url: 'javascript:alert(1)', added_monthly_usd: null, facts: [] }
  const root = await render(protocol('recommendation', 'PennyRecommendation', { recommendation: { outcome: 'verify_with_vendor', message: 'Check the plan.', options: [option], check_first: [], set_aside: [] }, problemTitle: 'Bookings', statuses: {} }), { serviceUrls: { cached: 'https://example.com/service' } })
  assert.equal(document.querySelector('.msc-service-link').href, 'https://example.com/service')
  await React.act(async () => root.unmount())
})

test('comparison table is accessible, escapes cells, and rejects unsafe links', async () => {
  const row = { tool_id: 'a', tool: '<script>vendor</script>', plan: 'Core', entry_price: 'USD 49/month (estimate)', added_cost: 'Confirm required plan', notes: 'Check fees.', sources: [{ url: 'https://example.com/pricing', checked: '2026-11-09' }] }
  const root = await render(protocol('table', 'PennyComparisonTable', { title: 'Compare alternatives', criterion: 'price', rows: [row] }))
  assert.match(document.querySelector('table caption').textContent, /by price/)
  assert.equal(document.querySelectorAll('thead th[scope="col"]').length, 5)
  assert.equal(document.querySelector('tbody th[scope="row"]').textContent, '<script>vendor</script>')
  assert.equal(document.querySelector('script'), null)
  assert.equal(document.querySelector('.msc-comparison-table a').href, 'https://example.com/pricing')
  await React.act(async () => root.unmount())
  const bad = await render(protocol('table', 'PennyComparisonTable', { title: 'Compare', criterion: 'price', rows: [{ ...row, sources: [{ url: 'javascript:alert(1)', checked: 'today' }] }] }))
  assert.equal(document.querySelector('table'), null)
  assert.match(document.body.textContent, /could not show this result/)
  await React.act(async () => bad.unmount())
})
