const { test, afterEach } = require('node:test')
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

function load(entry, exportAll = false) {
  const code = buildSync({ entryPoints: [path.join(__dirname, entry)], bundle: true, write: false,
    platform: 'node', format: 'cjs', external: ['react', 'react-dom'], loader: { '.css': 'empty' } }).outputFiles[0].text
  const result = new Module(path.join(__dirname, '../signin-test.cjs'), module)
  result.filename = path.join(__dirname, '../signin-test.cjs')
  result.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
  result._compile(code, result.filename)
  return exportAll ? result.exports : result.exports.default
}

let dom, root
function browser(url = 'http://localhost/signin') {
  dom = new JSDOM('<div id="root"></div>', { url })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
  root = createRoot(document.getElementById('root'))
}
afterEach(async () => {
  if (root) await React.act(async () => root.unmount())
  dom?.window.close()
  root = null
})

const setValue = (input, value) => {
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new window.Event('input', { bubbles: true }))
}
const submit = () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))
const button = (text) => [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === text)

async function render(auth, pagePath = '/signin') {
  const Page = load('../src/auth/SignInPage.jsx')
  await React.act(async () => root.render(React.createElement(Page, { auth, path: pagePath })))
}

test('password policy: 8 to 14 characters with at least one number', () => {
  browser()
  const { passwordProblem, passwordChecks } = load('../src/auth/passwordPolicy.js', true)
  assert.match(passwordProblem('abc1'), /at least 8/)
  assert.match(passwordProblem('abcdefgh'), /number/)
  assert.match(passwordProblem('abcdefghijklm12'), /no more than 14/)
  assert.equal(passwordProblem('coffee12'), '')
  assert.equal(passwordProblem('fourteen-char1'), '')
  assert.deepEqual(passwordChecks('short').map((rule) => rule.met), [false, false])
  assert.deepEqual(passwordChecks('longenough9').map((rule) => rule.met), [true, true])
})

test('a return address must stay on this site', () => {
  browser()
  const { safeNext } = load('../src/auth/route.js', true)
  assert.equal(safeNext('/#compare'), '/#compare')
  assert.equal(safeNext('https://evil.example'), '/')
  assert.equal(safeNext('//evil.example'), '/')
  assert.equal(safeNext('/\\evil.example'), '/')
  assert.equal(safeNext('/signin?next=/'), '/')
  assert.equal(safeNext(null), '/')
})

test('creating an account with a weak password never reaches Supabase', async () => {
  browser('http://localhost/signin?mode=create')
  let called = false
  await render({ configured: true, ready: true, user: null, session: null, client: { auth: { signUp: async () => { called = true; return { data: {} } } } } })
  const [password, again] = document.querySelectorAll('input[autocomplete=new-password]')
  await React.act(async () => {
    setValue(document.querySelector('input[type=email]'), 'owner@example.test')
    setValue(password, 'nonumbers')
    setValue(again, 'nonumbers')
  })
  assert.equal(document.querySelectorAll('.signin-rules li.is-met').length, 1)
  await React.act(async () => submit())
  assert.equal(called, false)
  assert.match(document.querySelector('[role=alert]').textContent, /number/)
})

test('mismatched passwords are caught before sign-up', async () => {
  browser('http://localhost/signin?mode=create')
  let called = false
  await render({ configured: true, ready: true, user: null, session: null, client: { auth: { signUp: async () => { called = true; return { data: {} } } } } })
  const [password, again] = document.querySelectorAll('input[autocomplete=new-password]')
  await React.act(async () => {
    setValue(document.querySelector('input[type=email]'), 'owner@example.test')
    setValue(password, 'coffee123')
    setValue(again, 'coffee124')
  })
  await React.act(async () => submit())
  assert.equal(called, false)
  assert.match(document.querySelector('[role=alert]').textContent, /don't match/)
})

test('signing in returns the owner to where they came from', async () => {
  browser('http://localhost/signin?next=%2F%23compare')
  let supplied
  await render({ configured: true, ready: true, user: null, session: null,
    client: { auth: { signInWithPassword: async (value) => { supplied = value; return { error: null } } } } })
  assert.equal(document.querySelector('.signin-rules'), null, 'sign-in does not show the new-password rules')
  await React.act(async () => {
    setValue(document.querySelector('input[type=email]'), ' owner@example.test ')
    setValue(document.querySelector('input[autocomplete=current-password]'), 'old5')
  })
  await React.act(async () => submit())
  assert.deepEqual(supplied, { email: 'owner@example.test', password: 'old5' })
  assert.equal(`${window.location.pathname}${window.location.hash}`, '/#compare')
})

test('a wrong password gets a plain-language message', async () => {
  browser()
  await render({ configured: true, ready: true, user: null, session: null,
    client: { auth: { signInWithPassword: async () => ({ error: { message: 'Invalid login credentials' } }) } } })
  await React.act(async () => {
    setValue(document.querySelector('input[type=email]'), 'owner@example.test')
    setValue(document.querySelector('input[autocomplete=current-password]'), 'wrongpass1')
  })
  await React.act(async () => submit())
  assert.match(document.querySelector('[role=alert]').textContent, /don't match/)
  assert.equal(window.location.pathname, '/signin')
})

test('forgot password sends a link back to the reset page', async () => {
  browser()
  let sent
  await render({ configured: true, ready: true, user: null, session: null,
    client: { auth: { resetPasswordForEmail: async (email, options) => { sent = { email, options }; return { error: null } } } } })
  await React.act(async () => button('Forgot password?').click())
  assert.match(document.querySelector('h1').textContent, /Reset your password/)
  await React.act(async () => setValue(document.querySelector('input[type=email]'), 'owner@example.test'))
  await React.act(async () => submit())
  assert.deepEqual(sent, { email: 'owner@example.test', options: { redirectTo: 'http://localhost/reset-password' } })
  assert.match(document.querySelector('[role=status]').textContent, /If that email has an account/)
})

test('the reset page sets a new password that meets the policy', async () => {
  browser('http://localhost/reset-password')
  let updated
  await render({ configured: true, ready: true, user: { id: 'u' }, session: { access_token: 't' },
    client: { auth: { updateUser: async (value) => { updated = value; return { error: null } } } } }, '/reset-password')
  const [password, again] = document.querySelectorAll('input[autocomplete=new-password]')
  await React.act(async () => { setValue(password, 'newpass123'); setValue(again, 'newpass123') })
  await React.act(async () => submit())
  assert.deepEqual(updated, { password: 'newpass123' })
  assert.match(document.body.textContent, /password is updated/)
})

test('an expired reset link offers a new one instead of a form', async () => {
  browser('http://localhost/reset-password')
  await render({ configured: true, ready: true, user: null, session: null, client: { auth: {} } }, '/reset-password')
  assert.match(document.body.textContent, /expired or was already used/)
  assert.equal(document.querySelector('form'), null)
})

test('without Supabase settings the page says accounts are coming soon', async () => {
  browser()
  await render({ configured: false, ready: true, user: null, session: null, client: null })
  assert.match(document.body.textContent, /Accounts are coming soon/)
  assert.equal(document.querySelector('form'), null)
})

test('the account button opens the sign-in page with a way back', async () => {
  browser('http://localhost/#compare')
  const Controls = load('../src/auth/AccountControls.jsx')
  await React.act(async () => root.render(React.createElement(Controls, { auth: { configured: true, ready: true, user: null, session: null, client: { auth: {} } } })))
  await React.act(async () => document.querySelector('.owner-account-trigger').click())
  assert.equal(window.location.pathname, '/signin')
  assert.equal(new URLSearchParams(window.location.search).get('next'), '/#compare')
})
