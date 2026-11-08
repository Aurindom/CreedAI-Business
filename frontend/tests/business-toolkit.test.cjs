const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const compiled = new Module(path.join(__dirname, '../business-toolkit-test.cjs'), module)
compiled.filename = path.join(__dirname, '../business-toolkit-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/components/BusinessToolkit.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' } }).outputFiles[0].text, compiled.filename)
const { businessToolkitGroups } = compiled.exports
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../../backend/data/catalog.json'), 'utf8'))
const toolIds = groups => [...new Set(groups.flatMap(group => group.tools.map(entry => entry.tool.id)))]

test('business overview includes supported examples without mixing in another industry', () => {
  const auto = toolIds(businessToolkitGroups(catalog.tools, catalog.categories, 'auto'))
  const hvac = toolIds(businessToolkitGroups(catalog.tools, catalog.categories, 'hvac'))
  assert.ok(auto.includes('quickbooks_online'))
  assert.ok(auto.includes('google_business_profile'))
  assert.ok(auto.includes('nicejob'))
  assert.equal(auto.includes('jobber'), false)
  assert.ok(hvac.includes('jobber'))
})

test('unknown businesses receive general-purpose examples, with pending and unchecked facts excluded', () => {
  const groups = businessToolkitGroups(catalog.tools, catalog.categories, null)
  assert.ok(groups.length)
  for (const group of groups) for (const { tool } of group.tools) {
    assert.equal(tool.applicability, 'cross_industry')
    assert.equal(tool.status, 'verified')
  }
  const withoutEvidence = catalog.tools.map(tool => ({ ...tool, capabilities: tool.capabilities.map(capability => ({ ...capability, access: { status: 'unknown' } })) }))
  assert.deepEqual(businessToolkitGroups(withoutEvidence, catalog.categories, 'auto'), [])
})
