const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.QA_FRONTEND_URL || 'http://127.0.0.1:5173'

// Recommendations use the real catalog API. Live transport is intercepted so
// this regression journey never spends model credits.
;(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
      const errors = [], recommendations = [], chats = []
      page.on('pageerror', error => errors.push(error.message))
      page.on('request', request => { if (new URL(request.url()).pathname === '/api/recommend') recommendations.push(request.postDataJSON()) })
      await page.route('**/api/chat/status', route => route.fulfill({ json: { available: true } }))
      await page.route('**/api/chat', route => {
        chats.push(route.request().postDataJSON())
        return route.fulfill({ contentType: 'text/event-stream', body: [{ type: 'message_delta', text: 'The selected tools have setup details to review.' }, { type: 'done' }].map(event => 'data: '+JSON.stringify(event)+'\n\n').join('') })
      })
      await page.goto(base, { waitUntil: 'networkidle' })
      const problems = await (await page.request.get(base+'/api/problems')).json()
      const title = id => problems.find(problem => problem.id === id).title
      const pick = id => page.locator('#challenge .problem-card').filter({ has: page.getByText(title(id), { exact: true }) }).click()
      await page.locator('#business input[list="trade-list"]').fill('HVAC')
      await page.locator('.budget-field input').fill('75')
      await page.locator('.owned-picker summary').click()
      await page.locator('.owned-picker .chip-more').click()
      await page.locator('.owned-picker').getByRole('button', { name: 'Jobber', exact: true }).click()
      const plan = page.getByLabel('Jobber plan', { exact: false })
      const planValue = await plan.locator('option').nth(1).getAttribute('value')
      await plan.selectOption(planValue)
      await page.waitForTimeout(400)
      await pick('missed_calls')
      await page.locator('#explore .opt-card').first().waitFor()
      assert.equal(await page.locator('#explore .opt-did-you-mean').count(), 0)
      const before = recommendations.length
      await page.locator('#explore').getByRole('button', { name: 'Ask Arkadio about these options', exact: true }).click()
      await page.locator('.msc-log .msc-result').first().waitFor()
      assert.equal(await page.locator('.msc-starters').count(), 0)
      assert.equal(chats.length, 0, 'initial handoff uses catalog lookup, not a paid chat call')
      assert.deepEqual(recommendations.slice(before).map(request => request.problem_id), ['missed_calls'])
      const selected = recommendations.at(-1).profile
      assert.equal(selected.trade, 'HVAC')
      assert.equal(selected.budget_monthly_usd, 75)
      assert.ok(selected.owned.some(entry => entry.tool_id === 'jobber' && entry.plan === planValue))
      await page.locator('.msc-form textarea').fill('Which option is simplest to set up?')
      await page.locator('.msc-send').click()
      await page.getByText('The selected tools have setup details to review.', { exact: true }).waitFor()
      assert.equal(chats.length, 1)
      assert.deepEqual(chats[0].memory.active_task_ids, ['missed_calls'])
      assert.equal(chats[0].memory.pending_question, null)
      assert.equal(chats[0].memory.background_done, true)
      assert.equal(chats[0].memory.budget_monthly_usd, 75)
      assert.equal(chats[0].memory.plans.jobber, planValue)
      await page.getByRole('button', { name: 'Close chat', exact: true }).click()
      await pick('bookkeeping')
      await page.locator('.plan-summary').waitFor()
      const beforeMulti = recommendations.length
      await page.getByRole('button', { name: 'Ask Arkadio about this plan', exact: true }).click()
      await page.waitForFunction(() => document.querySelectorAll('.msc-log .msc-result').length === 3)
      assert.deepEqual(recommendations.slice(beforeMulti).map(request => request.problem_id).sort(), ['bookkeeping', 'missed_calls'])
      await page.getByRole('button', { name: 'Close chat', exact: true }).click()
      const beforeReopen = recommendations.length
      await page.getByRole('button', { name: /^Talk to Arkadio/ }).click()
      await page.waitForTimeout(200)
      assert.equal(recommendations.length, beforeReopen, 'reopening the same selection does not duplicate results')
      assert.equal(await page.locator('.msc-log .msc-result').count(), 3)
      assert.deepEqual(errors, [])
      console.log(JSON.stringify({ width, pageOptions: true, singleTaskHandoff: true, profileAndPlan: true, followUpContext: true, multiTaskHandoff: true, noDuplicateOnReopen: true, paidCalls: 0 }))
      await page.close()
    }
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
