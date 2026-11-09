const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const compiled = new Module(path.join(__dirname, '../carousel-chips-test.cjs'), module)
compiled.filename = path.join(__dirname, '../carousel-chips-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/components/BusinessCarousel.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty', '.jpg': 'empty', '.webp': 'empty', '.png': 'empty' } }).outputFiles[0].text, compiled.filename)
const { carouselBusinesses, CHALLENGE_PROBLEMS } = compiled.exports
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../../backend/data/catalog.json'), 'utf8'))
const problems = new Set(catalog.problem_cards.map(card => card.id))

test('every carousel chip opens a real task in the catalog', () => {
  for (const business of carouselBusinesses) for (const challenge of business.challenges) {
    const id = CHALLENGE_PROBLEMS[challenge]
    assert.ok(id, `${business.type}: "${challenge}" has no task`)
    assert.ok(problems.has(id), `${business.type}: "${challenge}" points at missing task ${id}`)
  }
})

test('no carousel story promises privacy checks we do not run', () => {
  for (const business of carouselBusinesses) assert.doesNotMatch(`${business.copy} ${business.challenges.join(' ')}`, /privacy/i)
})
