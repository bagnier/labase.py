---
name: maintain-principles
description: >
  Checks that the codebase still holds what AGENTS.md states and the README claims, and that the
  claims registry's tests really prove it: each section goes to an adversarial-audit agent, and
  every break found is filed in ROADMAP.md, as an issue or as a principle proposal.

  Do NOT use for: bringing the README's inventories in line with the code (sync-readme), or
  fixing what the audit finds — this skill only files.
when_to_use: >
  "/maintain-principles", "maintenance des principes", "est-ce que le code tient ses principes",
  or a heading substring to check only matching sections: "/maintain-principles Time".
argument-hint: "[heading substring …]"
disable-model-invocation: true
---

This skill does corrective maintenance only. AGENTS.md and the README are taken as right, and the
question is whether the code, and the tests that claim to hold it, still live up to it. Fix nothing
and commit nothing.

The user is away for the whole run, and nobody will answer. Run every step to the end without
asking anything or waiting for a confirmation:

- **An ambiguous case** (a duplicate or not, an issue or a proposal, a unit's boundary): take the
  most reasonable reading, file accordingly, and note the choice in the log.
- **A unit that fails** (a refused tool, an agent that errors or returns nothing usable): note it
  in the log and move on to the next unit.
- **The end of the run:** the report is the last message. It ends on facts, never on a
  question.


## The run log

Every run is written to `.claude/logs/maintain-principles.md`, newest run at the end; create the
file and its folder if they are missing. The log is written as the run goes, never at the end
only, so that a run cut short still says how far it got. Take times from `date '+%F %H:%M'`.

The run opens with its header, before the first dispatch:

```
## Run {date time} — {git rev-parse --short HEAD}

Arguments: {the skill's arguments, or "none"} · {N} units selected
```

Each unit adds one entry once its breaks are filed, and before the next dispatch:

```
### {start}-{end} {heading}

- agent: {tokens} tokens · {tool uses} tool uses · {duration} min
- breaks: {N} ({n} invalidates, {n} weakens, {n} caveat) · held: {N}
- filed as issues: {one line per item, its impact first, or "none"}
- filed as proposals: {one line per item, or "none"}
- skipped as duplicates: {one line per break, or "none"}
- ambiguities: {the case and the reading taken, or "none"}
- to_research: {the briefs, or "none"}
```

The agent figures come from the completion notification's usage. A unit that failed gets the same
heading and a single line instead: `- failed: {reason}`.

The run closes with its footer:

```
Ended {date time} · {n} units audited, {n} failed, {n} never dispatched · {total} tokens ·
{n} issues ({n} security, {n} correctness, {n} drift), {n} proposals and {n} classes filed
```


## 1. List the units

From the repo root:

```sh
python3 "${CLAUDE_SKILL_DIR}/units.py"
```

Each unit prints on one line as `{NN} {document} {start}-{end} {heading} · {n} claims`: each
`###` principle of AGENTS.md, and the section around any claim of `tests/meta/claims.py` that
falls outside them, in the README, marked `[claims only]`. The numbering is stable for given
documents.

The skill's arguments are: "$ARGUMENTS". When that is empty, keep every unit. Otherwise keep
only the units whose heading contains one of its words, case-insensitive.

A run that did not reach its footer can be resumed. If the log's last run has no `Ended` line
and was made at the current `HEAD`, drop the units it already logged without a `failed` line,
and say so in the new header: `· resumed: {n} units already audited at this HEAD`. At any other
`HEAD`, audit everything again, because the code under those findings has moved.

Then write the run header.


## 2. Dispatch, one at a time

Send each unit to its own `adversarial-audit` agent, and never run more than one at a time: each
audit is a long run, and it draws on the same subscription quota as the user's own sessions.
Launch the next one only once the previous unit's log entry is written. Pass
`run_in_background: true` explicitly, because the project's agent hook refuses the call
otherwise.

The agent's brief is [brief.md](brief.md), next to this file; the agent reads it itself. The
prompt only points at it, with the unit number and this skill's directory filled in, and adds
nothing else, because the agent owns its report shape:

```
Read {skill directory}/brief.md whole and follow it. Your unit is {NN}.
```


## 3. File each break as it arrives

Once a report is in, file its breaks in ROADMAP.md, then write the unit's log entry.

- **What gets filed:** a break of severity `invalidates` or `weakens`. A `caveat` is left out.
  A break that is `grounded: unverified` is filed with its `to_run` command, so that whoever
  picks it up knows the check is still owed.
- **Duplicates:** check the whole of ROADMAP.md, every section included. A break already there,
  or already filed from another unit in this run, is not filed again. The same `file:line`, or
  the same fault in other words, counts as a duplicate. A `**class**` item is the exception: it
  is never a duplicate of anything. A break that matches one is still filed on its own, with its
  own `file:line`, because the class is worked from its instances' addresses.
- **Impact:** the agent's severity says how far the sentence falls, not what the fault
  costs. Judge the cost yourself and give each issue one tag:
  - `security`: someone can read, change or forge what they should not, or a secret leaks;
  - `correctness`: the product or its guarantees misbehave — lost data, a wrong answer, a test
    that stays green over a broken rule;
  - `drift`: the code departs from the text with no practical consequence.
- **Where and how:** a `security` issue goes at the top of the `## issues` list, the others at
  its end, in the shape the existing items have: `- [ ]`, then the fault in one or two
  sentences, then `→` and the direction, then the `[file.py:N](path#LN)` links. Lines are
  wrapped at 100 characters, and the language is English. The item opens with its impact, then
  the section it breaks, and the claim name when the break concerns one:
  ``**security** · AGENTS `Time` (`never-call-datetime-now`): …`` — `README` for a section of the
  README.
- **A break in a holder test:** the direction names the test to tighten.

Two kinds of break go to `## principle proposals` instead of `## issues`, because they are about
what AGENTS.md should say rather than about what the code does:

- **An unstated rule the code upholds everywhere:** a missing-premise break whose case says so.
  If the code breaks the rule somewhere, it is an issue instead.
- **A sentence the practice deliberately departs from:** the fix would change a chosen way of
  working (a workflow, a skill, a build step, a design decision) rather than a defect. Decide this
  yourself from the case, even when the agent reports it as a plain break.

Each proposal is an item of the same shape: the rule written as AGENTS.md would state it, then
the section it came from and what depends on it, then the links. Read AGENTS.md before filing:
a rule already stated there, even in other words, is not a proposal.


## 4. Name the classes

The audit reads one unit at a time, so a fault that recurs across units arrives as N separate
reports and is filed as N separate items — right, since each has its own address, but the shape
they share is stated nowhere. Once the last unit is logged, read back the `filed as issues` and
`filed as proposals` lines of this run's entries in the log — the log, not the run's own context,
which by then is many compactions old — and group them by the shape of the fault rather than by
the section it came from.

A shape carrying three items or more is a class, on two conditions:

- **It names a mechanism, not a quality.** "A holder reads the source text where it should
  interrogate the mounted artefact" is a class; "the holder tests are weak" is not, and is
  dropped rather than filed vague.
- **One fix reaches every instance.** Where each instance needs its own reading of its own code,
  the items are neighbours, not a class.

Do this once, at the end, on the whole run, never as the third instance arrives: a shape the run
has not finished producing gets named from the few instances seen so far, and what comes out is
the vague wording the first condition rejects. On a resumed run, read the entries the resume
dropped as well — they were written at this same `HEAD` and their items are in ROADMAP.md.

A class goes at the top of `## issues`, above the `security` items, in the shape
`` - [ ] **class** · {the mechanism in one sentence} · {N} instances ``, then `→` and the one
direction that covers them, then the links of two instances far enough apart to show the range.
Nothing else moves: the N items stay where they are, each with its own `file:line`.


## 5. Report

Once the classes are filed, write them into the log above the footer:

```
### Classes

- {the mechanism} · {N} instances · units {NN}, {NN}, …
```

Then write the run footer, and end with a short message that gives the footer's figures, names
the classes, lists the items filed in ROADMAP.md, names the units that failed or were never
dispatched, and points to the log for the rest.
