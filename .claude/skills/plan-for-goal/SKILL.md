---
name: plan-for-goal
description: >
  Writes a plan around the goals worth reaching and the tactics that could reach them,
  instead of an ordered list of edits guessed before opening the files.

  Do NOT use for: thinking a subject through with no change attached (/lets-talk).
when_to_use: >
  The user asks for a plan, "fais-moi un plan", "on s'y prend comment", "par où on
  commence", "/plan-for-goal" — or plan mode opens on work whose route is not obvious.
---

The plan is written in plan mode, argued out with the user, then frozen: approved, it is
read-only, and its steps become the todo list the work runs on. Everything below follows
from that — what was not put on the table before approval cannot be changed after it.


## The shape

```md
## actual situation

- <fact>

## goals

- <goal>

## out of scope

- <excluded>

## tactics

- <tactic>

## steps

- <step>

## final validation

- <validation>
```


## Stand on verified ground

What is the actual situation?

The situation is facts checked in the last few minutes, not recalled: files opened, commands
run, versions read. Anything the plan hinges on and you did not verify is not a fact — go
and check it, or write it down as an unknown that the first step resolves.

Constraints belong here too: what must keep working, what cannot be touched, what is already
half-done. A plan that ignores what is in the way is a wish.


## Goals worth the development

What are we trying to achieve?

A goal is what is true once the work lands, stated so it can be recognised — not a task in
the imperative. "Imports resolve from a single place" is a goal; "refactor the loader" is a
step wearing a goal's clothes.

Two or three of them, and drop any that would not be worth the development on its own. If
they only pay off all together, that is one goal, not four.


## Out of scope

What are we deliberately not doing?

What a reader could reasonably expect from the goals above and will not get: the adjacent bug
the situation surfaced, the cleanup the work will brush against, the second half of the
problem. Not the improbable — "not rewriting it in another language" bounds nothing.

It is the last moment for the user to pull one of those back in. Afterwards it binds the
other way: work drifting into it is off-plan, and a step turning out to need something listed
here re-opens the plan instead of quietly absorbing it.


## Tactics before steps

What could possibly be effective to reach the goals?

The patterns, tools and refactorings that could serve the goals. Name the means, not its
implementation. The list is ordered, best guess on top — the order carries the preference,
nothing else is argued on the line. During the journey, if a tactic does not succeed, this
list is the resource of possible alternatives to try.


## A journey that can stop anywhere

How do we get there without breaking anything on the way?

Each step leaves the project working: it builds, tests pass, nothing is half-wired. The plan
must be droppable after any step and still have left the ground better than it found it.

Each step becomes one todo item, and is written to survive as one: a single line, ordered,
either done or not done — never half. A step nobody could start without guessing is two
steps; a step that would stay in progress across most of the work is several.

Say what a step has to achieve, not the exact edit — the detail you cannot know before
opening the file is precisely the one not to commit to, since the plan can no longer be
corrected once it is approved.


## Validation written before the work

How will we know it is actually done?

The last section is written now, while nothing is at stake, and holds what someone else
could run or look at: a command with the output it should print, a behaviour to reproduce, a
case that used to break. "Verify it works" validates nothing.

It becomes the closing todos, after the last step: nothing is called done until every one of
them has been walked, and one that fails sends the work back to the steps, not to the goals.


## Re-read before submitting

The plan is shown once and cannot be repaired afterwards, so it gets one pass before it goes
out. Not to shorten it — to stop it saying the same thing twice, which is what makes the
choices hard to see:

- a fact stated in two sections: keep it where it does work, cut the echo;
- two steps that are one step, or a step that only restates a goal;
- a validation line another one already covers;
- a tactic that is a rewording of another — three variants of one idea count as one;
- anything in the situation that changes nothing in what follows.
