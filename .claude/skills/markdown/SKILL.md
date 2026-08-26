---
name: markdown
description: >
  Syntax and writing-style conventions for markdown notes: Obsidian syntax,
  wikilinks, heading and spacing rules, and restraint — go easy on bold, one styling
  effect at a time.

  Do NOT use for: deciding where a note belongs (/vault-organization), or reshaping an
  existing note's content (/refactor-notes).
when_to_use: >
  Before creating or editing ANY .md note or pushes back on formatting.
paths: "**/*.md"
---

## Principles

- prefer **Obsidian syntax** (callouts, embeds, frontmatter, tags, math, mermaid) for any md file.
- inside of the Obsidian vault, prefer wikilinks `[[link]]` to `[../link]`.
- **Go easy on bold.** Only where it's critical to insist.
- prefer one and only one styling effect.

## Imperative rules

- Never use a `#` title in the note body — the filename is the title. The first heading level is `##`.
- Never hard-wrap a paragraph. One paragraph = one line, however long — no wrapping at 80 or
  100 chars. Obsidian renders a manual newline as a line break, so a wrapped paragraph reads
  as broken prose. Only lists, tables and code blocks carry their own line structure.
- Never bold a link or a wikilink: `[[link]]`, never `**[[link]]**`.
- `[[Link]]` every concept that has a note: 
  ✅ `[[Buzz Aldrin]] effectue trois sorties`, ❌ `**Buzz Aldrin** effectue trois sorties`.
- Alias only when the alias says what the title cannot: 
  ✅ `[[Córdoba|le lieu du crime]]`, ❌ `[[_Protagonistes|protagoniste]]`.
- Mean one thing, link the section: `[[Córdoba#Le Turnverein]]` — it renders as the section title, so it needs no alias.
- Never bold a section heading: `## Section`, never `## **Section**`.
- Never fake a section with a lone `**Something**` line — use a real `## Section`.
- `- **Term:** definition` list items are fine.
- Two blank lines before every `## Section` — one is not enough.
- Never more than two blank lines in a row.
- No `---` / `***` dividers in the body — structure with a `## Section`.
- Use `→` arrows for calls to action.
- tables should be readable on screen so 150 chars per line max.
- a standalone enumeration (its own sentence, not embedded in a paragraph) renders as `-`
  bullets, not inline commas — e.g. "Source: A, B, C" → three bullets. Leave enumerations
  inside dense prose untouched.
