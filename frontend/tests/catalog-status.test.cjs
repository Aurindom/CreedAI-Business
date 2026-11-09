const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const compiled = new Module(path.join(__dirname, '../catalog-status-test.cjs'), module)
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/catalogStatus.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text, compiled.filename || 'catalog-status-test.cjs')
const { catalogStatus, catalogChecked, checkedTaskNames } = compiled.exports

const capabilities = [{ capability: 'phone' }, { capability: 'staff_scheduling' }]

test('a product-wide verified flag alone is never shown as checked', () => {
  const tool = { status: 'verified', capabilities, reviews: { phone: { eligible: true } } }
  assert.equal(catalogStatus(tool), '')
  assert.equal(catalogChecked(tool), false)
})

test('one checked task never labels every feature checked', () => {
  const tool = { status: 'verified', capabilities, checked_capabilities: ['staff_scheduling'] }
  assert.equal(catalogStatus(tool), 'Recommended for 1 task')
  assert.equal(catalogChecked(tool), false)
  assert.deepEqual(checkedTaskNames(tool), ['staff scheduling'])
  tool.checked_capabilities.push('phone')
  assert.equal(catalogStatus(tool), 'Recommended')
  assert.equal(catalogChecked(tool), true)
})

test('a refresh due overrides any earlier checks', () => {
  const tool = { capabilities, checked_capabilities: ['phone', 'staff_scheduling'], verification_state: 'refresh_due' }
  assert.equal(catalogStatus(tool), '')
  assert.equal(catalogChecked(tool), false)
})
