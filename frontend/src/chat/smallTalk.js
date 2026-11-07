// Friendly replies to everyday chat, always steering back to the owner's business.
// Each reply is short, honest that Penny is an AI, and never makes claims about tools.

function steer(topic) {
  return topic ? `Want to keep going with "${topic}", or is something else on your mind?` : "What's getting in the way at your business?"
}

const RULES = [
  {
    test: /\b(how are (you|u|things)|how(s| is) it going|how have you been|hows your day|how you doing|whats up|sup)\b/,
    reply: (topic) => (topic
      ? `I'm doing well, thanks for asking! How's business going? ${steer(topic)}`
      : "I'm doing well, thanks for asking! How's business going? If anything's slowing you down, tell me and I'll find tools that help."),
  },
  {
    test: /\b(who are you|what are you|whats your name|what is your name|your name)\b/,
    reply: (topic) => `I'm Penny, an AI guide from Main Street AI. I help small businesses find AI tools that fit their budget, and I show where every fact comes from. ${steer(topic)}`,
  },
  {
    test: /\b(are you (a )?(real|human|person|bot|robot|ai|machine)|am i talking to a (person|human|bot|real person))\b/,
    reply: (topic) => `I'm an AI, not a person. I can't see your accounts or buy anything, but I can check tools for you. ${steer(topic)}`,
  },
  {
    test: /\b(what can you do|what do you do|how does this work|how do you work|help me|can you help|what should i ask|i need help)\b/,
    reply: (topic) => `I can match a problem to tools we've checked, compare options and prices, check what you already pay for, save a plan with setup steps, or draft a custom assistant for your staff. ${topic ? `We were on "${topic}". ` : ''}Tell me what's slowing you down, or tap one of the options below.`,
  },
  {
    test: /\b(bye|goodbye|good bye|see you|see ya|talk later|thats all|thats it|im done|gotta go)\b/,
    reply: () => "Thanks for stopping by! This chat stays here until you close the tab, so you can pick up where you left off anytime.",
  },
  {
    test: /\b(youre (great|helpful|awesome|smart|the best|amazing)|good job|well done|love this|this is (great|helpful|awesome))\b/,
    reply: (topic) => `Thank you, that's kind! ${steer(topic)}`,
  },
  {
    test: /\b(confusing|confused|useless|not helpful|doesnt help|dont understand|makes no sense|frustrat)\b/,
    reply: (topic) => `Sorry about that. Let's slow down. Tell me in one sentence what's taking up your time${topic ? `, or ask me anything about "${topic}"` : ''}, and I'll keep it simple.`,
  },
  {
    test: /\b(joke|make me laugh|something funny)\b/,
    reply: (topic) => `Why did the coffee shop owner hire an AI? Because the espresso machine kept getting all the credit! ${steer(topic)}`,
  },
  {
    test: /\b(weather|forecast|sports?|football|basketball|baseball|soccer|movie|tv show|music|song|politic|election|president|news|stock market|crypto|bitcoin|homework|essay|poem|dating|girlfriend|boyfriend|horoscope)\b/,
    reply: (topic) => `That's outside what I can help with. I stick to helping your business find and use the right tools. ${steer(topic)}`,
  },
]

const GREETING = /^(hi|hello|hey|hiya|howdy|yo|good (morning|afternoon|evening)|greetings)\b/

export function smallTalk(text, topic = '') {
  const rule = RULES.find((item) => item.test.test(text))
  if (rule) return rule.reply(topic)
  if (GREETING.test(text) && text.split(' ').length <= 4) {
    return topic
      ? `Hi again! Still thinking about "${topic}", or is something else getting in the way?`
      : "Hi! I'm Penny. Tell me what's slowing your business down, or tap 'Start with a few questions' and I'll guide you."
  }
  return null
}
