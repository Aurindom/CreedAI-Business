const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const compiled = new Module(path.join(__dirname, '../presentation-test.cjs'), module)
compiled.filename = path.join(__dirname, '../presentation-test.cjs')
compiled.paths = Module._nodeModulePaths(path.join(__dirname, '..'))
compiled._compile(buildSync({ entryPoints: [path.join(__dirname, '../src/chat/chatSession.js')], bundle: true, write: false, platform: 'node', format: 'cjs' }).outputFiles[0].text, compiled.filename)
const { visibleMessages } = compiled.exports

test('restored recommendation evidence is compacted without losing the conversation or errors', () => {
  const messages = [
    { id: 'owner', kind: 'user', text: 'Help with calls' },
    { id: 'cards', kind: 'result', problemTitle: 'Calls go unanswered', recommendation: {} },
    { id: 'duplicate', kind: 'a2ui', surface: 'text', text: 'Calls go unanswered: Check these options. Source: https://example.com/' },
    { id: 'continuation', kind: 'a2ui', surface: 'text', text: 'More source citations.' },
    { id: 'error', kind: 'error', text: 'Connection failed' },
    { id: 'next-owner', kind: 'user', text: 'Hello' },
    { id: 'greeting', kind: 'assistant', text: 'Hello! What can I help with?' },
  ]
  assert.deepEqual(visibleMessages(messages).map(message => message.id), ['owner', 'cards', 'error', 'next-owner', 'greeting'])
  assert.equal(messages.length, 7)
  assert.equal(visibleMessages([{ kind: 'assistant', text: messages[2].text }]).length, 1)
})
