<!-- charm:readme-first -->
## Before you start

Read `README.md` first.
<!-- /charm:readme-first -->

<!-- charm:general-guidance -->
## General guidance

- Be concise in output, thorough in reasoning. Keep it short by default (commits, agent reports, docs) — this is the most frequently missed.
- No sycophantic openers or closing fluff.
- No explicit action request (a question, a doubt, a pasted plan, "wait/sleep") means: run NO tool — discuss or wait. ("discutons" / "let's talk" is the named case.)
- Read the right sources before concluding: the relevant files/generators, never from memory.
- Before declaring done: run it for real (the touched command/route/page) — green CI/tests are not enough.
- Plan = short, the goals aimed at (not a change inventory or history), offered right away.
- Never change scope without validation (no code when the request is about docs; no removal during a simplification) — announce first.
- Command slower than 1s: never `| tail`, always `> /tmp/<file>`.
- Skip files over 100KB unless explicitly required.
- User instructions may override this file.
<!-- /charm:general-guidance -->

## labase

- TDD, red, green, refactor any development.
- import at top, refactor to make it possible.
- Unless explicitly asked, the user commits, not the agent.
- when the user want to fix a linter issue, please dont #noqa or ignore it — unless the user explicitly asks for a local suppression (e.g. `ty: ignore`, `# noqa`).
- /research for codebase, web or documentation digging.
- /obsidian-markdown for any markdown edition.
- when you think it's done, run `make finalize` as background task before you claim it.
- render any UI change and look at a screenshot (Playwright or /run).
- Docs by audience: README = functional/CLI, DEV.md = development, INSTALL.md = deployment. 
- Describe the CURRENT state, never the history; prune, dense and short.
