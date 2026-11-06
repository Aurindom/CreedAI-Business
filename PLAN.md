# MVP plan

Working name: Main Street AI (placeholder)

## Goal

A website that helps non-technical small business owners choose, compare, adopt, and measure AI tools. It covers coffee shops, restaurants, HVAC, and landscaping.

**Submission deadline:** Sunday, November 8, 2026 (video and prototype link)
**Final presentations:** November 17 (winning teams)

## User journey

| Step | MVP feature |
|---|---|
| Describe the business | Trade selection and a short guided chat about size, budget, and current software |
| Identify a problem | Plain-English problem cards, plus "Not sure? Tell us about your week" |
| Find suitable tools | Personal stack of 2-3 tools, the directory, and live discovery |
| Compare evidence and costs | Trust Scores with source links, prices, payback estimates, and side-by-side comparison |
| Get help adopting them | Setup steps for each tool, or an instant custom assistant when nothing fits |
| Measure results | A private plan link with an estimate-versus-actual tracker and assistant usage counts |

## MVP features

### Core flow
- Problem cards for all four trades
- "Not sure? Tell us about your week": the owner describes their week and the chatbot suggests the likely problem
- Guided chat about budget, software, and comfort with technology
- Personal plan with tools, Trust Scores, total monthly cost, payback estimate, and reasons for each pick

### Custom assistant (signature feature)
- Owner answers a few questions and adds details such as recipes or routines
- A working assistant is generated, saved, and shared by link, with no setup
- Example: a barista trainer staff can open on a phone
- Usage is counted, for example "Your staff asked 42 questions this week"

### Directory and comparison
- About 30 real tools, around 6-8 per trade, with some shared across trades
- Side-by-side comparison of 2-3 tools: cost, setup time, Trust Score, and what each connects to

### Trust Score
AI drafts each score from public pages with source links, and the team spot-checks it.

| Factor | Weight |
|---|---|
| Fit for the trade | 25% |
| Ease of setup | 25% |
| True cost | 20% |
| Privacy | 15% |
| Support and company stability | 15% |

### Live discovery
A button finds a new tool and writes it up as "Pending review". Safeguards:
- A time limit
- Saved results to fall back on
- A limit on how often it can run
- A review step, so web content is never published straight to the directory

### Results tracking
- Each plan gets a private link, so owners can return without an account
- A simple form logs results such as hours saved or calls answered
- The plan page shows the estimate next to the actual result
- The demo uses clearly labeled sample data, since nobody will have 30 days of results by Sunday

## Out of scope for the MVP
- User accounts and payments
- Real integrations with tools such as Square
- Hands-on testing of every tool
- Automated 30-day check-in reminders

These belong in the 16-week plan.

## Tech stack
- App: Next.js, hosted on Vercel
- Saved plans, assistants, results, and tool data: Supabase
- AI: OpenRouter, with the key kept on the server and a spending limit set
- Code sharing: GitHub
- Web search for discovery: try OpenRouter's search first and confirm it works early in the build

## Team split
- Person 1: builds the app with Claude Code
- Person 2: verifies tools and scores, and talks to the business owner
- Person 3: handles the 16-week plan, script, and slides, and tests as a non-technical user

## Timeline

| When | Goal |
|---|---|
| Friday night | Set up accounts and get a basic version online |
| Saturday | Finish the core flow, assistant generator, tool data, live discovery, comparison, and results tracking |
| Sunday morning | Stop adding features, fix bugs, and test on a phone |
| Sunday afternoon | Record the video and submit, with time to spare |

If time runs short, cut in this order: live discovery falls back to saved results, then comparison, then "Tell us about your week". Keep the custom assistant and a simple results tracker.

## Still needed
- Free Vercel and Supabase accounts
- OpenRouter key ready to add securely (don't paste it into chat)
- A 10-minute conversation with one business owner on Saturday, with a short clip if they agree
- Published small business research to support the evidence section
