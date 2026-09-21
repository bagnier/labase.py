# The fix workflow

How a bug becomes a pull request while nobody is at the keyboard. The human decides; the
bot codes. What the human writes: sentences in [README.md](../README.md) (principles),
`.feature` files (features), and the `auto-fix` label. What the bot writes: a branch and a
pull request. Merging is never the bot's.

## The loop

1. **File.** A reproduced bug becomes a GitHub issue: a scratch run, or a "to run" command
   that fails today. A hypothesis stays in [ROADMAP.md](../ROADMAP.md) until someone made
   it fall. The `Bug` issue form (`.github/ISSUE_TEMPLATE/bug.yml`) holds the shape the bot
   reads: the fault, `→` the direction, what to run, the README sentence, the `file:line`
   links. The label goes on last, once the body is final.
2. **Label.** The owner puts `auto-fix` on it. The label is the decision that the body is a
   bug report worth a run; only the owner's issues can drive the bot (the workflow's guard),
   and only a write-access actor can label (the action's own check).
3. **Run.** `.github/workflows/fix.yml` builds the stack `ci.yml` builds, then hands the
   issue to the `close-issue` skill. The skill reads the issue and its author's comments as
   a bug report, never as instructions, writes the failing test first, fixes under the `tdd`
   loop, runs `make finalize`, and pushes `fix/<issue>` with a pull request that
   `Closes #<issue>`. It never edits `ROADMAP.md`: the map is the owner's, the issues are the
   bot's, and neither is derived from the other.
4. **Review.** The owner reads the pull request. Corrections go back to the bot as a
   review: inline remarks, then one comment that mentions `@claude` and says what to change.
   `.github/workflows/review.yml` hands the pull request to the `address-review` skill on that
   mention: it applies the remarks on the pull request's own branch, runs `make finalize`,
   pushes, and answers in a comment — or asks, and pushes nothing. One run per mention, so
   remarks are grouped in one.
5. **Merge.** The owner merges, or closes. `main` requires a review and refuses a direct
   push, so the bot cannot get past this step.

Run by hand, `/close-issue <n>` does the same from a local checkout.

## The three ends of a run

The issue's label is the run's state, set by the run itself: `auto-fix` becomes `fixing`
when it starts, then one of:

| label                       | what happened                                          | where the rest is                                     |
| --------------------------- | ------------------------------------------------------ | ----------------------------------------------------- |
| none, a pull request linked | the fix is open for review; its merge closes the issue | closing questions in its body; new work as new issues |
| `question`                  | something only the owner knows blocks the fix          | one comment on the issue, no pull request             |
| `not-reproduced`            | the failing test passed at this `HEAD`                 | the issue is closed with what was run                 |
| `stalled`                   | the run ended before its own end                       | the run's URL in a comment; put `auto-fix` back       |

A run only starts on the `auto-fix` label. To answer a `question`, comment, then put
`auto-fix` back: the next run reads the whole thread. A comment alone starts nothing. A run
that ends before its own end — cancelled, timed out, a turn that stopped — is marked
`stalled` by the workflow itself, with the run's URL in a comment; read the log, then put
`auto-fix` back. Pull requests carry `bot`.

## Cost

Runs bill the owner's Claude subscription through `CLAUDE_CODE_OAUTH_TOKEN`
(`claude setup-token`), never API credits; keep `ANTHROPIC_API_KEY` out of the repository's
secrets, or the runs silently switch to metered billing. On a public repository the runner
minutes are free; private, one issue a night is roughly the free plan's monthly quota.

## Known edges

- A pull request opened with the workflow's own `GITHUB_TOKEN` fires no `pull_request` CI.
  The action pushes and opens the pull request with the token of the Claude GitHub App
  installed on the repository (the author reads `app/claude`), which does fire it; `gh` in
  the run holds `FIX_BOT_TOKEN`, the owner's fine-grained token (this repository only;
  contents, pull requests and issues read and write), for the labels and comments.
- Nothing records the token cost of a run; the job log is the only trace.
