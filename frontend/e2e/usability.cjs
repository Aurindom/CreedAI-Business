const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.QA_FRONTEND_URL || 'http://127.0.0.1:5173'

;(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
  const results = []
  try {
    for (const [name, width, height] of [['desktop', 1440, 1000], ['tablet', 820, 1000], ['mobile', 390, 844], ['small', 320, 740]]) {
      const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.goto(base, { waitUntil: 'networkidle' })
      await page.locator('.launchpad-categories button').first().waitFor()
      assert.equal(await page.locator('.owner-path').count(), 3)
      await page.evaluate(() => document.querySelector('#start').scrollIntoView({ block: 'start', behavior: 'instant' }))
      await page.locator('#start').screenshot({ path: `sandbox/owner-launchpad-${name}.png` })
      await page.locator('.path-find').click()
      assert.equal(await page.locator('#challenge .section-heading').evaluate(element => { const bounds = element.getBoundingClientRect(); return bounds.top >= 0 && bounds.bottom <= innerHeight }), true)
      const categoryName = await page.locator('.launchpad-categories button').first().evaluate(element => element.firstChild.textContent)
      await page.locator('.launchpad-categories button').first().click()
      assert.equal(await page.getByRole('tab', { name: categoryName, exact: true }).getAttribute('aria-selected'), 'true')
      await page.getByRole('tab', { name: 'All', exact: true }).click()
      const search = page.getByRole('searchbox', { name: 'Search tools', exact: true })
      await search.fill('Jobber')
      const jobber = page.locator('#explore .tool-card').filter({ has: page.getByRole('heading', { name: 'Jobber', exact: true }) })
      await jobber.waitFor()
      assert.equal(await page.locator('#explore .tool-card').count(), 1)
      await jobber.getByRole('button', { name: 'Compare +', exact: true }).click()
      await page.getByRole('complementary', { name: 'Your comparison shortlist' }).waitFor()
      for (const tool of ['Housecall Pro', 'Calendly']) {
        await search.fill(tool)
        const card = page.locator('#explore .tool-card').filter({ has: page.getByRole('heading', { name: tool, exact: true }) })
        await card.getByRole('button', { name: 'Compare +', exact: true }).click()
      }
      await search.fill('Podium')
      assert.equal(await page.locator('#explore .tool-card').getByRole('button', { name: 'Compare +', exact: true }).isDisabled(), true)
      const layout = await page.evaluate(() => {
        const tray = document.querySelector('.comparison-tray').getBoundingClientRect()
        const penny = document.querySelector('.penny-speech').getBoundingClientRect()
        return { noOverflow: document.body.scrollWidth <= innerWidth, noOverlap: tray.right <= penny.left || tray.bottom <= penny.top || tray.left >= penny.right }
      })
      assert.equal(layout.noOverflow, true)
      assert.equal(layout.noOverlap, true)
      await page.getByRole('button', { name: 'Compare 3 tools', exact: true }).click()
      await page.locator('#compare').screenshot({ path: `sandbox/owner-comparison-${name}.png` })
      await page.getByRole('button', { name: 'Clear comparison', exact: true }).click()
      assert.equal(await page.locator('.comparison-tray').count(), 0)
      await search.fill('not-a-catalog-tool-zzzz')
      await page.getByRole('heading', { name: 'No matches just yet', exact: true }).waitFor()
      await page.getByRole('button', { name: 'Clear search and filters', exact: false }).click()
      await page.locator('#explore .tool-card').first().waitFor()
      assert.ok(await page.locator('#explore .tool-card').count() > 1)
      await page.locator('#challenge .problem-card').filter({ has: page.locator('.problem-title', { hasText: 'Calls go unanswered' }) }).click()
      const evidence = page.locator('#explore .tool-evidence').first()
      await evidence.waitFor()
      assert.equal(await evidence.getAttribute('open'), null)
      await evidence.locator('summary').click()
      assert.equal(await evidence.locator('.fact-list').isVisible(), true)
      await page.evaluate(() => document.querySelector('#start').scrollIntoView({ block: 'start', behavior: 'instant' }))
      await page.locator('.path-compare').click()
      await page.locator('#quick-compare').waitFor({ state: 'visible' })
      assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true)
      assert.deepEqual(errors, [])
      const result = { viewport: name, startPaths: true, categoryShortcut: true, search: true, comparisonLimit: true, trayClear: true, noTrayOverlap: true, emptySearchRecovery: true, expandableEvidence: true, subscriptionShortcut: true, pageErrors: errors }
      results.push(result)
      console.log(JSON.stringify(result))
      await page.close()
    }
    fs.writeFileSync('sandbox/owner-usability-results.json', JSON.stringify(results, null, 2))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
