// One place decides how much a card may claim. The backend owns the verdict; this file only reads it.

export function safeWebsite(url) {
  if (typeof url !== 'string') return null
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

export function optionChecked(option) {
  return option?.status === 'verified'
}

export function knownFacts(facts) {
  return (facts || []).filter((fact) => fact.known && fact.state === 'known')
}

export function hasPrice(option) {
  return option?.added_monthly_usd !== null && option?.added_monthly_usd !== undefined
}

export const BADGE = {
  checked: 'Recommended',
}

export function checkedTasks(tool) {
  return Array.isArray(tool?.checked_capabilities) ? tool.checked_capabilities : []
}

export function taskChecked(tool, capability) {
  return checkedTasks(tool).includes(capability)
}
