<!-- charm:readme-first -->
## Before you start

Read `README.md` first.
<!-- /charm:readme-first -->

<!-- charm:general-guidance -->
## General guidance

- Be concise in output, no sycophantic openers or closing fluff.
- Keep it short by default (commits, agent reports, docs) — this is the most frequently missed.
- Plan = short, the goals aimed at (not a change inventory or history), offered right away.
- Hard on the idea and the code, gentle on whoever made them. A critique names the artefact
  — "this text bets on a reader who fills the gaps" — never its author's level, taste or
  judgement.
- Before contradicting what the user wants, believes or intended, quote the sentence where
  they said it. If it cannot be quoted, it is a question, not a position.
- A joke, an emoji or an exclamation is answered in its own register, first line, before
  the substance. This outranks the no-openers rule above: returning a joke is courtesy to
  the person, not flattery of the idea.
- Command slower than 1s: never `| tail`, always `> /tmp/<file>`.
- Skip files over 100KB unless explicitly required.
- User instructions may override this general guidance.
<!-- /charm:general-guidance -->

## labase

- TDD, red, green, refactor any development.
- import at top, refactor to make it possible.
- Unless explicitly asked, the user commits, not the agent.
- when the user want to fix a linter issue, please dont #noqa or ignore it — unless the user explicitly asks for a local suppression (e.g. `ty: ignore`, `# noqa`).
- /analyse for codebase digging, /fetch for the web, context7 for library docs.
- /markdown for any markdown edition.
- when you think it's done, run `make finalize` as background task before you claim it.
- render any UI change and look at a screenshot (Playwright or /run).
- Docs by audience: README = functional/CLI and development, docs/ = one topic per file
  (deployment: docs/production.md).
- Describe the CURRENT state, never the history; prune, dense and short.

<!-- charm:no-autocommit -->
## Git is mine

Without an explicit go-ahead in that same message, only two things are allowed: reading (`status`, `log`, `diff`, `show`) and `stash`. Nothing that touches the index, the history or the remote — no `add`, no `commit`, no `push`, no `reset`, no `rebase`. Finishing a task is never permission to commit it, and one go-ahead covers one command.
<!-- /charm:no-autocommit -->
