const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const compiled = new Module(path.join(__dirname, '../catalog-status-test.cjs'), module)
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/catalogStatus.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text, compiled.filename || 'catalog-status-test.cjs')
const { catalogStatus, catalogChecked } = compiled.exports

test('one approved task never labels every feature checked', () => {
  const tool = { status: 'verified', capabilities: [{ capability: 'phone' }, { capability: 'books' }], reviews: { phone: { eligible: true }, books: { eligible: false } } }
  assert.equal(catalogStatus(tool), 'Some features checked')
  assert.equal(catalogChecked(tool), false)
  tool.reviews.books.eligible = true
  assert.equal(catalogChecked(tool), true)
  tool.verification_state = 'refresh_due'
  assert.equal(catalogChecked(tool), false)
  assert.equal(catalogStatus(tool), 'Source refresh due')
})

test('incomplete automatic refresh retains the catalog entry with clear confirmation wording', () => {
  const tool = { status: 'verified', capabilities: [{ capability: 'phone' }], reviews: { phone: { eligible: false } } }
  assert.equal(catalogStatus(tool), 'Details need confirmation')
  assert.equal(catalogChecked(tool), false)
})
