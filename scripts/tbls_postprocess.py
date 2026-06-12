"""Remove enums from non-public schemas in tbls-generated README."""

import pathlib

f = pathlib.Path("docs/schema/README.md")
lines = f.read_text().splitlines(keepends=True)
out, in_enums = [], False
for line in lines:
    if line.startswith("## Enums"):
        in_enums = True
    elif line.startswith("## "):
        in_enums = False
    if (
        in_enums
        and line.startswith("| ")
        and not line.startswith("| Name")
        and not line.startswith("| ----")
    ):
        schema = line.split(".")[0].lstrip("| ")
        if schema not in ("public", "test"):
            continue
    out.append(line)
f.write_text("".join(out))
