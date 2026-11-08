const { test } = require('node:test')
const assert = require('node:assert/strict')

test('deployment build exports exactly public auth settings', async () => {
  const { publicAuth } = await import('../scripts/build-deploy.mjs')
  const actual = publicAuth('SUPABASE_URL=https://qa.supabase.co\nSUPABASE_PUBLISHABLE_KEY=sb_publishable_test\nHERMES_API_KEY=private-marker\nMODEL_GATEWAY_KEY=private-marker')
  assert.deepEqual(actual, { VITE_SUPABASE_URL: 'https://qa.supabase.co', VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test' })
  assert.ok(!JSON.stringify(actual).includes('private-marker'))
})

test('deployment build refuses missing, secret or service-role keys', async () => {
  const { publicAuth } = await import('../scripts/build-deploy.mjs')
  const jwt = role => 'header.' + Buffer.from(JSON.stringify({ role })).toString('base64url') + '.signature'
  for (const key of ['', 'sb_secret_test', jwt('service_role'), 'REPLACE_KEY']) {
    assert.throws(() => publicAuth('SUPABASE_URL=https://qa.supabase.co\nSUPABASE_PUBLISHABLE_KEY=' + key))
  }
  assert.equal(publicAuth('SUPABASE_URL=https://qa.supabase.co\nSUPABASE_PUBLISHABLE_KEY=' + jwt('anon')).VITE_SUPABASE_PUBLISHABLE_KEY, jwt('anon'))
})
