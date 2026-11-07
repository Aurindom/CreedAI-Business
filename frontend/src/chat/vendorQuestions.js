const QUESTIONS = {
  'Entry price': (name) => `What would ${name} cost each month for a business my size, including any fees?`,
  Setup: (name) => `How long does ${name} take to set up, and who does the work?`,
  Privacy: (name) => `What happens to my customer data in ${name}, and is it used to train AI?`,
  Support: (name) => `How do I reach a real person at ${name} when something goes wrong?`,
}

// Turns facts the catalog can't confirm into questions. Nothing here is a claim about the tool.
export function vendorQuestions(recommendation) {
  const options = [...recommendation.options, ...recommendation.check_first]
    .filter((option) => option.route !== 'already_have')
    .slice(0, 3)

  return options
    .map((option) => {
      const confirm = option.facts
        .filter((fact) => fact.known && fact.inferred)
        .map((fact) => `Can you confirm the ${fact.label.toLowerCase()} for ${option.tool_name}? Ours is an estimate: ${fact.value}.`)
      const questions = option.facts
        .filter((fact) => !fact.known)
        .map((fact) => (QUESTIONS[fact.label]
          ? QUESTIONS[fact.label](option.tool_name)
          : `What should I know about ${fact.label.toLowerCase()} for ${option.tool_name}?`))
      const priceAsked = option.facts.some((fact) => fact.label === 'Entry price' && !fact.known)
      if (option.added_monthly_usd === null && !priceAsked) {
        questions.unshift(`What would ${option.tool_name} add to my monthly bill?`)
      }
      return { toolId: option.tool_id, toolName: option.tool_name, questions: [...confirm, ...questions] }
    })
    .filter((group) => group.questions.length)
}

export function vendorQuestionsText(groups) {
  return groups
    .map((group) => [group.toolName, ...group.questions.map((question) => `- ${question}`)].join('\n'))
    .join('\n\n')
}
