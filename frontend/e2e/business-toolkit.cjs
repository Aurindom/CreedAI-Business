const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.QA_FRONTEND_URL || 'http://127.0.0.1:5173'
;(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
  try {
    for (const width of [1440, 390, 320]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.goto(base, { waitUntil: 'networkidle' })
      const business = page.locator('#business input[list="trade-list"]')
      const toolkit = page.locator('.business-toolkit')
      assert.equal(await toolkit.count(), 0)
      await business.fill('mechanic shop')
      await toolkit.getByRole('heading', { name: 'Your auto shop toolkit', exact: true }).waitFor()
      await toolkit.getByRole('link', { name: /QuickBooks Online/ }).waitFor()
      assert.equal(await toolkit.getByRole('link', { name: /^Jobber/ }).count(), 0)
      assert.ok((await toolkit.getByRole('link', { name: /QuickBooks Online/ }).getAttribute('href')).startsWith('https://'))
      assert.equal(await toolkit.getByRole('button', { name: 'Sign in to save QuickBooks Online as a favourite', exact: true }).isDisabled(), true)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await toolkit.scrollIntoViewIfNeeded()
      await toolkit.screenshot({ path: `sandbox/business-toolkit-${width}.png` })
      await toolkit.locator('.business-toolkit-card').filter({ has: page.getByRole('heading', { name: 'Billing and bookkeeping', exact: true }) }).getByRole('button', { name: 'Find tools for this work', exact: false }).click()
      assert.equal(await page.getByRole('tab', { name: 'Billing and bookkeeping', exact: true }).getAttribute('aria-selected'), 'true')
      await toolkit.getByRole('button', { name: 'Browse the full catalog', exact: false }).click()
      await page.getByRole('searchbox', { name: 'Search tools', exact: true }).waitFor()
      await business.fill('HVAC')
      await toolkit.getByRole('link', { name: /^Jobber/ }).first().waitFor()
      await business.fill('Unlisted business')
      await toolkit.getByRole('heading', { name: 'Your business toolkit', exact: true }).waitFor()
      assert.equal(await toolkit.getByRole('link', { name: /^Jobber/ }).count(), 0)
      await toolkit.getByText("We haven't mapped your business type yet. These examples are general-purpose tools.", { exact: true }).waitFor()
      assert.deepEqual(errors, [])
      console.log(JSON.stringify({ width, businessExamples: true, sourceLinks: true, guestFavourites: true, categoryNavigation: true, directoryNavigation: true, changingBusiness: true, unknownBusiness: true, noOverflow: true }))
      await page.close()
    }
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
