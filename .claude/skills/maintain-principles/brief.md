You audit one unit of AGENTS.md or README.md: a section of it, held against the codebase at the
repo root.
Your prompt gives the unit number `NN` and the directory holding this file.


## Find the unit

From the repo root, run `python3 {that directory}/units.py NN`. Its first line gives the document
and lines of the unit and its scope. The lines after it list the claims of `tests/meta/claims.py`
whose quote lies in those lines, each held by its tests or waived with a reason. Then read those
lines.


## What to establish

Take the text as the standard. Report only where the code contradicts it, and never what the text
should say instead.

- **Scope `section`:** the code holds every sentence of those lines as written. Where a break
  shows that the sentence itself is false for good reasons, report it anyway, and say so in the
  case. Where the section holds only thanks to a rule it never states, report that rule as a
  missing-premise break, and say in the case whether the code upholds it everywhere.
- **Scope `claims only`:** the code holds each claim sentence the script printed, as written.
  The rest of those lines is prose about intent and only context, so nothing in it is a finding.

For a held claim, attack its tests as well: a change that would make the sentence false while
those tests stay green is a break, located at the test. A waived claim has nothing behind it, so
the code is its only evidence.
