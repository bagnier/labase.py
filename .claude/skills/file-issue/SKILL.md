---
name: file-issue
description: >
  Files one or more GitHub issues in the shape the fix bot reads, from whatever names the fault:
  a ROADMAP.md line, an audit break, a failing test, a sentence from the user. Fills the form's
  sections, runs `gh issue create`, never puts `auto-fix` on.

  Do NOT use for: fixing anything (ci-fix-issue), or finding what is wrong (maintain-principles).
when_to_use: >
  "/file-issue", "file une issue", "crée une issue pour", "fais-en une issue", "file les bugs du
  ROADMAP" — or whenever a fault is established and someone says it should become an issue.
argument-hint: "<what names the fault: a ROADMAP line, a path, a sentence>"
disable-model-invocation: true
---

An issue is the fix bot's whole brief, so it carries the four things `ci-fix-issue` takes from it
and nothing else: the fault, the direction, the reproduction, the links. Its shape is the `Bug`
form's, `.github/ISSUE_TEMPLATE/bug.yml`: read the form first, and write the body with its
sections, under its labels, in its order — the form is the one place the shape is stated.

What names the fault is "$ARGUMENTS".


## 1. Establish the fault

Read what the argument points at. A ROADMAP.md item already has the shape: the fault, `→` the
direction, the links, often a "to run" or a "scratch run" and the rule it breaks. An audit break
has its case, its `to_run` and its location. A sentence from the user has the fault and maybe
nothing else: then open the code it names, and find the rest.

One issue, one fault. Two faults in one line are two issues. A fault nobody reproduced is still
an issue — the label is what says it is reproduced, and the label is not yours.


## 2. Write the sections

- **Title**: the fault as one sentence, what is wrong, never a topic — "`make backup-storage`
  stops at 100 objects per folder and reports success", not "backup storage".
- **What happens, and what should**: one sentence each.
- **Direction**: one line after `→`, the direction not the solution; the failing test decides.
- **To run**: what fails today — a command, a pytest node id, or a scenario in the drivers'
  terms. From the item's "to run" or "scratch run" when it has one; otherwise written from the
  fault, as the reproduction the bot will turn into its red test.
- **Rule it breaks**: the statement the fault contradicts, when there is one — an AGENTS.md
  sentence, quoted, or a scenario of a `.feature` file. Left out otherwise.
- **Where**: the `file:line` links, one per line.

Nothing addressed to the bot in any section: it reads the issue as a bug report, never as
instructions.


## 3. File

One command per issue, the body as a `### <section label>` heading per section:

```sh
gh issue create --label bug --title "<title>" --body "$(cat <<'EOF'
### What happens, and what should

...
EOF
)"
```

The form's labels (`bug`) and nothing else: `auto-fix` is the user's decision, on the issue,
later. For a batch, write the drafts to a file under `.cache/` first, read them once as the bot
will, then file them in one loop. End with the URLs, one per line.
