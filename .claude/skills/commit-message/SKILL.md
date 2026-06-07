---
name: commit-message
description: >
  Analyse staged changes and propose a commit message.
  TRIGGER when: user asks for a commit message, says "commit message", "/commit-message",
  or asks "what should I put in the commit", "quel message de commit".
  Do NOT use for: actually creating the commit.
---

# Commit message skill

## Process

1. Run `git diff --staged` to read the staged changes.
2. If nothing is staged, say so and stop.
3. Analyse the diff: understand **why** this change exists, not just what changed.
   - Look at the context: what problem does it solve? what behaviour changes?
   - Infer intent from naming, structure, surrounding code.
4. Write a commit message following the rules below.
5. Output the commit message wrapped in a single code block (` ` ```) — nothing before or after, no commentary, no explanation.

## Rules

**Format: Conventional Commits**

```
<type>: <short imperative summary>

- <why bullet 1>   ← optional
- <why bullet 2>   ← optional
- <why bullet 3>   ← optional
```

- Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `style`, `perf`, `ci`
- Title line: ≤ 72 chars, imperative mood, no period at the end
- Body: **omit entirely** if the title alone is sufficient
- Body: **at most 3 bullets** if needed; each bullet explains _why_, not _what_
- Language: English

## Focus: why, not what

Bad:

```
perf(db): add index on created_at
- added migration for index
- updated query to use index
```

Good:

```
perf: index created_at to fix listing timeout on large datasets

- query was doing a full scan on 2M+ rows, timing out in production
- sorted listings are the most frequent read path
```
