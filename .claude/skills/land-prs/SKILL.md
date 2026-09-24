---
name: land-prs
description: >
  Takes the open pull requests, computes which ones compose, gates the batch as one branch, and
  opens the single pull request that lands them — telling each one it ejected why, and what its
  branch will need.

  Do NOT use for: one pull request (ci-rework-pr), or one issue (ci-fix-issue).
when_to_use: >
  "/land-prs", "atterris les PR", "fais passer le lot", "on merge tout ça" — whenever more
  than a couple of pull requests are open at once.
argument-hint: "<pull request numbers, or nothing for every open one>"
disable-model-invocation: true
---

This skill lands one batch and nothing else. It never commits, pushes or merges on `main`: it ends
on a pull request the owner merges, the way `ci-fix-issue` ends on one. And it never works in the
owner's checkout: everything from the listing on happens in a worktree of its own.

What it writes into the repository is in English — the pull request, its body, every comment,
the commit messages — whatever language the owner's own reviews and issues are written in.

A green check proves one pull request against `main`, never against the others open beside it. Two
branches that each pass can fail together — a contract changed on one, consumed on the other — and
no per-pull-request run can see it. So the batch is the unit: one branch, one gate, one verdict.
The pull requests to take are "$ARGUMENTS", or every open one when that is empty.


## The two ends of a run

- **A pull request.** The integration branch is green, reviewed and open against `main`, its body
  naming what it carries and what it ejected, and every ejected pull request has its note.
- **A question.** Two pull requests answer the same fault differently, and which one survives is
  the owner's call. Nothing pushed, one comment naming the two and what each does.

A pull request whose own check is red is that pull request's problem, not the batch's: leave it out
and say so. Everything else that does not compose is ejected, never judged.


## Take the pull requests

```sh
gh pr list --state open --limit 100 --json number,title,statusCheckRollup
```

`--limit` is not optional: `gh pr list` stops at 30 and says nothing, dropping the oldest — which
are the ones most likely to conflict and most in need of landing.


## The worktree, first

The main checkout belongs to the owner. A `git switch -c` there moves the branch under whatever
they have open, and a gate running twenty minutes holds it for twenty minutes. So the batch is cut
its own worktree before the first merge, and every command from here on runs inside it — the
fetches, the merges, the gate, the push.

```sh
make worktree NAME=batch    # the one command that runs in the main checkout
cd worktrees/batch
git fetch -q origin main
git switch -c "integration/$(date +%Y-%m-%d)" origin/main
```

