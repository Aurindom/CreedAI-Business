// A catalog entry's recorded sources and its current feature checks are distinct.
// Purchase recommendations use the backend's capability-specific status.
export function catalogStatus(tool) {
  if (tool.verification_state === 'refresh_due') return 'Source refresh due'
  const reviews = Object.values(tool.reviews || {})
  if (reviews.length) {
    const approved = reviews.filter(review => review.eligible).length
    if (!approved) return 'Details need confirmation'
    return approved === tool.capabilities?.length ? 'Features source checked' : 'Some features checked'
  }
  if (tool.auto_review) return tool.auto_review.eligible ? 'One feature checked' : 'Details need confirmation'
  return tool.status === 'verified' ? 'Catalog sources checked' : 'Pending review'
}

export function catalogChecked(tool) {
  if (tool.verification_state === 'refresh_due') return false
  const reviews = Object.values(tool.reviews || {})
  if (reviews.length) return reviews.length === tool.capabilities?.length && reviews.every(review => review.eligible)
  return !tool.auto_review && tool.status === 'verified'
}
