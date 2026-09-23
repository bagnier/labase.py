---
name: land-prs
description: >
  Takes the open pull requests, computes which ones compose, gates the batch as one branch, and
  opens the single pull request that lands them — with a rework brief for each one it ejected.

  Do NOT use for: one pull request (ci-rework-pr), or one issue (ci-fix-issue).
when_to_use: >
  "/land-prs", "atterris les PR", "fais passer le lot", "on merge tout ça" — whenever more
  than a couple of pull requests are open at once.
argument-hint: "<pull request numbers, or nothing for every open one>"
disable-model-invocation: true
---

This skill lands one batch and nothing else. It never commits, pushes or merges on `main`: it ends
on a pull request the owner merges, the way `ci-fix-issue` ends on one.

What it writes into the repository is in English — the pull request, its body, every comment,
the commit messages — whatever language the owner's own reviews and issues are written in.

A green check proves one pull request against `main`, never against the others open beside it. Two
branches that each pass can fail together — a contract changed on one, consumed on the other — and
no per-pull-request run can see it. So the batch is the unit: one branch, one gate, one verdict.
The pull requests to take are "$ARGUMENTS", or every open one when that is empty.


## The two ends of a run

- **A pull request.** The integration branch is green and open against `main`, its body naming what
  it carries and what it ejected, and every ejected pull request has its rework brief.
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


## Partition, without a worktree

`git merge-tree` merges in memory and `git commit-tree` chains the result, so the whole partition
costs seconds and creates no ref, no branch and no checkout:

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

```sh
git switch -c "integration/$(date +%Y-%m-%d)" origin/main
for n in 81 82; do git merge --no-ff -m "merge #$n" "refs/prsim/$n"; done
```


## Gate it in a scratch worktree

Run this block whole, never the `cp` alone. A `.env.test` copied verbatim points at the main
checkout's ports and the stack dies on `Bind for 0.0.0.0:54422 failed: port is already allocated` —
but only once `lint` has passed and `make test-stack` finally runs, so a first red gate hides the
trap and the second one springs it. `scripts/worktree.py` holds the port block each checkout gets:

```sh
git worktree add --detach worktrees/batch HEAD
cp .env .env.test worktrees/batch/
ln -s "$PWD/node_modules" worktrees/batch/node_modules
PYTHONPATH=. uv run python -c "
from pathlib import Path
from scripts.envfile import merge_env
from scripts.worktree import test_block_base, test_stack_settings
merge_env(Path('.env.test'), Path('worktrees/batch/.env.test'),
          test_stack_settings(test_block_base('batch')))
"
grep -q ':54[45]' worktrees/batch/.env.test && echo "PORTS NOT REWRITTEN — rerun the block"
```

Then `uv sync --all-groups && make finalize` in it, waited for as the rules say for where you are.
`make finalize`, not `make check`: it opens on `js-build`, and a fresh worktree has none of the
built assets — `static/js/htmx.min.js` and `static/css/tailwind.css` are gitignored outputs, so
`git worktree add` does not bring them. A browser run without htmx sends no request at all, and
every `expect_response` waits out its thirty seconds: a whole lane of timeouts, reproducible to
the test, with not one assertion among them.

Not `test-e2e` either: the browser lane is nine minutes, it is the lane a flake costs a scenario
in, and the integration pull request's own CI runs it anyway. What the local gate owes is the
answer no per-pull-request run could give — that the composition builds, types and passes the
suite.

`make … ; echo "exit:$?"` leaves the shell's own exit at 0, so a completion notification reports
success on a red gate: the log's last line is the verdict, never the notification.

Remove the worktree and its stack when the batch has landed — `make test-stack-rm` from inside it,
then `git worktree remove`.


## When the gate is red

Each failure names a pair. The one that changes a contract stays, the one that consumes it is
ejected, the branch is rebuilt without it and gated again. Eject, re-gate, until green.

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


## Pull request

```sh
git push -u origin "integration/$(date +%Y-%m-%d)"
gh pr create --base main --head "integration/$(date +%Y-%m-%d)" --label bot \
  --title "<what the batch lands, as one sentence>" --body-file /tmp/batch.md
```

The body, in this order: what it carries, one line per pull request with its number and title; what
was ejected, one line each with the reason; what the gate gave. No history, no narration.


## The ejected

After the pull request is open, never before: three branches told to rebase at once produce three
divergent rebases against a `main` about to move. One comment per ejected pull request, mentioning
`@claude`, saying what state it must now sit on and what to change — `ci-rework-pr` takes it from
there and merges `main` into its own branch itself.


## Cadence

Depth is what conflicts, not parallelism: two branches off the same `main` rarely collide, twenty
do. Run this often enough that the queue stays shallow — the next branch is then cut from a `main`
that moved, which is the same fix applied upstream.


## Report

Which end the run took, the pull request URL, what it carries, and what was ejected with the brief
each one got.
