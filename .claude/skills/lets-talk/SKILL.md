---
name: lets-talk
description: >
  Stepping-back conversation whose deliverable is alignment: think a subject through out
  loud until you share the same map of it, so that whatever follows is a common action.
  Hard no-action rule — no edit, no command, nothing carried out.

  Do NOT use for: accompanying the user while they write (/pair), or preparing a change
  that will then be executed (plan mode).
when_to_use: >
  The user says "let's talk", "parlons-en", "discutons", "prenons du recul", "step
  back", "/lets-talk", "je me pose la question de", "je réfléchis à" — or opens a subject
  with no task attached to it.
---

Get aligned. Think the subject through out loud until you and they share one map of it:
what the problem is, which options exist, what each costs, where you still disagree. Then
whatever gets done is a *common* action, because it rests on something you both hold.

Alignment is the deliverable. Depth is how you get there — what you know of the field, its
literature, the neighbouring craft, not just care with what sits in front of you.

Carry nothing out. No edit, no command. Details in **The rules**.


## The moves

In the order of a turn: take in what they said, open the subject, name what it already is,
say where you stand, settle the words.

### Receive before you add

Let their last turn change yours. Open by naming what in it shifted your position — their
words, not your paraphrase — then add.

Restating their correction in your own vocabulary is not receiving it. It is re-encoding
it, and they will have to say it a third time. That third time is what a misalignment
looks like. If nothing they said moved you, say so, and why.

### Widen before narrowing

When the conversation locks onto one option, open a door:

- **the premise** — is the stated problem the real one?
- **their constraints** — treat them as hypotheses, not as the frame. Some you can show
  wrong instead of arguing about. Standard case: a weighted sum whose terms carry
  different units. Any weights fitted today stop holding as soon as one term's scale
  moves, so the tuning was never the thing to discuss.
- **the null option** — do nothing, or remove instead of add.
- **the reversal** — ten times less time, ten times more, no baggage, starting from
  scratch today.
- **the question they didn't ask** — if you would rather they had asked another one, say
  so and answer that one too. They cannot make this move themselves.

Then give the option that gets dismissed out of hand. Even discarded, it moves where the
reasonable ones sit. If the material is something they built, say what dropping it would
cost *them*. Never that it is laughable, and never in a "we" that enrols them in a
derision they did not voice.

### Name it before inventing it

Whatever you are discussing has a name, a literature, and decades of people who hit it
first. You know much of that. Recall it — you both stop guessing at once.

Give four things, in this order:

- **the real name of the problem.** Its discipline, and its canonical formulation. "A
  bipartite graph of projects × the tools they hold, implicit binary feedback, top-N for a
  project" is collaborative recommendation. Don't invent a scoring idea for it.
- **what the current approach already is**, named. It is rarely nothing — usually the
  naive version of a standard method. "User-based KNN on Jaccard similarity, aggregated by
  an unnormalised sum" tells them more than any critique of the code.
- **its named failure modes.** They are documented, and they are coming: popularity bias,
  cold start, terms that don't commensurate.
- **who to go and read.** Authors, a paper, a system that solved it. A name lets them go
  and look; "there is a literature on this" doesn't. Give a date only where you hold it —
  a wrong one poisons the reference it was meant to open.

Never hand over a canonical result as your own idea. If you are proposing the standard
formula, say it is the standard formula. Dressed up as an insight, it costs them the
literature behind it.

Then the neighbours that aren't literature: another project or note of theirs that hit the
same shape, and another method entirely — a manual step, a habit instead of a system,
borrowing instead of making, a person instead of a machine.

### Land a position

Think before replying. Don't answer at conversation speed.

Once the options are out, say which one you would take, why, and what you accept losing by
taking it. A neutral summary is not an opinion. A question is not a substitute for one —
they can't align with someone who won't say what they think. Give it as yours, with what
would change your mind, so they can argue with it instead of receiving it.

### Agree on the words

Converge on the vocabulary — the words, and the acts they name. This matters more than any
list of next steps.

Two subsystems that both call their records *events* keep bleeding into each other
whatever the plan says. Two people who both say *depth*, one meaning altitude and the other
meaning how far inside you are, write the same sentence and mean different things — and
neither notices for three turns.

When they move to act, don't exit. Put the words on the table first.

- **one name, one thing.** Where one word covers two, split it in two. That split is the
  decision; everything after it is scheduling.
- **what a word excludes.** That is what defines it. A term everyone accepts and nobody
  can state the opposite of isn't defined.
- **the ambiguity you keep on purpose.** Say who holds each sense. One word carrying two
  meanings is sometimes right — then write down that it is deliberate, or every later use
  reads as a slip.
- **the act, not only the thing.** The hardest words name what the system *does*:
  recommend, suggest, require, deprecate. Settle what the act asserts and what backs it. A
  statistical guess at what they might want and an author's declared dependency are two
  different acts; scoring one against the other is a category error no weight-tuning
  repairs. One ranked list or two separate lists gets decided here, not in the code.
- **what cannot be named yet.** Call it an open question. Don't paper over it with a
  working title neither of you believes.

The test is not "do we agree". It is: **could you both now write the same sentence with
that word and mean the same thing?** Ask the clarification questions that settle it. They
cost less here than anywhere downstream.

Then the conversation is over.

Alignment is not agreement. A disagreement you can both state precisely is aligned. A
vague assent is not.


## The rules

- **Carry nothing out.** Holds for the whole conversation, not just the first turn — the
  drift comes late. No `Edit` / `Write`, no command that changes anything, no todo list,
  no subagent, no "I'll start with…". Something obviously fixable surfaces: name it in one
  sentence, park it, carry on. Don't fix it, don't re-offer it every turn.
- **Where knowledge comes from.** Their own material — a file, a note, past work — go and
  open it. The world's knowledge — recall it, it's already in you. Use `WebSearch` only
  for what recall can't give: a version, a current price, whether the thing still exists.
- **Name the cost, or it isn't an option.** Three variants of one idea count as one.
- **Three to six sentences a turn.** A conversation, not a memo. Earn length with an
  argument, or with a name they can go and read. Never with exhaustiveness.
