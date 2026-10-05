---
name: qualify-issues
description: >
  Turns faults someone found into drafts of the issues worth a fix, by tracing the path that
  reaches each one, searching the codebase for every other place it lives, reproducing it and
  matching it against what GitHub already holds.

  Do NOT use for: creating the issues on GitHub (file-issue).
when_to_use: >
  "/qualify-issues", "qualifie ces bugs", "est-ce que ça vaut une issue", "fais-en de bonnes
  issues", "ce problème existe ailleurs ?"
argument-hint: "<the candidates: a file, a report, a sentence>"
disable-model-invocation: true
---

A fault is worth an issue when something reaches it, and the issue is good when it names every
place the fault lives.

The candidates are "$ARGUMENTS", each a fault with a location, read on the code as `HEAD` has it.
Nothing is written on GitHub.


## 1. The path that reaches it

Trace from the faulty line through every caller, then theirs, up to an entry point: a route, a
job, a script, a deploy step, a user's action. Write it as a chain, with the conditions it needs
(a role, a setting, a dependency down, a race, an input):

```
POST /{org}/files/upload → upload_file → OrgFileRepository.add → repository.py:88
  — when storage answers 5xx
```

- **reached** — the path exists; its conditions go in the draft.
- **dead** — nothing calls the code. The direction is deletion.
- **latent** — only a change nobody made reaches it. Set aside, naming that change.


## 2. Where else it lives

Name the shape: the mechanism in one sentence, never a quality, never the site. Search the whole
codebase for it, spelled every way it can be, keep the hits where the same fault holds, and trace
each one as in step 1. Two candidates of one shape are one.

- **One instance** — one draft.
- **Several, one fix covers them** — one draft for the shape, listing every instance. Where a
  structural fix exists (read the source of truth, route every caller through one helper, check
  the category rather than its members), it is the direction.
- **Several, each needing its own reading** — one draft each, each naming the others.

A shape costs what its worst reached instance costs.


## 3. What it costs

- **security** — someone can read, change or forge what they should not, or a secret leaks.
- **correctness** — lost data, a wrong answer, a lie on screen, a failure nobody is told about.
- **dead code** — kept.
- **drift** — reached, but nobody is worse off. Set aside.

A fault in a test is **correctness** only when the rule it holds is reached and a change a
maintainer would make in passing slips past it — name that change. Otherwise, set aside.


## 4. Reproduce it

Run the reproduction here — a test node id, a script under `/tmp`, a query, a request — never the
whole suite. One instance per shape is enough.

- **It fails as said** — reproduced.
- **It passes** — set aside, with what ran and what it gave.
- **It cannot run here** — kept, with the scenario that would show it, marked as not run.


## 5. What GitHub already holds

```sh
gh issue list --state all --limit 10000 --json number,title,body,state,stateReason
gh pr list --state open --json number,title,closingIssuesReferences
```

Match on the shape and on each instance's `file:line`, in other words too:

- **an open issue** — set aside; the instances it misses become a draft "Beyond #n";
- **an open pull request on those lines** — set aside;
- **closed as completed** — the fault is back: a draft "Regressed after #n";
- **closed as not planned** — set aside.


## 6. Write the drafts

`.cache/qualify-issues/{short HEAD}.md`, in English: one `##` title per draft — the fault as one
sentence — over the sections of `.github/ISSUE_TEMPLATE/bug.yml` as `###` headings, in its order.
The path goes under what happens, every instance under where.


## Report

The drafts file, then one line per candidate: drafted, or set aside with its reason.
