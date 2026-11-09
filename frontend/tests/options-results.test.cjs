const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const compiled = new Module(path.join(__dirname, '../options-results-test.cjs'), module)
compiled.filename = path.join(__dirname, '../options-results-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/components/OptionsResults.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' } }).outputFiles[0].text, compiled.filename)
const OptionsResults = compiled.exports.default

const known = (label, value) => ({ label, value, known: true, state: 'known', source_url: 'https://example.com/pricing', checked: '2026-11-05' })
const unknown = (label) => ({ label, value: null, known: false, state: 'unresolved' })
const option = (id, name, extra = {}) => ({ tool_id: id, tool_name: name, route: 'separate_tool', fit: 'unconfirmed', status: 'pending_review', added_monthly_usd: null, facts: [], service_url: `https://${id}.example.com`, ...extra })

const homebase = option('homebase', 'Homebase', { status: 'verified', fit: 'made_for', added_monthly_usd: 30, facts: [known('Setup', 'Same day')], fit_note: 'Built for restaurant shifts.' })
const sevenShifts = option('seven_shifts', '7shifts', { added_monthly_usd: 35, facts: [known('Plan', 'Entrée'), unknown('Privacy')], fit_note: 'Confirm the plan covers scheduling for your team size.' })
const connecteam = option('connecteam', 'Connecteam', { facts: [unknown('Setup'), unknown('Privacy')] })

function render(recommendation) {
  const props = { recommendation: { set_aside: [], message: 'Homebase is checked for this task.', ...recommendation }, toolsById: {}, activeProblem: { id: 'staff_scheduling', title: 'Staff scheduling' }, business: 'Restaurant', budgetProvided: false, compareProps: () => ({ selected: false, full: false, onCompare() {} }), onAskPenny() {}, onCompareThese() {} }
  return renderToStaticMarkup(React.createElement(OptionsResults, props))
}

const section = (html, id) => {
  const start = html.indexOf(`id="${id}"`)
  if (start === -1) return ''
  const end = html.indexOf('</section>', start)
  return html.slice(start, end)
}

const UNSURE = /Needs checking|Not checked yet|Confirm with the service|To confirm:|No website on file|Price not confirmed|Ask the company|Not confirmed|not_checked|source not found|in review/i

test('restaurant staff scheduling recommends only the checked tool', () => {
  const html = render({ outcome: 'new_tool', winner_tool_id: 'homebase', options: [homebase], check_first: [sevenShifts, connecteam] })
  assert.match(html, /<strong>1<\/strong> recommended/)
  assert.match(html, /<strong>2<\/strong> more options/)
  const best = section(html, 'opt-best')
  assert.match(best, /Homebase/)
  assert.match(best, />Recommended</)
  assert.doesNotMatch(best, /7shifts|Connecteam/)
  assert.equal(section(html, 'opt-others'), '')
  const more = section(html, 'opt-more')
  assert.match(more, /More options/)
  assert.match(more, /7shifts/)
  assert.match(more, /Connecteam/)
  assert.doesNotMatch(more, /Recommended|Monthly cost/)
  assert.doesNotMatch(html, UNSURE)
})

test('a pending item handed back in options goes to more options', () => {
  const html = render({ outcome: 'new_tool', winner_tool_id: 'homebase', options: [homebase, sevenShifts], check_first: [] })
  assert.match(html, /<strong>1<\/strong> recommended/)
  assert.equal(section(html, 'opt-others'), '')
  assert.match(section(html, 'opt-more'), /7shifts/)
})

test('recommended cards drop unknown rows instead of labelling them', () => {
  const sparse = option('square', 'Square', { status: 'verified', fit: 'unconfirmed', facts: [unknown('Setup'), unknown('Privacy')] })
  const html = render({ outcome: 'new_tool', winner_tool_id: 'square', options: [sparse], check_first: [] })
  const best = section(html, 'opt-best')
  assert.match(best, /Square/)
  assert.doesNotMatch(best, /Monthly cost|Fits your business\?|>Setup<|See details/)
  assert.doesNotMatch(html, UNSURE)
})

test('nothing checked shows plain website cards with no count of zero', () => {
  const unsafe = option('shady', 'Shady', { service_url: 'javascript:alert(1)' })
  const html = render({ outcome: 'verify_with_vendor', winner_tool_id: null, options: [], check_first: [sevenShifts, connecteam, unsafe] })
  assert.match(html, /<h3>Tools to look at<\/h3>/)
  assert.doesNotMatch(html, /recommended<\/span>|<strong>0<\/strong>/)
  const sites = section(html, 'opt-more')
  assert.match(sites, /href="https:\/\/connecteam\.example\.com\/"/)
  assert.match(sites, /Shady/)
  assert.doesNotMatch(sites, /javascript:|Monthly cost|Recommended/)
  assert.doesNotMatch(html, UNSURE)
})
