import { checkedTasks } from './toolEvidence'

// Only a positive per-task verdict earns a label. Anything else shows no label at all.
export function catalogStatus(tool) {
  if (tool.verification_state === 'refresh_due') return ''
  const checked = checkedTasks(tool).length
  if (!checked) return ''
  if (checked >= (tool.capabilities?.length || 0)) return 'Recommended'
  return `Recommended for ${checked} ${checked === 1 ? 'task' : 'tasks'}`
}

export function catalogChecked(tool) {
  if (tool.verification_state === 'refresh_due') return false
  const checked = checkedTasks(tool).length
  return checked > 0 && checked >= (tool.capabilities?.length || 0)
}

export function checkedTaskNames(tool) {
  return checkedTasks(tool).map(task => task.replaceAll('_', ' '))
}
