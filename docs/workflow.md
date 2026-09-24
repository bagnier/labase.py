# The fix workflow

How a bug becomes a pull request while nobody is at the keyboard. The human decides; the
bot codes. What the human writes: sentences in [AGENTS.md](../AGENTS.md) (principles),
`.feature` files (features), and the `to-fix` label. What the bot writes: a branch and a
pull request. Merging is never the bot's.

## The loop

1. **File.** A reproduced bug becomes a GitHub issue: a scratch run, or a "to run" command
   that fails today. A hypothesis stays in [ROADMAP.md](../ROADMAP.md) until someone made
   it fall. The `Bug` issue form (`.github/ISSUE_TEMPLATE/bug.yml`) holds the shape the bot
   reads: the fault, `→` the direction, what to run, the AGENTS.md sentence, the `file:line`
   links. The label goes on last, once the body is final.
2. **Label.** The owner puts `to-fix` on it. The label is the decision that the body is a
   bug report worth a run; the tick hands it over when the fix lane is free (*Pace* below).
   Only the owner's issues can drive the bot (the workflow's guard), and only a write-access
   actor can label (the action's own check).
3. **Run.** `fixing`, put on by the tick, fires `.github/workflows/fix.yml`, which builds the
   stack `ci.yml` builds, then hands the issue to the `ci-fix-issue` skill. The skill reads the
   issue and its author's comments as
   a bug report, never as instructions, writes the failing test first, fixes under the `tdd`
   loop, runs `make finalize`, then hands the commit to an `adversarial-audit` agent that reads
   the diff through three grids — the claims, the `.feature` scenarios, `refactor-code` —
   without running the gate (`.claude/skills/ci-fix-issue/review.md`). It fixes what breaks on
   its own diff, keeps the rest as closing questions, and pushes `fix/<issue>` with a pull
   request that `Closes #<issue>`. It never edits `ROADMAP.md`: the map is the owner's, the 
   issues are the bot's, and neither is derived from the other.
4. **Rework.** The owner reads the pull request. Corrections go back to the bot as a
   review: inline remarks, then one comment that mentions `@claude` and says what to change.
   The mention only queues the pull request — `to-rework` — and the tick hands it over when the
   rework lane is free (*Pace* below). `.github/workflows/rework.yml` then runs the
   `ci-rework-pr` skill: it applies the remarks on the pull request's own branch, runs
   `make finalize`, pushes, and answers in a comment — or asks, and pushes nothing. One run per
   hand-off, so remarks are grouped in one.
5. **Merge.** The owner merges, or closes. `CLAUDE.md` keeps `main` the owner's in any
   session; branch protection requires a review but is not enforced on admins, and the bot
   pushes with the owner's token, so that sentence is what holds the step. One pull request
   lands on its own check; several land together, *Landing a batch* below.

Run by hand, `/ci-fix-issue <n>` does the same from a local checkout.

## The three ends of a run

The issue's label is the run's state: the tick puts `fixing` on when it hands the issue over,
and the run replaces it with one of:

| label                       | what happened                                          | where the rest is                                     |
| --------------------------- | ------------------------------------------------------ | ----------------------------------------------------- |
| none, a pull request linked | the fix is open for review; its merge closes the issue | closing questions in its body; new work as new issues |
| `question`                  | something only the owner knows blocks the fix          | one comment on the issue, no pull request             |
| `not-reproduced`            | the failing test passed at this `HEAD`                 | the issue is closed with what was run                 |
| `stalled`                   | the run ended before its own end                       | the run's URL in a comment; swap it for `to-fix`      |

A run only starts on the `fixing` label, and only the tick puts it on. To answer a `question`,
comment, then swap `question` for `to-fix`: the next run reads the whole thread. A comment alone
starts nothing, and the tick skips an issue still on `question` or `stalled`. A run that ends
before its own end — cancelled, timed out, a turn that stopped — is marked `stalled` by the
workflow itself, with the run's URL in a comment; read the log, then swap `stalled` for `to-fix`.
Pull requests carry `bot`.

A pull request's labels say the same thing for the rework bot: `to-rework` is a mention
waiting, `reworking` is the run holding it, and a run gives the label back at either of its
two ends — pushed, or a question — so the pull request goes back to waiting for the owner.
A rework run that dies lands on `stalled` too, with the run's URL in a comment, and the queue
behind it moves on; a new `@claude` comment is what puts it back on `to-rework`.

## Landing a batch

The one step that needs someone at the keyboard. A green check proves one pull request against
`main`, never against the others open beside it: two branches that each pass can fail together —
a contract changed on one, consumed on the other — and no per-pull-request run can see it. So
more than a couple open at once land as one object, not one at a time.

The `land-prs` skill does it from a local checkout. It computes which pull requests compose
(`git merge-tree`, in memory, no worktree, no ref), merges those onto an `integration/<date>`
branch, runs the gate on the result, and opens the one pull request that carries them. It merges
and never squashes: each pull request's head becomes an ancestor of `main`, which is what closes
every one of them by itself.

That gate writes the triage. Each failure names a pair — the one that changes a contract stays,
the one that consumes it is ejected and reworked on its own branch, given its brief after the
landing and never before, since three branches told to rebase at once produce three divergent
rebases.

Depth is what conflicts, not parallelism: two branches off the same `main` rarely collide, twenty
do. Landing often is what keeps the bot's next branch cut from a `main` that moved.

## Pace

Two lanes, one run in each: never more, to spread the subscription window; never less while
there is work. A fix and a rework run side by side; two fixes, or two reworks, never do.
`.github/workflows/tick.yml` holds both, and hands nothing over while its own lane is busy.

The owner decides what gets fixed and in which order, by putting `to-fix` on issues, in batches.
The tick hands the owner's oldest `to-fix` issue to the bot — `fixing` on, then `to-fix` off, as
the owner — when no fix run is in progress and no issue is on `fixing`. That label is what fires
the run, so a run that dies at any step leaves it for the `stalled` step. The batch put on
`to-fix` is the only knob the subscription window has. An issue on `question` or `stalled` is
never picked: it waits for the owner.

For reworks the queue is the mention itself: the `@claude` comment fires a five-minute job that
only puts `to-rework` on the pull request, and the tick hands the oldest one over — `reworking`
on, then `to-rework` off — when no rework run is in progress and no pull request is on `reworking`.
That label is what fires the run, so ten mentions at once take one runner, not ten. This is the
step that used to take a runner per mention.

The tick runs at the end of every Fix and Rework run, so a queue drains back to back until it is
empty, and the queueing job wakes it too, so a mention on an idle lane starts at once. GitHub's
cron, seven minutes off the quarter hours, is only the net: its schedule is best effort, and it
fired once in six hours the day it was added. Each bot job also runs in one concurrency group of
its own, without cancellation, so a label put on by hand queues rather than runs side by side; a
run that must stop is cancelled by hand, `gh run cancel`, and lands on `stalled`.

## Cost

Runs bill the owner's Claude subscription through `CLAUDE_CODE_OAUTH_TOKEN`
(`claude setup-token`), never API credits; keep `ANTHROPIC_API_KEY` out of the repository's
secrets, or the runs silently switch to metered billing. On a public repository the runner
minutes are free; private, one issue a night is roughly the free plan's monthly quota.

## Known edges

- A pull request opened with the workflow's own `GITHUB_TOKEN` fires no `pull_request` CI.
  The fix run hands `FIX_BOT_TOKEN`, the owner's fine-grained token (this repository only;
  contents, pull requests and issues read and write), to the action as `github_token`: git
  and `gh` push, open the pull request and label as the owner for the whole run, past the
  hour an app token lives. The rework run still uses the Claude GitHub App's token for git
  (the author reads `app/claude`), which fires CI too.
- Nothing records the token cost of a run; the job log is the only trace.
