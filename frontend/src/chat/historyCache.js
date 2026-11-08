import { api } from '../api'

let queue = Promise.resolve()
let latest = null

export function queueHistory(token, snapshot) {
  if (!token) return Promise.resolve()
  latest = { token, snapshot }
  queue = queue.catch(() => {}).then(() => api.saveChatHistory(token, snapshot))
  return queue
}

export async function flushHistory(refresh = false) {
  await queue
  if (refresh && latest) await api.saveChatHistory(latest.token, latest.snapshot)
}

export function forgetQueuedHistory() {
  latest = null
}
