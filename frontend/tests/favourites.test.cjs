const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const { JSDOM } = require('jsdom')
const React = require('react')
const { createRoot } = require('react-dom/client')
const compiled = new Module(path.join(__dirname, '../favourites-test.cjs'), module)
compiled.filename = path.join(__dirname, '../favourites-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/favourites/Favourites.jsx')], bundle: true, write: false, platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text, compiled.filename)
const { FavouritesProvider, FavouriteButton, FavouriteTools } = compiled.exports
const tool = { id: 'jobber', name: 'Jobber', status: 'verified' }
const entry = { tool_id: 'jobber', tool_name: 'Jobber', available: true, saved_at: '2026-11-08' }
const auth = id => ({ ready: true, user: id ? { id } : null, session: id ? { access_token: id } : null })

function setup() {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
  const root = createRoot(document.getElementById('root'))
  const render = async identity => React.act(async () => root.render(React.createElement(FavouritesProvider, { auth: identity },
    React.createElement('div', { id: 'choice' }, React.createElement(FavouriteButton, { toolId: tool.id, name: tool.name })),
    React.createElement('div', { id: 'saved' }, React.createElement(FavouriteTools, { toolsById: { jobber: tool }, renderTool: item => React.createElement('p', { key: item.id }, item.name) })),
  )))
  return { dom, root, render, close: async () => { await React.act(async () => root.unmount()); dom.window.close() } }
}

test('save, sign out, second account and sign back in preserve only the correct favourites', async () => {
  const ui = setup(), saved = new Map(), requests = []
  globalThis.fetch = async (url, options = {}) => {
    const owner = options.headers.Authorization
    requests.push({ url, owner, method: options.method })
    if (!options.method) return Response.json(saved.get(owner) || [])
    if (options.method === 'PUT') { saved.set(owner, [entry]); return Response.json(entry) }
    saved.set(owner, []); return new Response(null, { status: 204 })
  }
  await ui.render(auth(null))
  assert.equal(document.querySelector('#choice button').disabled, false)
  assert.equal(requests.length, 0)
  await ui.render(auth('alice'))
  await React.act(async () => document.querySelector('#choice button').click())
  assert.match(document.querySelector('#saved').textContent, /Jobber/)
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'true')
  await ui.render(auth(null))
  assert.doesNotMatch(document.querySelector('#saved').textContent, /Jobber/)
  await ui.render(auth('bob'))
  assert.doesNotMatch(document.querySelector('#saved').textContent, /Jobber/)
  await ui.render(auth('alice'))
  assert.match(document.querySelector('#saved').textContent, /Jobber/)
  await React.act(async () => document.querySelector('#choice button').click())
  assert.doesNotMatch(document.querySelector('#saved').textContent, /Jobber/)
  assert.equal(window.localStorage.length, 0)
  assert.ok(requests.every(request => request.owner === 'Bearer alice' || request.owner === 'Bearer bob'))
  await ui.close()
})

test('failed removal preserves the favourite and reports the error', async () => {
  const ui = setup()
  globalThis.fetch = async (url, options = {}) => options.method ? Response.json({ detail: 'Outage' }, { status: 503 }) : Response.json([entry])
  await ui.render(auth('alice'))
  await React.act(async () => document.querySelector('#choice button').click())
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'true')
  assert.match(document.body.textContent, /Could not remove/)
  await ui.close()
})

test('late save response from a previous account cannot leak into the next account', async () => {
  const ui = setup()
  let resolveSave
  globalThis.fetch = async (url, options = {}) => options.method === 'PUT' ? new Promise(resolve => { resolveSave = resolve }) : Response.json([])
  await ui.render(auth('alice'))
  await React.act(async () => document.querySelector('#choice button').click())
  assert.equal(document.querySelector('#choice button').disabled, true)
  await ui.render(auth('bob'))
  await React.act(async () => resolveSave(Response.json(entry)))
  assert.doesNotMatch(document.querySelector('#saved').textContent, /Jobber/)
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'false')
  await ui.close()
})

test('a guest tapping the heart is asked to sign in and comes back to the same page', async () => {
  const ui = setup(), requests = []
  globalThis.fetch = async url => { requests.push(url); return Response.json([]) }
  window.history.replaceState({}, '', '/#compare')
  await ui.render(auth(null))
  await React.act(async () => document.querySelector('#choice button').click())
  const prompt = document.querySelector('.favourites-toast')
  assert.match(prompt.textContent, /Sign in to save tools/)
  assert.equal(prompt.querySelector('a').getAttribute('href'), '/signin?next=%2F%23compare')
  await React.act(async () => prompt.querySelector('a').click())
  assert.equal(window.location.pathname, '/signin')
  assert.equal(document.querySelector('.favourites-toast'), null)
  assert.equal(requests.length, 0)
  await ui.close()
})

test('a guest can dismiss the sign-in prompt', async () => {
  const ui = setup()
  await ui.render(auth(null))
  await React.act(async () => document.querySelector('#choice button').click())
  await React.act(async () => document.querySelector('.favourites-toast button').click())
  assert.equal(document.querySelector('.favourites-toast'), null)
  await ui.close()
})

test('the heart stays locked while sign-in is still restoring', async () => {
  const ui = setup()
  await ui.render({ ready: false, user: null, session: null })
  assert.equal(document.querySelector('#choice button').disabled, true)
  await ui.close()
})

test('a failed favourites load says so and retry recovers it', async () => {
  const ui = setup()
  let healthy = false
  globalThis.fetch = async () => healthy ? Response.json([entry]) : Response.json({ detail: 'Outage' }, { status: 503 })
  await ui.render(auth('alice'))
  const toast = document.querySelector('.favourites-toast')
  assert.match(toast.textContent, /Could not load your favourite tools/)
  assert.equal(document.querySelector('#choice button').disabled, false)
  healthy = true
  await React.act(async () => [...toast.querySelectorAll('button')].find(button => button.textContent === 'Retry').click())
  assert.equal(document.querySelector('.favourites-toast'), null)
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'true')
  await ui.close()
})

test('tapping the heart after a failed load retries instead of saving', async () => {
  const ui = setup(), methods = []
  let healthy = false
  globalThis.fetch = async (url, options = {}) => { methods.push(options.method || 'GET'); return healthy ? Response.json([]) : Response.json({ detail: 'Outage' }, { status: 503 }) }
  await ui.render(auth('alice'))
  healthy = true
  await React.act(async () => document.querySelector('#choice button').click())
  assert.deepEqual(methods, ['GET', 'GET'])
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'false')
  assert.equal(document.querySelector('.favourites-toast'), null)
  await ui.close()
})

test('chat favourite changes refresh cards from the API', async () => {
  const ui = setup()
  let items = []
  globalThis.fetch = async () => Response.json(items)
  await ui.render(auth('alice'))
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'false')
  items = [entry]
  await React.act(async () => window.dispatchEvent(new window.Event('arkadio:favourites-changed')))
  assert.equal(document.querySelector('#choice button').getAttribute('aria-pressed'), 'true')
  assert.match(document.querySelector('#saved').textContent, /Jobber/)
  await ui.close()
})
