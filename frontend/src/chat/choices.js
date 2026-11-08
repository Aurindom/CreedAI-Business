// Shared by Penny's question renderers. MAX_CHOICES matches MAX_QUESTION_CHOICES in the backend.
export const MAX_CHOICES = 5
// A choice that asks the owner to type their own answer instead of sending this word.
export const OTHER_CHOICE = 'Other'

// The typing hint shown after "Other" is tapped, worded for the question that offered it.
export function otherHint(question = '') {
  return /business/i.test(question) ? 'Type your kind of business, for example Florist' : 'Type your answer'
}
