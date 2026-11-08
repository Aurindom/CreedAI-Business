const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')
const Module = require('node:module')
const { buildSync } = require('esbuild')

const compiled = new Module(path.join(__dirname, '../business-types-test.cjs'), module)
compiled.filename = path.join(__dirname, '../business-types-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/businessTypes.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text, compiled.filename)
const { resolveTrade } = compiled.exports
const trades = JSON.parse(fs.readFileSync(path.join(__dirname, '../../backend/data/catalog.json'), 'utf8')).trades
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, '../../backend/tests/fixtures/business_types.json'), 'utf8'))

test('business aliases agree with the backend cases, without guessing unrelated businesses', () => {
  for (const entry of cases) assert.equal(resolveTrade(trades, entry.text), entry.expected, entry.text)
  for (const trade of trades) {
    assert.equal(resolveTrade(trades, trade.name), trade.id)
    assert.equal(resolveTrade(trades, trade.id), trade.id)
  }
})

test('ambiguous business aliases and typos need clarification', () => {
  const ambiguous = [{ id: 'a', name: 'First', aliases: ['Mechanic shop'] }, { id: 'b', name: 'Second', aliases: ['Mechanic shop'] }]
  assert.equal(resolveTrade(ambiguous, 'mechanic shop'), null)
  assert.equal(resolveTrade(ambiguous, 'mechainc shop'), null)
})
