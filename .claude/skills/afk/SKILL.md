---
name: afk
description: >
  Declares the user unavailable for a stretch — the agent resolves ambiguity itself
  instead of stopping to ask, and routes anything genuinely irreversible into a
  deferred, logged decision instead of blocking on it.

  Do NOT use for: a single "just do it, don't ask" instruction on one task — that's
  just following the instruction. This is for a whole stretch with no one to check
  with at all.
when_to_use: >
  The user says "afk", "je suis afk", "je pars", "je suis indisponible", "continue
  sans moi", "/afk", "I'm going to be away/unavailable", "work autonomously while
  I'm gone" — or otherwise flags they won't be reachable for questions for a while.
---

You are now working with no one to ask. Until the user's next message (or the session
ends), every question you'd normally raise gets resolved by you, not parked for them.

## Resolve, don't ask

- Never stop to ask a clarifying question. Pick the most reasonable interpretation,
  state the assumption in one line as you act on it, and keep moving.
- "I'd normally check with them first" becomes "pick the safest reasonable default and
  note it," not a reason to pause.

## The one exception: irreversible or high-blast-radius actions

Some actions can't be undone if the guess is wrong: force-push, `git reset --hard` on
unbacked-up work, deleting branches/files/records, sending a message, opening/closing a
PR or issue, paying for something, revoking access. For these:

1. Don't perform them on a guess.
2. Take the least-destructive path that keeps the option open instead — commit to a new
   branch rather than force-pushing, move a file aside rather than deleting it, draft a
   PR description without sending it.
3. Log the deferred decision (below) and move on to everything else that doesn't depend
   on it — one blocked step shouldn't stall the whole stretch.

## Keep a running log

Maintain one running note as you go, not a reconstruction at the end — long stretches
get compacted and detail gets lost. Use a file the user will naturally reopen: e.g.
`AFK_LOG.md` at the project root for code work, or a dated note in the vault for
notes work. Append to it if one already exists from earlier in this session. Per entry:
what got done, the assumption made (if any), and, for deferred items, why it stopped
and what's needed from the user.

## Coming back

When the user reappears, lead with the log — what got done, what was assumed, what's
waiting on their call. Don't make them dig through the transcript for it.