`make worktree` is what gives a checkout its own everything, and hand-rolling any of it is the
mistake: it clones `.env` and `.env.test` from the main one onto the port block
`test_block_base("batch")` derives from the name (545xx and up — the main checkout keeps its
544xx), symlinks `node_modules`, and runs `uv sync --all-groups`. A `.env.test` copied verbatim
instead points the stack at the main checkout's ports and it dies on `Bind for 0.0.0.0:54422
failed: port is already allocated` — but only once `lint` has passed and `make test-stack` finally
runs, so a first red gate hides the trap and the second one springs it.

`NAME=batch` is the name, not a choice: the block is derived from it. The target also provisions a
dev schema and bucket the gate never touches, so the dev stack has to be up — and if it is not, it
dies having already made the worktree and its env files, leaving one half-cut to finish or remove
by hand. It refuses outright when `worktrees/batch` is still there, so the last batch is torn down
before the next is cut, never reused: it sits on that batch's commit.

The `git switch` is where the branch is chosen, and it is the reason the worktree is not simply
worked on as it comes: `make worktree` cuts its own `batch` branch from wherever the main checkout
happens to stand, which is not what a batch is built on. A second batch the same day collides on
the branch name — suffix it `-2`, `-3`, then read it back with `git branch --show-current` rather
than spelling the date out again.


## Partition, in memory

`git merge-tree` merges in memory and `git commit-tree` chains the result, so the whole partition
costs seconds and leaves no branch and no checkout behind — only the `refs/prsim/*` this fetch
writes, shared by every worktree of the repository:

```sh
for n in 81 82 83; do git fetch -q origin "pull/$n/head:refs/prsim/$n" --force; done
```

Then merge each head onto the accumulating commit, keeping the ones that apply:

```sh
CUR=$(git rev-parse origin/main)
for n in 81 82 83; do
  H=$(git rev-parse "refs/prsim/$n")
  OUT=$(git merge-tree --write-tree --messages "$CUR" "$H") \
    && CUR=$(git commit-tree "$(echo "$OUT" | head -1)" -p "$CUR" -p "$H" -m "sim $n") \
    && echo "clean $n" || echo "conflict $n"
done
```

Write the numbers in the `for` list itself: zsh does not word-split an unquoted variable, so
`for n in $PRS` passes the whole list as one argument.

The order is a decision, not a detail — it names who conflicts. Within a cluster touching one file,
the pull request that **changes a contract** goes first and its consumers follow; otherwise
ascending number, which is oldest first.


## The integration branch

Merge, never squash, never rebase. Each pull request's head becomes an ancestor of `main` when the
batch lands, and that is what closes every one of them by itself; a squash orphans them all and
leaves them open against a base they can no longer reach.

The worktree is already on the branch, at `origin/main`: there is nothing to switch, and no
checkout of the owner's to switch it in.

```sh
for n in 81 82; do git merge --no-ff -m "merge #$n" "refs/prsim/$n"; done
```


## Gate it

`make finalize`, in the worktree, waited for as the rules say for where you are — the dependencies
are already synced, `make worktree` having done it. `make finalize`, not `make check`: it opens on
`js-build`, and a fresh worktree has none of the built assets — `static/js/htmx.min.js` and
`static/css/tailwind.css` are gitignored outputs, so a new checkout does not bring them. A browser
run without htmx sends no request at all, and every `expect_response` waits out its thirty
seconds: a whole lane of timeouts, reproducible to the test, with not one assertion among them.

Not `test-e2e` either: the browser lane is nine minutes, it is the lane a flake costs a scenario
in, and the integration pull request's own CI runs it anyway. What the local gate owes is the
answer no per-pull-request run could give — that the composition builds, types and passes the
suite.

`make … ; echo "exit:$?"` leaves the shell's own exit at 0, so a completion notification reports
success on a red gate: the log's last line is the verdict, never the notification.

Tear it down once the batch has landed: `make worktree-rm NAME=batch`, from the main checkout,
drops the worktree with its test stack and volumes, its dev schema and bucket, and the `batch`
branch `make worktree` cut. The integration branch is pushed by then, so it survives. The
simulation refs are the run's other litter — they pin every head fetched, ejected ones included:

```sh
git for-each-ref --format='%(refname)' refs/prsim | xargs -n1 git update-ref -d
```


## When the gate is red

Each failure names a pair. The one that changes a contract stays, the one that consumes it is
ejected, the branch is rebuilt without it and gated again. Eject, re-gate, until green.

Rebuilding throws `.env.test` back to its committed content, port block and all — it is a tracked
file, and `reset` restores it like any other. Carry it across, or the next stack comes up on the
main checkout's ports:

```sh
cp .env.test /tmp/batch.env.test
git reset --hard origin/main
cp /tmp/batch.env.test .env.test
```

A failure that names no pair is not the batch's, and ejecting anything for it ejects an innocent.
Read the failures before touching the branch:

```sh
grep -E "^E  +[a-zA-Z]" <gate log> | sed 's/^E *//' | sort | uniq -c | sort -rn | head
```

A broken batch fails assertions — a value expected against a value received. A starved machine
fails on time: `TimeoutError`, `Locator.click`, `wait_for_selector`. **No assertion among them and
timeouts throughout accuses the machine, never the batch**, and the browser lane is where it lands
first, its waits being what a loaded laptop or a contended runner crosses. Say in the pull request
body which run timed out on what, and leave the branch alone.

Do not try to isolate a scenario to settle it: the count above already has. And a node id passed
alongside `apps/` collects the whole lane anyway, so the isolation costs the full run and answers
nothing.

Never patch the integration branch itself: that is a commit nobody reviewed, on a branch carrying
everyone's work, and it hides the fault from the pull request that owns it.


## Adversarial review

The subject is the integration branch — these pull requests standing together — and nothing else:
what the run left off it was judged by the partition, not here. Every hunk on the branch was
reviewed and gated on its own pull request against the same base, so what no one has read is the
composition, and the gate does not read it either: it answers whether the branch *runs*, never
whether it still *means* what each pull request meant, a merge being silent exactly where both
sides agreed on the letter. So hand the branch to one `adversarial-audit` agent, started once it is
built so it reads while the gate runs, and take its report when the gate comes back:

```
Read .claude/skills/land-prs/review.md whole and follow it. Base: origin/main. Head: <branch>.
Carries: #<n>, #<n>, … The simulation refs refs/prsim/* are still there.
```

One review per batch, never a second on the answer to the first. It applies nothing and never runs
the gate, so a break marked `unverified` is run from its `to_run` command before anything is done
about it.

Either grid names a pair, and a pair is settled the way a red gate's is: eject one side, rebuild,
re-gate. Which side goes is the same rule — the one that changes a contract stays, the one that
consumes it leaves — and for an `[intent]` break it is the pull request that undid the thesis, not
the one whose promise it broke. Never the patch: a composition fixed by hand is a commit nobody
reviewed, which is what this review exists to refuse.


## Pull request

```sh
git push -u origin HEAD
gh pr create --base main --head "$(git branch --show-current)" --label bot \
  --title "<what the batch lands, as one sentence>" --body-file /tmp/batch.md
