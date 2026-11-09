const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const compiled = new Module(path.join(__dirname, '../copy-test.cjs'), module)
compiled.filename = path.join(__dirname, '../copy-test.cjs')
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/toolEvidence.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text, compiled.filename)
const { recommendationIntro } = compiled.exports

test('persisted audit notes do not become owner-facing recommendation copy', () => {
  const message = 'Jobber: automatic evidence checks are complete. Official page could not be read; retry or use vendor support.'
  const recommendation = { outcome: 'verify_with_vendor', message }
  assert.doesNotMatch(recommendationIntro(recommendation), /evidence checks|could not be read|retry|vendor support/)
  assert.match(recommendationIntro(recommendation), /websites/)
  assert.equal(recommendation.message, message)
})

test('a confirmed decision retains its sourced explanation', () => {
  assert.equal(recommendationIntro({ outcome: 'no_new_tool', message: 'Your plan already includes this.' }), 'Your plan already includes this.')
})
