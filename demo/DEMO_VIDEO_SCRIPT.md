# Main Street AI: final demo video script

Target length: about 9 minutes (the limit is 10). Spoken lines are in plain
text. Screen directions are in *italics*. Times are rough guides.

Live site: https://mainstreet-penny-aurin.belgiumcentral.cloudapp.azure.com

Before recording, check:

- The site loads and Penny answers one test question.
- You are signed out for the guest part and have a test account ready for the
  signed-in part.
- Browser zoom is 100%, window about 1440px wide, notifications off.
- The "Recommended / More options" screens in Part 4 match what the deployed
  site shows. If the per-task confidence fix is not deployed yet, record Part 4
  from the local build and say so on screen, or deploy it first.

---

## Part 1. The problem (0:00 to 0:45)

*Home page, hero visible.*

Hi, we're the Main Street AI team. Small business owners hear about AI tools
every day, but they don't have time to figure out which one actually fits a
restaurant, a clinic or an HVAC shop. Review sites tell you what people liked.
They don't tell you whether a tool does your specific job, what it will really
cost you each month, or whether you're already paying for something that
covers it.

So we built Main Street AI. You tell it your business and the job you need
done, and it shows tools that were actually checked for that job, with the
price and the source. And when you want to talk it through, there's Penny, our
assistant.

---

## Part 2. UI walkthrough, the guided flow (0:45 to 3:00)

*Scroll slowly to the carousel.*

Here are some common situations. Each slide is a real kind of business with a
real problem, like missed calls or staff scheduling.

*Scroll to step 1. Type "Restaurant" in the business field.*

Let's be a restaurant owner. I type my business here.

*Click the "Staff scheduling" chip on a carousel slide.*

Now I pick a task, staff scheduling. Notice the business still says
Restaurant. That's one of the bugs we fixed. I'll come back to it.

*Results appear. Pause on the summary bar.*

The top tells me there's one recommended tool and three more options.

*Point at the Recommended card.*

"Recommended" means one thing only. We checked this tool for this exact task,
for this kind of business. You see the monthly price, and if you open details,
every fact links to the vendor page it came from and the date we checked it.

*Scroll to More options.*

Everything else goes under More options. Each card is simple: the name, a
one-line summary, a link to the website, a button to compare and a heart to
save it. We don't stamp these as good fits, because we haven't proven that yet.

*Click "Add to compare" on two tools, open the comparison.*

I can put up to three side by side. I choose the tasks I care about and the
table shows which tool covers which task and the added monthly cost. If I
already pay for a tool, it tells me so instead of making me buy it twice.

*Change the task to something with no checked tool, for example a clinic and
appointment reminders.*

Here's a case where nothing has been checked yet for this task. Instead of a
"zero recommended" message or a page full of question marks, you get "Tools to
look at": real tools in this area with a link to their site. Honest, and still
useful.

---

## Part 3. Penny, the assistant (3:00 to 4:45)

*Click "Ask Penny about these options".*

This is Penny. You can talk to her the way you'd talk to a friend who knows
software.

*Type: "I run a small restaurant, about 12 staff. I need scheduling that
doesn't cost much. What should I use?"*

*While it streams:* Penny is reading our catalog live through a tool call, not
from memory.

*When the answer and cards appear:*

Her answer comes with the same cards you saw before, and the same rule
applies. She only calls something recommended when we've checked it.

Here's the part we care most about. Penny cannot just make up a price or a
feature. Before her answer reaches you, our server checks that she really
called the catalog tool, that the result matches what we expected, and that
every claim points to stored evidence. If any of that fails, you don't get a
made up answer. You get a safe fallback.

*Optional, if time allows: sign in, save a plan, show it under your account.*

If you sign in, you can save plans and favourites, and your chat history comes
back next time. That's tied to your account only. Nobody else can read it.

---

## Part 4. Architecture (4:45 to 6:45)

*Switch to the architecture diagram (docs/architecture.md, the nine service
diagram). Zoom in so the boxes are readable.*

