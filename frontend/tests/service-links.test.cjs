const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { JSDOM } = require('jsdom')
const { buildSync } = require('esbuild')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const compiled = new Module(path.join(__dirname, '../service-link-test.cjs'), module)
compiled.filename = path.join(__dirname, '../service-link-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/chat/ChatResult.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' } }).outputFiles[0].text, compiled.filename)
const { ServiceText } = compiled.exports

test('official fallback links are clickable without interpreting message text as HTML', () => {
  const text = 'Official service details: https://example.com/plans?mode=business&lang=en. <img src=x onerror=alert(1)> javascript:alert(1)'
  const dom = new JSDOM(renderToStaticMarkup(React.createElement(ServiceText, { text })))
  const links = dom.window.document.querySelectorAll('a')
  assert.equal(links.length, 1)
  assert.equal(links[0].href, 'https://example.com/plans?mode=business&lang=en')
  assert.equal(links[0].rel, 'noopener noreferrer')
  assert.equal(dom.window.document.querySelector('img'), null)
  assert.match(dom.window.document.body.textContent, /<img src=x onerror=alert\(1\)>/)
  dom.window.close()
})
