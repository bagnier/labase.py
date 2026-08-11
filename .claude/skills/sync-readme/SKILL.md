---
name: sync-readme
description: >
  Brings README.md back in sync with the repo: takes the README's own last commit as the
  baseline, reads everything landed since (commits + working tree), and edits only the
  passages those changes contradict.

  Do NOT use for: drafting a release note from commits since the last tag (`changelog`).
when_to_use: >
  User asks to update / refresh / sync the README, says "mets à jour le README",
  "le README est-il à jour ?", or wants the doc caught up after a batch of commits.
---

## Range

Baseline = the README's own last commit, not the last tag nor `origin/main`.

```sh
git log -1 --follow --format='%H %ad %s' --date=short -- README.md   # baseline B
git log --reverse --no-merges --stat B..HEAD                        # what landed since
git status --short && git diff HEAD                                 # "now" includes the working tree
```

`git diff HEAD` is blind to untracked files: open what the `??` lines name.


## Edit surgically

- edit the sentences the changes contradict; never rewrite a section that still holds,
  never reorder, never restyle prose you are not correcting.
- match the README's language, heading case and tone.
- every command, flag, path or field you write must be traceable to the diff or the source
  you just read. When those two disagree, the current source decides, not the diff.
- a shipped feature drops its hedge: remove the "not implemented yet" wording and its
  ROADMAP pointer. Leave ROADMAP.md itself alone.


## verify before reporting done

Finding the diff is not the same as confirming the edit is true. For every sentence you
changed, re-check it against the live repo, not the diff you derived it from: the command
still runs as written, the flag still exists, the path still resolves. A diff tells you
what moved; only the current source tells you whether your new sentence is correct.


## report to user

- please report if you identify a new concept with no home in the README file.
- leave the edit uncommitted unless asked to commit.
