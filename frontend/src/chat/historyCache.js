import { api } from '../api'

let queue = Promise.resolve()
let latest = null
let pending = null

function enqueuePending() {
  if (!pending) return
  const item = pending
  pending = null
  clearTimeout(item.timer)
  queue = queue.catch(() => {}).then(() => api.saveChatHistory(item.token, item.snapshot))
  queue.then(item.resolve, item.reject)
}

export function queueHistory(token, snapshot) {
  if (!token) return Promise.resolve()
  latest = { token, snapshot }
  if (pending && pending.token === token && pending.snapshot.conversationId === snapshot.conversationId) {
    pending.snapshot = snapshot
    return pending.promise
  }
  enqueuePending()
  const item = { token, snapshot }
  item.promise = new Promise((resolve, reject) => { item.resolve = resolve; item.reject = reject })
  item.timer = setTimeout(enqueuePending, 300)
  pending = item
  return item.promise
}

export async function flushHistory(refresh = false) {
  enqueuePending()
  await queue
  if (refresh && latest) await api.saveChatHistory(latest.token, latest.snapshot)
}

export function forgetQueuedHistory() {
  latest = null
  if (pending) {
    clearTimeout(pending.timer)
    pending.resolve()
    pending = null
  }
}

export async function deleteSavedHistory(token) {
  // Discard pending drafts and let already-started saves finish before deletion.
  // This prevents a delayed PUT from restoring the history just deleted.
  forgetQueuedHistory()
  queue = queue.catch(() => {}).then(() => api.deleteChatHistory(token))
  await queue
}
