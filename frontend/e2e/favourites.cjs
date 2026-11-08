const assert = require('node:assert/strict')
const fs = require('node:fs')
const crypto = require('node:crypto')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:5175'
const ids = { alice: '00000000-0000-0000-0000-0000000dbba1', bob: '00000000-0000-0000-0000-0000000dbba2' }
const tokens = {}, checks = []
const record = name => { checks.push(name); console.log(JSON.stringify({ check: name, passed: true })) }
fs.writeFileSync('sandbox/favourites-qa-clock.json', JSON.stringify({ seconds: 0 }))

;(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('https://*.supabase.co/**', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/token')) {
        const body = request.postDataJSON(), name = body.email?.startsWith('alice') ? 'alice' : 'bob'
        const user = { id: ids[name], email: `${name}@example.test`, aud: 'authenticated', role: 'authenticated', app_metadata: { provider: 'email' }, user_metadata: {}, created_at: new Date().toISOString() }
        const payload = { sub: user.id, email: user.email, aud: 'authenticated', role: 'authenticated', exp: Math.floor(Date.now()/1000)+3600, iat: Math.floor(Date.now()/1000), iss: url.origin+'/auth/v1', session_id: crypto.randomUUID(), qa_fixture: true }
        const token = [Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url'), Buffer.from(JSON.stringify(payload)).toString('base64url'), 'synthetic-qa-signature'].join('.')
        tokens[name] = token
        return route.fulfill({ json: { access_token: token, refresh_token: crypto.randomUUID(), token_type: 'bearer', expires_in: 3600, user } })
      }
      if (url.pathname.endsWith('/logout')) return route.fulfill({ status: 204 })
      return route.fulfill({ json: {} })
    })
    async function signIn(name) {
      await page.locator('.owner-account-trigger').click()
      await page.locator('.owner-account-form input[type=email]').fill(`${name}@example.test`)
      await page.locator('.owner-account-form input[type=password]').fill('synthetic-password')
      await page.locator('.owner-account-form button[type=submit]').click()
      await page.locator('.owner-account-trigger').filter({ hasText: 'Account' }).waitFor()
      await page.locator('#favourites .favourites-empty, #favourites .tool-card').first().waitFor()
    }
    async function signOut() {
      if (await page.locator('.msc-panel').isVisible()) await page.getByRole('button', { name: 'Close chat', exact: true }).click()
      await page.locator('.owner-account-trigger').click()
      await page.getByRole('button', { name: 'Sign out', exact: true }).click()
      await page.locator('.owner-account-trigger').filter({ hasText: 'Sign in' }).waitFor()
      await page.locator('#favourites .favourites-empty').waitFor()
    }
    async function saveTool(name) {
      await page.getByRole('button', { name: 'Browse directory', exact: false }).click()
      await page.locator('#explore').getByRole('button', { name: `Save ${name} to favourites`, exact: true }).click()
      await page.locator('#favourites').getByRole('heading', { name, exact: true }).waitFor()
    }
    const getHistory = token => page.request.get(base+'/api/chat/history', { headers: { Authorization: 'Bearer '+token } })
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Browse directory', exact: false }).click()
    assert.equal(await page.locator('#explore .favourite-button').first().isDisabled(), true)
    assert.equal((await page.request.get(base+'/api/favourites')).status(), 401)
    record('guest cannot save or retrieve account favourites')
    await signIn('alice')
    await saveTool('Jobber')
    record('heart saves a tool through the real API into account favourites')
    await page.waitForTimeout(450)
    const rec = await (await page.request.post(base+'/api/recommend', { data: { profile: { trade: 'hvac' }, problem_id: 'missed_calls' } })).json()
    const surfaceId = 'penny-recommendation-favourites-e2e'
    const protocol = [
      { version: 'v0.9', createSurface: { surfaceId, catalogId: 'https://mainstreet.ai/catalogs/penny/v1' } },
      { version: 'v0.9', updateComponents: { surfaceId, components: [{ id: 'root', component: 'PennyRecommendation', recommendation: rec, problemTitle: 'Calls go unanswered', taskPurpose: 'answering phone calls', statuses: Object.fromEntries([...rec.options, ...rec.check_first].map(option => [option.tool_id, option.status])) }] } },
    ]
    const snapshot = { conversationId: 'qa-alice-retained-chat', messages: [{ id: 'qa-msg', kind: 'user', text: 'Alice saved workflow' }, { id: 'qa-cards', kind: 'a2ui', surface: 'recommendation', text: rec.message, protocol }] }
    assert.equal((await page.request.put(base+'/api/chat/history', { headers: { Authorization: 'Bearer '+tokens.alice }, data: snapshot })).status(), 204)
    await page.reload({ waitUntil: 'networkidle' })
    await page.locator('#favourites').getByRole('heading', { name: 'Jobber', exact: true }).waitFor()
    await page.locator('.msc-launcher').click()
    await page.getByText('Alice saved workflow', { exact: true }).waitFor()
    record('reload restores favourites from SQLite and chat from Redis')
    assert.equal(await page.locator('.msc-log').getByRole('button', { name: 'Remove Jobber from favourites', exact: true }).getAttribute('aria-pressed'), 'true')
    await page.locator('.msc-log').getByRole('button', { name: 'Save Housecall Pro to favourites', exact: true }).click()
    await page.locator('#favourites').getByRole('heading', { name: 'Housecall Pro', exact: true }).waitFor()
    await page.locator('.msc-log').getByRole('button', { name: 'Remove Housecall Pro from favourites', exact: true }).click()
    await page.locator('#favourites').getByRole('heading', { name: 'Housecall Pro', exact: true }).waitFor({ state: 'detached' })
    record('Penny card hearts share account favourites with the directory and saved section')
    await page.screenshot({ path: 'sandbox/favourites-alice-desktop.png' })
    const revokedAlice = tokens.alice
    await signOut()
    assert.equal((await page.request.get(base+'/api/favourites', { headers: { Authorization: 'Bearer '+revokedAlice } })).status(), 401)
    record('logout immediately revokes the old session without deleting favourites')
    await signIn('bob')
    assert.equal(await page.locator('#favourites').getByRole('heading', { name: 'Jobber', exact: true }).count(), 0)
    assert.equal(await (await getHistory(tokens.bob)).json() === null || !JSON.stringify(await (await getHistory(tokens.bob)).json()).includes('Alice saved workflow'), true)
    await saveTool('Calendly')
    record('second account cannot see the first account favourites or history')
    await signOut()
    fs.writeFileSync('sandbox/favourites-qa-clock.json', JSON.stringify({ seconds: 86400 }))
    await signIn('alice')
    await page.locator('#favourites').getByRole('heading', { name: 'Jobber', exact: true }).waitFor()
    assert.equal(await page.locator('#favourites').getByRole('heading', { name: 'Calendly', exact: true }).count(), 0)
    await page.locator('.msc-launcher').click()
    await page.getByText('Alice saved workflow', { exact: true }).waitFor()
    record('new login after simulated one day restores the correct favourites and history')
    await page.getByRole('button', { name: 'Delete history', exact: true }).click()
    await page.getByText('Your saved chat history was deleted. Your favourite tools are unchanged.', { exact: true }).waitFor()
    assert.equal(await page.getByText('Alice saved workflow', { exact: true }).count(), 0)
    await page.waitForTimeout(450)
    assert.equal(JSON.stringify(await (await getHistory(tokens.alice)).json()).includes('Alice saved workflow'), false)
    assert.equal(await page.locator('#favourites').getByRole('heading', { name: 'Jobber', exact: true }).count(), 1)
    record('delete history removes saved messages without removing favourites or resurrecting delayed saves')
    await page.getByRole('button', { name: 'Close chat', exact: true }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: 'Favourite tools (1)', exact: true }).click()
    await page.waitForFunction(() => { const top = document.querySelector('#favourites').getBoundingClientRect().top; return top > 100 && top < 180 })
    await page.screenshot({ path: 'sandbox/favourites-alice-mobile.png' })
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true)
    record('favourites section works at mobile width without horizontal overflow')
    await page.locator('#favourites').getByRole('button', { name: 'Remove Jobber from favourites', exact: true }).click()
    await page.locator('#favourites .favourites-empty').waitFor()
    await signOut()
    await signIn('alice')
    assert.equal(await page.locator('#favourites').getByRole('heading', { name: 'Jobber', exact: true }).count(), 0)
    record('removing a favourite persists across logout and a new login')
    await signOut()
    await signIn('bob')
    await page.locator('#favourites').getByRole('heading', { name: 'Calendly', exact: true }).waitFor()
    record('another account favourite remains unchanged after deletion and removal')
    assert.deepEqual(errors, [])
    fs.writeFileSync('sandbox/favourites-e2e-results.json', JSON.stringify({ identityProvider: 'synthetic test seam', api: 'real FastAPI', database: 'real SQLite', cache: 'real Redis', checks, pageErrors: errors }, null, 2))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
