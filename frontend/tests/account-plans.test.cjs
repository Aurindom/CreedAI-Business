const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const { JSDOM } = require('jsdom')
// react-dom checks for a browser when it loads; without one it never listens for typed input.
const bootDom = new JSDOM('')
Object.assign(globalThis, { window: bootDom.window, document: bootDom.window.document })
const React = require('react')
const { createRoot } = require('react-dom/client')

function component(entry) {
  const code = buildSync({ entryPoints: [path.join(__dirname, entry)], bundle: true, write: false,
    platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
  const result = new Module(path.join(__dirname, '../account-plans-test.cjs'), module)
  result.filename = path.join(__dirname, '../account-plans-test.cjs')
  result.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
  result._compile(code, result.filename)
  return result.exports.default
}

function browser() {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
  return dom
}

test('plans are account-scoped and old browser plans require explicit import', async () => {
  const dom = browser()
  const Plans = component('../src/components/PrivatePlans.jsx')
  const requests = []
  window.localStorage.setItem('mainstreet-private-plans-v1', JSON.stringify({ token: 'legacy-fixture', expires_at: '2099-01-01' }))
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, method: options.method, token: options.headers.Authorization })
    if (url === '/api/plans') return Response.json(options.headers.Authorization === 'Bearer alice'
      ? [{ id: 'p', tool_names: ['Alice account plan'], total_monthly_usd: 1 }] : [])
    throw new Error('Unexpected request')
  }
  const root = createRoot(document.getElementById('root'))
  const selection = { profile: {}, problem_ids: [], tool_ids: [] }
  const auth = (id) => id ? { user: { id }, session: { access_token: id } } : { user: null, session: null }
  await React.act(async () => root.render(React.createElement(Plans, { selection, canSave: false, auth: auth('alice') })))
  assert.match(document.body.textContent, /Alice account plan/)
  assert.match(document.body.textContent, /Import my old plans/)
  assert.ok(!requests.some((item) => item.url.includes('claim-legacy')))
  assert.ok(requests.every((item) => item.token !== 'Bearer legacy-fixture'))
  await React.act(async () => root.render(React.createElement(Plans, { selection, canSave: false, auth: auth('bob') })))
  assert.doesNotMatch(document.body.textContent, /Alice account plan/)
  await React.act(async () => root.render(React.createElement(Plans, { selection, canSave: false, auth: auth(null) })))
  assert.match(document.body.textContent, /Sign in to save plans/)
  assert.doesNotMatch(document.body.textContent, /Alice account plan/)
  await React.act(async () => root.unmount())
  dom.window.close()
})

test('sign out revokes the backend session before ending the Supabase session', async () => {
  const dom = browser()
  const Controls = component('../src/auth/AccountControls.jsx')
  const steps = []
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/auth/logout')
    assert.equal(options.headers.Authorization, 'Bearer fixture-account')
    steps.push('backend')
    return Response.json({ signed_out: true, cache_expiry_confirmed: true })
  }
  const auth = { configured: true, ready: true, user: { id: 'a', email: 'fixture@example.test' },
    session: { access_token: 'fixture-account' }, client: { auth: { signOut: async () => { steps.push('supabase'); return {} } } } }
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(Controls, { auth })))
  await React.act(async () => document.querySelector('.owner-account-trigger').click())
  const button = [...document.querySelectorAll('button')].find((item) => item.textContent === 'Sign out')
  await React.act(async () => button.click())
  assert.deepEqual(steps, ['backend', 'supabase'])
  await React.act(async () => root.unmount())
  dom.window.close()
})

test('signup confirmation requests a return to this application origin', async () => {
  const dom = browser()
  // Sign-up moved from the account pop-up to the sign-in page; the same Supabase call is checked here.
  const Page = component('../src/auth/SignInPage.jsx')
  let supplied
  const auth = { configured: true, ready: true, user: null, session: null,
    client: { auth: { signUp: async (value) => { supplied = value; return { data: { session: null } } } } } }
  window.history.replaceState({}, '', '/signin?mode=create')
  const root = createRoot(document.getElementById('root'))
  await React.act(async () => root.render(React.createElement(Page, { auth, path: '/signin' })))
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await React.act(async () => {
    const [password, again] = document.querySelectorAll('input[autocomplete=new-password]')
    for (const [input, value] of [[document.querySelector('input[type=email]'), 'fixture@example.test'], [password, 'fixture1pass'], [again, 'fixture1pass']]) {
      setValue.call(input, value)
      input.dispatchEvent(new window.Event('input', { bubbles: true }))
    }
    document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))
  })
  assert.equal(supplied.options.emailRedirectTo, 'http://localhost')
  await React.act(async () => root.unmount())
  dom.window.close()
})
