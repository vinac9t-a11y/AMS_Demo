# Teleprompt — S7 leadership overview deck

Companion script for `docs/s7-leadership-overview.pptx`. One block per slide,
written to be spoken. Total run time about 5–6 minutes at a calm pace.
Scrubbed per hard rule 2 — refer to the end client only as "the client".

---

## Slide 1 — Title

Good morning, everyone. I want to take five minutes to show you what we are
building for the delivery scope — what it will do, and more importantly, how
we stay in control of it.

The one line at the top is the whole story: AI-assisted delivery, from a
business requirement all the way to a production release — with humans in
control at every point that matters.

## Slide 2 — The idea in one sentence

Here is the idea in a single sentence.

The AI does the heavy lifting of delivery — the analysis, the design, the user
stories, the code, the tests, the documentation. And nothing reaches
production without passing our checks.

I want to stress the second half as much as the first. This is not a black
box that produces software. Every step is gated, logged, and traceable — and
the rest of this presentation is really about that second half, because that
is where the confidence comes from.

## Slide 3 — How work will flow

This is how work will flow, left to right.

A business requirement comes in. The AI assesses it — what does it touch,
how big is it, what can be automated. It produces a design, with real
diagrams. Then — the first amber box — a person reviews that design and
approves it before anything else happens.

Only after that approval does the AI break the work into user stories, and
build and test against them. And before anything is released — the second
amber box — a person approves again.

The amber boxes are the point of this slide. If the reviewer rejects, the
pipeline stops. That is not a limitation we are working around — it is the
design. The system cannot run past a human who said no.

## Slide 4 — Nothing advances without passing a gate

Let me go one level deeper on the checkpoints, because this is the part I
most want you to remember. There are five gates between intake and release.

The first three are automated completeness checks. Is every requirement
mapped to a story? Does every story have testable acceptance criteria? Is
every criterion covered by code and tests? These run before any human spends
a minute reviewing — so people review complete work, not drafts.

Gate three is the one I would highlight: independent review. A second,
separate AI reviews the first one's output against the design. If it finds a
critical gap, the work is blocked. The principle is simple: no phase approves
its own work. The same rule we apply to people, applied to the AI.

And gate four is a person. The final call before release is always human.

These gates are real. A rejection genuinely stops the pipeline, and we will
demonstrate exactly that, live.

## Slide 5 — Every output can be traced back

The second thing that makes this trustworthy: everything is on the record.

The provenance ledger is a tamper-evident history of every artifact — who or
what produced it, when, and from which inputs.

The traceability matrix links everything end to end: requirement, design,
story, code, test, release. If a defect shows up in production, we trace it
backward to its requirement in one lookup — minutes, not days.

The activity log records every AI session — what it did, how long it took,
what came out. That gives us honest numbers on velocity and bottlenecks,
measured, not estimated.

And staleness detection closes a loop people often miss: if a design changes
after stories are written, everything downstream is automatically flagged
out-of-date and must be refreshed before release. Nothing ships against a
stale design.

## Slide 6 — The ten building blocks

Everything I have described comes down to ten building blocks, in three
groups — and the grouping is the easiest way to hold onto this.

The control group keeps humans in charge: the gated pipeline, the automated
completeness checks, the independent review, staleness detection.

The trust and audit group proves what happened: the ledger, the traceability
matrix, the activity log.

And the foundation group makes it repeatable: a clean architecture that
separates the rules from the workflows, quality standards for every story,
and managed change control for the delivery system itself — so when we
improve the factory, that change is assessed and versioned too.

Control keeps us in charge. Trust and audit proves it. Foundation makes it
last.

## Slide 7 — What happens next

So what happens next?

We build these ten capabilities point by point, in priority order. And we
hold ourselves to one rule throughout: every stage ends with something that
runs. A working demonstration, not a slide.

Two commitments worth stating plainly. First, anything simulated will be
clearly labelled as simulated — what you see running live is real, and we
will never blur that line. Second, the human checkpoints stay on until a
workflow has proven itself over repeated runs. Autonomy is earned, not
assumed.

By the end, you will see the pipeline run end to end, watch a gate block bad
work, and trace a finished output back to the requirement that caused it.

## Slide 8 — The takeaway

If you take one thing from these five minutes, make it this.

Speed comes from the AI. Confidence comes from the governance.

Every artifact is gated, logged, and traceable — and a human always holds
the final approval.

Happy to take questions.

---

## Q&A back-pocket lines

**"How accurate are the estimates?"** — Today they are placeholders, and we
label them as such. The plan is to ground estimation in historical delivery
data — past stories and the time they actually took.

**"Is any of this real yet?"** — The pipeline skeleton and the human review
gate run today. Artifacts that are staged are labelled staged, on screen. We
would rather show a smaller thing that genuinely runs than a bigger thing
that doesn't.

**"Why keep humans in the loop — doesn't that slow it down?"** — The gates
are where a workflow starts, not where it ends. Checkpoints come off only
after a workflow has proven itself over many runs. That removal is a
measurable milestone, not a hope.

**"What does the AI not cover?"** — Not every stream is AI-addressable — some
work routes to teams as ordinary tickets, and we count it as manual, not as
coverage. An honest coverage number that survives questioning beats a claimed
100% that doesn't.
