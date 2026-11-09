const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const compiled = new Module(path.join(__dirname, '../comparison-rows-test.cjs'), module)
compiled.filename = path.join(__dirname, '../comparison-rows-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/components/ComparisonWorkspace.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' } }).outputFiles[0].text, compiled.filename)
const ComparisonWorkspace = compiled.exports.default

const tools = [{ id: 'a', name: 'Alpha', capabilities: [] }, { id: 'b', name: 'Beta', capabilities: [] }]
const known = { a: { 'Entry price': true }, b: {} }

function render(factKnown) {
  return renderToStaticMarkup(React.createElement(ComparisonWorkspace, { tools, problems: [], profile: { owned: [] }, activeProblemId: null, baseline: null, onRemove() {}, renderFact: (tool, label) => `${tool.id}:${label}`, factKnown, auth: null }))
}

test('fact rows missing for every compared tool are left out', () => {
  const html = render((tool, label) => Boolean(known[tool.id][label]))
  assert.match(html, /<td>Entry price<\/td>/)
  assert.doesNotMatch(html, /<td>Setup<\/td>|<td>Privacy<\/td>|<td>Support<\/td>/)
  assert.doesNotMatch(html, /no sourced detail|Needs checking|Catalog status/)
})

test('rows stay while facts are still loading', () => {
  const html = render(() => undefined)
  assert.match(html, /<td>Privacy<\/td>/)
})

test('no fact rows when every fact is unknown', () => {
  const html = render(() => false)
  assert.doesNotMatch(html, /<td>Entry price<\/td>|no sourced detail/)
})