```

The body, in this order: what it carries, one line per pull request with its number and title; what
was ejected, one line each with the reason; what the gate gave, and what the review found and
what was done about it. No history, no narration.


## The ejected

After the pull request is open, never before: three branches told to rebase at once produce three
divergent rebases against a `main` about to move. One comment per ejected pull request, saying why
it was ejected and what its branch will need once the batch has landed.

**Ejection is not a review, so it does not mention `@claude`.** A `@claude` comment puts the pull
request on `to-rework`, and that queue holds one thing: a review the owner sent back. What
`ci-rework-pr` then looks for is *"every remark by the repository owner ... what the owner wants
changed in the diff"* — so a collision reaches it as a review with no ask, and the run answers it by
guessing which of two sound branches to bend. It burns a lane one rework at a time, and the label
itself states a fault the run did not find.

Which is what the two classes are for, and the comment says which one it is:

- **A defect of the pull request itself** — a committed artefact, a broken file, something wrong in
  the diff whatever else is open. That is a change to the diff, so it *is* a review: mention
  `@claude`, say what to change, and let the queue take it.
- **A collision with a sibling, or a stale base** — a textual conflict, a shared counter two
  branches moved to the same value, a branch `main` has moved under. **Nothing is wrong with the
  diff**, and saying so in the comment is half its purpose: the owner reads a label before a
  paragraph, and `to-rework` on a sound pull request says the opposite of what the run found. No
  mention, no label — the note stands, and the branch waits for a `main` that moved.

The same line holds when the run ejects on the gate rather than on a conflict: two pull requests
that are each right and only disagree once composed are a collision, not a fault, and neither one
is the one to blame.


## Cadence

Depth is what conflicts, not parallelism: two branches off the same `main` rarely collide, twenty
do. Run this often enough that the queue stays shallow — the next branch is then cut from a `main`
that moved, which is the same fix applied upstream.


## Report

Which end the run took, the pull request URL, what it carries, and what was ejected — saying, for
each one, whether it was its own defect or a collision, since only the first is queued for rework;
and what the adversarial review broke.