Here's how it's built. It runs on one Azure virtual machine in Belgium Central,
as nine Docker Compose services.

*Point at each box as you name it.*

- Caddy is the front door. It handles HTTPS and security headers.
- The FastAPI app holds the core logic: matching, comparison, plans and
  sign-in checks. The matching is deterministic. The model never decides what
  is recommended.
- Hermes is the agent runtime that runs Penny.
- The MCP executor is the only tool Penny can call. It's read-only and it gives
  public catalog details. Every call leaves a receipt.
- The model gateway meters every model request. It reserves the cost before the
  call and settles it after. That's how we keep a hard spending cap.
- The verification worker discovers new tools and checks vendor pages for
  prices and features.
- The renderer is a sandboxed Chromium for pages that need JavaScript. It can
  only reach the internet through a guarded proxy that blocks private
  addresses.
- Redis keeps chat history per account, and SQLite holds the catalog, plans,
  receipts and the spend ledgers.

Sign-in uses Supabase. We verify the actual token with Supabase on every
request, we don't just decode it. The model is Claude Haiku 4.5 through
OpenRouter.

*Switch to the Penny sequence diagram.*

This is the flow for one Penny answer. The app registers what it expects
before Penny runs. Penny calls the tool, the tool writes a receipt with a hash
of the result. When Penny finishes, the app checks that receipt and hash
itself. A model saying "success" is never enough.

And the budget is real. We set lifetime limits: four dollars for chat, one
dollar for discovery, ten dollars total for testing. The whole project so far
has used about four and a half dollars.

---

## Part 5. The most critical issues we fixed (6:45 to 8:30)

*Simple slide or text overlay with the issue title for each one.*

We want to be honest about what broke, because finding these is what made the
product trustworthy.

**1. Tools looked recommended when they weren't.**
*Show a before screenshot if you have one, then the current Recommended / More
options screen.*
When we checked one tool for a task, like Homebase for restaurant scheduling,
the page showed the tools next to it as "Also a good fit", even though nobody
had checked them. We ran an audit of 240 business and task combinations and
found 25 where this happened, including medical staff scheduling, which is
exactly where a wrong answer matters. We fixed it at the data level. Each tool
now carries which tasks it was checked for, and the page only says Recommended
when that's true.

**2. The page was full of "not sure" labels.**
Cards used to say things like "Needs checking" or "Source not found". That's
honest, but it's noise for a business owner. Now if we don't know a fact, we
leave it off. The full record, with sources and dates, is still kept in the
backend.

**3. The carousel changed your business.**
If you typed Restaurant and then clicked a shortcut on a coffee shop slide,
your business quietly became Coffee shop and the results changed. Now what you
type is kept.

**4. Penny could describe features a tool never returned.**
In early tests the model wrote nice sounding descriptions that weren't in our
data. That's why we added the receipt and evidence check you saw in the
architecture. Penny can only say what the catalog actually returned.

**5. Prices that were really guesses.**
Some vendor pages show annual or per-seat prices, or hide them behind
JavaScript. We now only accept a monthly price when the plan, the price and the
currency all come from the same official page. If it's unclear, we don't show
a price at all.

---

## Part 6. Close (8:30 to 9:00)

*Back to the home page.*

So that's Main Street AI. You tell it your business and your problem. It shows
you tools that were actually checked for that job, the real monthly cost and
the source, and Penny helps you think it through without making things up.

Next, we're adding sourced customer reviews and making long chats more
resilient.

Thanks for watching.

---

## Notes for whoever records

- Keep every claim on screen true to what the site shows on recording day. If
  something in this script isn't live yet, cut that line rather than fake it.
- Don't show a real named business's weaknesses. Use the sample businesses.
- The spend numbers are from 2026-11-08. Check the ledgers before quoting them
  again.
- Each Penny question uses a few model requests. Rehearse with the browsing
  flow and ask Penny only during the real take.
