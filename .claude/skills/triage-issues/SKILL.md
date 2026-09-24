---
name: triage-issues
description: >
  Sorts the open GitHub issues against `main`, the pull requests and each other — fixed,
  duplicated, riding on a pull request, or best fixed in one diff — and, once the owner agrees,
  hands the issues one diff should fix to a carrier under the `carried` label.

  Do NOT use for: filing an issue (file-issue), fixing one (ci-fix-issue), or landing pull
  requests (land-prs).
when_to_use: >
  "/triage-issues", "fais le tour des issues", "y a-t-il des doublons ?", "des issues déjà
  fixées ?", "des issues à marquer ?", "regroupe les issues liées"
disable-model-invocation: true
---

This skill sorts the queue and nothing else: it posts one comment per carrier and moves labels,
never code, never a pull request, never a close — an issue found fixed is named for the owner to
close.

What it writes on GitHub is in English; the report to the owner is in the owner's language.


## Read the state

```sh
git fetch -q origin
gh issue list --state open --limit 200 --json number,title,labels,author,createdAt,body > /tmp/issues.json
gh pr list --state all --limit 100 --json number,title,state,headRefName,closingIssuesReferences > /tmp/prs.json
gh issue list --state closed --limit 100 --json number,title,closedAt
```

Read every body whole.


## Judge each issue against `main`, the pull requests and the other issues

Each of the three can already hold an issue's fix, so each is read before a verdict:

- **`main`** — open the `file:line` the issue links, as `origin/main` has it, and look for the
  fault it describes: the literal, the missing call, the sentence.
- **the pull requests** — an open one that closes the issue, or whose diff (`gh pr diff <n>`)
  rewrites the lines it names. An `integration/*` pull request only transports others: it is never
  one of them.
- **the other issues, open and closed** — the same fault at the same place, or a closed issue whose
  fix covered this one too (`gh issue view <n>` on any whose title comes close).

One verdict per issue:

- **fixed** — the fault is gone from `main`: the line as it reads now, and what removed it.
- **duplicate** — the same fault at the same place as another issue: the older one stands. Two
  faults under one AGENTS.md sentence, at two sites, are two issues — maybe one subject, which is
  pairing's business.
- **in a pull request** — its number.
- **written against a pull request** — the issue describes code only an open pull request has (a
  follow-up the adversarial review filed on that diff): it stands or falls with that pull request
  and goes into its rework, never into a carrier.
- **open** — the fault is on `main`, and nothing else holds its fix.


## Pair what one diff should fix

The owner's rule:

- **Same subject → together**, even with no file in common: three accessibility faults on three
  templates go in one diff, so the treatment is uniform.
- **Same lines → together**: two fixes rewriting the same region conflict when landed apart (a
  rename running through the lines around a check another issue changes).
- **Different subjects → apart**, even in one file or one registry, when their hunks are far enough
  for git to merge them.

Pair only issues on `to-fix` with no pull request and no `fixing`: `carried` on an issue the owner
never put on `to-fix` would fix it without their decision. The carrier is the oldest of the set,
the one the tick hands over first.

Propose each set with its reason in one line, and each pair set aside with its own. Nothing is
written before the owner agrees.


## Mark, once agreed

The queue moves while the owner reads: the tick hands issues over, runs open pull requests. Right
before writing, re-read every issue of the set:

```sh
gh issue view <n> --json state,labels,closedByPullRequestsReferences
```

All open, on `to-fix`, no linked pull request — or nothing is written for that set, and "When the
set has already moved" applies. Then, carrier first:

```sh
gh label create carried --force --color c5def5 \
  --description "Fixed with the issue whose comment names it; the tick never picks it"
gh issue comment <carrier> --body-file /tmp/carries-<carrier>.md
gh issue edit <carried> --remove-label to-fix --add-label carried   # each carried issue
```

The comment opens `Carries #<n>[ and #<m>]:`, then in one sentence why one diff fixes them — the
shared subject or the shared lines. It is posted as the owner: `ci-fix-issue` reads only the
author's comments, and takes only carried issues by the carrier's author. A posted comment is never
edited.

`carried` is a link, not a run's state: no run takes it off, so the list keeps showing the issue is
taken care of. Only the owner detaches one, by swapping it for `to-fix`.


## When the set has already moved

A carrier with a pull request or on `fixing`, or a carried issue on `fixing`, can no longer be
joined: a run reads its thread once, when it starts. Take off whatever label this pass put on, then
offer the two ways:

- **Restart as one** — `gh run cancel` the running fix (it lands on `to-unblock`), close the
  carrier's pull request unmerged, mark the set, put the carrier back on `to-fix`. Each step is
  irreversible and waits for its own go-ahead.
- **Let them run apart**, and align the pull requests afterwards in a rework.


## Report

The verdicts, grouped: fixed (with the line), duplicates, in a pull request, written against a pull
request, the sets proposed or marked with their carrier, the pairs set aside and why. Links for
every comment posted.
