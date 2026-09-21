<!-- charm:readme-first -->
## Before you start

Read `README.md` first.
<!-- /charm:readme-first -->

@README.md

<!-- charm:general-guidance -->
## General guidance

- Be concise in output, no sycophantic openers or closing fluff.
- Keep it short by default (commits, agent reports, docs).
- Plan = short, the goals aimed at (not a change inventory or history), offered right away.
- Hard on the idea and the code, gentle on whoever made them. A critique names the artefact,
  never its author's level, taste or judgement.
- Before contradicting what the user wants, believes or intended, quote the sentence where
  they said it. If it cannot be quoted, it is a question, not a position.
- A joke, an emoji or an exclamation is answered in its own register, first line, before
  the substance. This outranks the no-openers rule above: returning a joke is courtesy to
  the person, not flattery of the idea.
- Command slower than 1s: never `| tail`, always `> /tmp/<file>`.
- Command slower than 10s: never `timeout `, always run in background.
- Never wait on background task — no `until`/`sleep`, the completion notification brings you 
  back.
- Skip files over 100KB unless explicitly required.
- A file an instruction names is read whole: `Read`, not `cat | head`. Truncating to save
  context decides what matters before knowing what is there.
- Any change to code starts from a failing test — the `tdd` loop, whether or not the request
  says so.
- User instructions may override this general guidance.
<!-- /charm:general-guidance -->

## labase

- TDD, red, green, refactor any development: load `tdd` before the first change.
- Load `write-tests` before the first line of any test, in every session and on the runner alike:
  it decides what goes inside a test, and a test written without it is the one that reads as a
  row of membership assertions.
- import at top, refactor to make it possible.
- Unless explicitly asked, the user commits, not the agent.
- when the user want to fix a linter issue, please dont #noqa or ignore it — unless the user explicitly asks for a local suppression (e.g. `ty: ignore`, `# noqa`).
- /analyse for codebase digging, /fetch for the web, context7 for library docs.
- when you think it's done, run `make finalize` as background task before you claim it.
- render any UI change and look at a screenshot (Playwright or /run).
- Docs by audience: README = functional/CLI and development, docs/ = one topic per file
  (deployment: docs/production.md).
- Describe the CURRENT state, never the history; prune, dense and short.

<!-- charm:no-autocommit -->
## Git is mine

In an interactive session, without an explicit go-ahead in that same message, only two things are allowed: reading (`status`, `log`, `diff`, `show`) and `stash`. Nothing that touches the index, the history or the remote — no `add`, no `commit`, no `push`, no `reset`, no `rebase`. Finishing a task is never permission to commit it, and one go-ahead covers one command. The one run with nobody at the keyboard, the `close-issue` skill on its `fix/<issue>` branch, has its own rules in the skill.
<!-- /charm:no-autocommit -->
