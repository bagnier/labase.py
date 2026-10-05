---
name: maintain-principles
description: >
  Checks that the codebase still holds what AGENTS.md states and the README claims, and that the
  claims registry's tests really prove it: each section goes to an adversarial-audit agent, and
  every break found is collected in one file.

  Do NOT use for: bringing the README's inventories in line with the code (sync-readme), or
  fixing what the audit finds.
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

- **An ambiguous case** (a break or a proposal, a unit's boundary): take the most reasonable
  reading, collect accordingly, and note the choice in the log.
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

Each unit adds one entry once its breaks are collected, and before the next dispatch:

```
### {start}-{end} {heading}

- agent: {tokens} tokens · {tool uses} tool uses · {duration} min
- breaks: {N} ({n} invalidates, {n} weakens, {n} caveat) · held: {N}
- collected: {one line per break, its short name, or "none"}
- proposals: {one line per rule, or "none"}
- ambiguities: {the case and the reading taken, or "none"}
- to_research: {the briefs, or "none"}
```

The agent figures come from the completion notification's usage. A unit that failed gets the same
heading and a single line instead: `- failed: {reason}`.

The run closes with its footer:

```
Ended {date time} · {n} units audited, {n} failed, {n} never dispatched · {total} tokens ·
{n} breaks and {n} proposals collected in {the breaks file}
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


## 3. Collect each break as it arrives

Once a report is in, collect its breaks, then write the unit's log entry. The breaks file is
`.cache/maintain-principles/{short HEAD}.md`: each break goes under its unit's heading, as the
agent wrote it — its case, `at`, `grounded` and `to_run` are what whoever reads the file starts
from. A resumed run at the same `HEAD` appends to the same file.

- **What is collected:** a break of severity `invalidates` or `weakens`, under `## Breaks`. A
  `caveat` is left out.
- **Proposals:** two kinds of break are about what AGENTS.md should say rather than about what the
  code does, and go under `## Proposals`, as the rule written the way AGENTS.md would state it,
  the section it came from, what depends on it, and the links:
  - **an unstated rule the code upholds everywhere** — a missing-premise break whose case says so.
    If the code breaks the rule somewhere, it is a break instead;
  - **a sentence the practice deliberately departs from** — the fix would change a chosen way of
    working (a workflow, a skill, a build step, a design decision) rather than a defect. Decide
    this yourself from the case, even when the agent reports it as a plain break.

  Read AGENTS.md before collecting one: a rule already stated there, even in other words, is not
  a proposal.


## 4. Report

Write the run footer, and end with a short message that gives the footer's figures, the path of
the breaks file, the proposals, the units that failed or were never dispatched, and points to the
log for the rest.
