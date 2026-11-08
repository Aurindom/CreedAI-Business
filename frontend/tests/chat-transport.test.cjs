const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')

const code = buildSync({ entryPoints: [path.join(__dirname, '../src/chat/chatAdapter.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text
const compiled = new Module(path.join(__dirname, '../transport-test.cjs'), module)
compiled.filename = path.join(__dirname, '../transport-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(code, compiled.filename)
const { createChatAdapter } = compiled.exports
const request = { conversationId: 'test', message: 'Help with invoices', profile: {}, memory: {}, history: [] }
const newline = String.fromCharCode(10)
const stream = (events, complete = true) => new Response(
  [...events, ...(complete ? [{ type: 'done' }] : [])].map(event => 'data: ' + JSON.stringify(event) + newline + newline).join(''),
  { headers: { 'Content-Type': 'text/event-stream' } },
)


async function run(fetcher) {
  const events = []
  await createChatAdapter({ fetcher }).sendMessage(request, event => events.push(event))
  return events
}

function assertUnavailable(events) {
  assert.ok(events.some(event => event.type === 'error' && event.code === 'agent_unavailable'))
  assert.equal(events.at(-1).type, 'done')
  assert.equal(events.some(event => event.type === 'recommendation'), false)
}

test('verified-account credential is sent in the header, never the model request body', async () => {
  let captured
  const adapter = compiled.exports.createHttpAdapter({ fetcher: async (url, options) => { captured = options; return stream([]) } })
  const controller = new AbortController()
  await adapter.sendMessage({ ...request, accessToken: 'fixture-account-token', signal: controller.signal }, () => {})
  assert.equal(captured.headers.Authorization, 'Bearer fixture-account-token')
  assert.equal(captured.signal, controller.signal)
  assert.ok(!captured.body.includes('fixture-account-token'))
  assert.ok(!('accessToken' in JSON.parse(captured.body)))
  await adapter.sendMessage(request, () => {})
  assert.ok(!('Authorization' in captured.headers))
})

test('no key or budget means unavailable, with no generated fallback reply', async () => {
  const urls = []
  const events = await run(async url => { urls.push(url); return Response.json({ available: false }) })
  assert.deepEqual(urls, ['/api/chat/status'])
  assertUnavailable(events)
  assert.equal(events.some(event => event.type === 'message_delta'), false)
})

test('provider failure remains an error instead of generating scripted text', async () => {
  const events = await run(async url => url.endsWith('/status') ? Response.json({ available: true }) : new Response('', { status: 503 }))
  assertUnavailable(events)
  assert.equal(events.some(event => event.type === 'message_delta'), false)
})

test('a model stream error is preserved and never replaced by a fallback', async () => {
  const events = await run(async url => url.endsWith('/status') ? Response.json({ available: true }) : stream([{ type: 'error', code: 'agent_unavailable', message: 'Agent unavailable', retryable: true }]))
  assertUnavailable(events)
  assert.equal(events.some(event => event.type === 'message_delta'), false)
})

test('incomplete live response is reported honestly after the received text', async () => {
  const events = await run(async url => url.endsWith('/status') ? Response.json({ available: true }) : stream([{ type: 'message_delta', text: 'Partial model response' }], false))
  assert.deepEqual(events.filter(event => event.type === 'message_delta').map(event => event.text), ['Partial model response'])
  assertUnavailable(events)
})

test('live events and profile come from the real transport unchanged', async () => {
  let sent
  const events = await run(async (url, options) => {
    if (url.endsWith('/status')) return Response.json({ available: true })
    sent = JSON.parse(options.body)
    return stream([{ type: 'message_delta', text: 'Live response' }])
  })
  assert.equal(sent.message, request.message)
  assert.equal(sent.conversation_id, request.conversationId)
  assert.deepEqual(events.filter(event => event.type === 'message_delta').map(event => event.text), ['Live response'])
  assert.equal(events.some(event => event.type === 'error'), false)
})

test('availability is rechecked so a recovered provider can be retried', async () => {
  let checks = 0
  const adapter = createChatAdapter({ fetcher: async url => url.endsWith('/status') ? Response.json({ available: ++checks > 1 }) : stream([{ type: 'message_delta', text: 'Recovered' }]) })
  const first = [], second = []
  await adapter.sendMessage(request, event => first.push(event))
  await adapter.sendMessage(request, event => second.push(event))
  assertUnavailable(first)
  assert.ok(second.some(event => event.text === 'Recovered'))
})
