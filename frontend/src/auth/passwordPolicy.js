// The password rules for new accounts and password resets. Change them here only.
// Supabase checks passwords too, so its dashboard setting should match PASSWORD_MIN and the number rule.
export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 14

export const PASSWORD_RULES = [
  { id: 'length', label: `${PASSWORD_MIN} to ${PASSWORD_MAX} characters`, test: (value) => value.length >= PASSWORD_MIN && value.length <= PASSWORD_MAX },
  { id: 'number', label: 'At least one number', test: (value) => /\d/.test(value) },
]

// Every rule with whether this password meets it, for the checklist under the field.
export function passwordChecks(value = '') {
  return PASSWORD_RULES.map((rule) => ({ id: rule.id, label: rule.label, met: rule.test(value) }))
}

// A sentence for the first rule the password breaks, or '' when it meets them all.
export function passwordProblem(value = '') {
  if (value.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`
  if (value.length > PASSWORD_MAX) return `Use no more than ${PASSWORD_MAX} characters.`
  if (!/\d/.test(value)) return 'Add at least one number.'
  return ''
}
