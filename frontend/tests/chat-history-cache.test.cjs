const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')

const code = buildSync({ entryPoints: [path.join(__dirname, '../src/chat/historyCache.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text
const compiled = new Module(path.join(__dirname, '../history-cache-test.cjs'), module)
compiled.filename = path.join(__dirname, '../history-cache-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(code, compiled.filename)
const { queueHistory, flushHistory, forgetQueuedHistory, deleteSavedHistory } = compiled.exports

test('chat saves serialize and sign-out refreshes the latest snapshot', async () => {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, token: options.headers.Authorization, snapshot: JSON.parse(options.body) })
    return new Response(null, { status: 204 })
  }
  const first = { conversationId: 'one', messages: [], memory: {} }
  const second = { conversationId: 'two', messages: [{ id: 'm', kind: 'user', text: 'Hello' }], memory: {} }
  await Promise.all([queueHistory('access-token', first), queueHistory('access-token', second)])
  await flushHistory(true)
  assert.deepEqual(calls.map((call) => call.snapshot.conversationId), ['one', 'two', 'two'])
  assert.ok(calls.every((call) => call.url === '/api/chat/history' && call.token === 'Bearer access-token'))
  forgetQueuedHistory()
  await flushHistory(true)
  assert.equal(calls.length, 3)
})

test('rapid updates to the same conversation save only the latest snapshot', async () => {
  const calls = []
  globalThis.fetch = async (url, options) => { calls.push(JSON.parse(options.body)); return new Response(null, { status: 204 }) }
  await Promise.all([queueHistory('fixture', { conversationId: 'same', messages: [1] }),
    queueHistory('fixture', { conversationId: 'same', messages: [1, 2] }),
    queueHistory('fixture', { conversationId: 'same', messages: [1, 2, 3] })])
  await flushHistory()
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].messages, [1, 2, 3])
  forgetQueuedHistory()
})

test('deleting history discards pending saves and waits for in-flight writes before DELETE', async () => {
  const calls = []
  let finishSave
  globalThis.fetch = async (url, options) => {
    calls.push(options.method)
    if (options.method === 'PUT') await new Promise(resolve => { finishSave = resolve })
    return new Response(null, { status: 204 })
  }
  const save = queueHistory('fixture', { conversationId: 'old', messages: [] })
  const flush = flushHistory()
  await new Promise(resolve => setTimeout(resolve, 0))
  const discarded = queueHistory('fixture', { conversationId: 'pending', messages: [] })
  const deletion = deleteSavedHistory('fixture')
  assert.deepEqual(calls, ['PUT'])
  finishSave()
  await Promise.all([save, flush, discarded, deletion])
  await flushHistory(true)
  assert.deepEqual(calls, ['PUT', 'DELETE'])
})
