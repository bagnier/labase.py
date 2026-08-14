---
name: fetch
description: >
  Retrieves a web resource whole and verifiably, escalating from curl to an impersonated
  fingerprint to a headless browser to Safari, only as far as each rung's verdict demands.

  Do NOT use for: library or framework documentation (context7 answers it with no fetch at all).
when_to_use: >
  Any URL to read; a page that came back truncated, empty, 403 or behind a login; a PDF, a
  timetable or a grid to extract; a research pass spread over many sources — or the user says
  "fetch", "fait des recherches".
---

Fetching fails in more ways than this ladder repairs, and a verdict's first job is to tell the
two apart. **A rung fixes** truncation, JS-only rendering, bot-blocking, and data that needs
clicking to appear. **No rung fixes** a server that errors or says nothing — `404`, `5xx`, a
timeout, a dead host — nor an identity you do not hold.

| rung | tool                          | fixes                                   |
| ---- | ----------------------------- | --------------------------------------- |
| 1    | curl                          | everything, most of the time            |
| 2    | `impersonate.py` (curl-cffi)  | TLS / HTTP/2 fingerprint blocking       |
| 3    | Playwright CLI                | JS rendering — one shot, to an artefact |
| 4    | Playwright MCP                | forms, clicks, any multi-step flow      |
| 5    | Safari, real and not headless | anti-bot that beats headless Playwright |

Four rules bind every rung.

**Never climb without a verdict.** A rung is earned by a failure signal from the rung below — a
status code, a byte count, a named error. A hunch is not a signal, and neither is prose.

**Go lateral before going up.** Re-aiming costs nothing, climbing costs a browser. Most
"blocked" pages are the wrong URL.

**One rung at a time**, with the two skips the decision table documents: data behind a form or a
click starts at rung 4, and a JS shell goes from 1 to 3 — rung 2 does not run JS either.

**Most failures are not climbable at all.** A server error, a dead host, an identity nobody here
holds: results to report, not obstacles to route around. The table marks them.

Announce a climb to rung 5 **before** making it, and report at the end which rung succeeded and
what was left unread.

## Never start with WebFetch

It returns a digest, not a resource: no status code, no byte count, no statement of what was
dropped — so a partial answer is indistinguishable from a complete one, and no verdict ever
triggers a climb. It is not a rung, and it never opens a fetch.

One exception, and it is not a fallback: **`claude.ai/code/artifact/{uuid}` URLs**, which it
reaches through the user's claude.ai login where `curl` gets only the SPA shell or a Cloudflare
403. Its answers are cached 15 minutes per URL, so re-reading an artifact that has just changed
returns the old one.

## Lateral before vertical

Before climbing, check the URL is the right one:

- the site's RSS / ICS / JSON feed rather than its HTML;
- WordPress (recognisable by `/wp-content/` in its URLs) → `/wp-json/wp/v2/posts?per_page=100`;
- `raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>` rather than the blob page; `gh api`
  for issues, PRs and releases;
- `llms.txt`, or the `.md` variant of a documentation page;
- **open-data feeds and machine formats** — GTFS for transport, GBFS for bikes, an OpenAPI or
  `/swagger.json` spec, `.well-known/`. A transport agency's GTFS gives exact stop coordinates
  and along-route distances that no HTML page publishes;
- **the JS bundle of a SPA**, grepped for endpoint names — it names the backend and its routes
  faster than any amount of rendering;
- **one index mined N times, rather than N leaf pages fetched once each** — an agenda page
  read for six days beats six event pages.

## Rung 1 — curl, with a verdict

```sh
"${CLAUDE_SKILL_DIR}/curl-verdict.sh" "$URL" timetable.html         # url, then output name
"${CLAUDE_SKILL_DIR}/curl-verdict.sh" "$URL" timetable.html --head  # extra curl options pass through
```

The second argument is a **name, not a path**: any directory it carries is dropped and the file
lands under `$FETCH_DIR`, `/tmp/fetch/<session-id>` by default. One flat directory per session,
so keep names unique — the same name twice overwrites. `FETCH_DIR` moves every download at once.

One file written, one line on stdout — and **the decision table below reads that line**:

```
http=200 318b text/html HTTP/2 redir=0 0.17s file=/tmp/fetch/3e1dc534/timetable.html https://example.com/
```

`file=` is the path to read afterwards; the cookie jar sits beside it as `<file>.cookies`.

Do not hand-roll a bare `curl` instead. The script bakes in four things the verdict depends on,
each easy to drop when retyping:

- **a Safari `--user-agent`.** A bare `403` is far more often a missing User-Agent than real
  blocking — it flips a good share of them to `200`.
- **`--output` to a file.** Never `| head`, `| tail` or `| less`. Piping recreates by hand the
  exact truncation this ladder exists to avoid, and hides the size.
- **coherent headers.** A Safari UA with no `Accept` and no `Accept-Language` is an
  inconsistency, and inconsistency is easier to detect than an honest client.
- **a cookie jar**, written as `<output>.cookies`. Many sites set a cookie then require it after
  a redirect; without one you collect a loop or a 403 and wrongly blame anti-bot.

Appended options win wherever curl keeps a single value — `--user-agent`, `--max-time`,
`--cookie`, `--cookie-jar` — so pass `--head`, `--range`, a shared jar, your own UA off a Mac.
**`--header` is the exception: it accumulates**, and a baked-in one cannot be removed from
outside. Adding `--header 'Accept: application/json'` leaves both Accept values in the request,
which servers read as the union — harmless, and the way to call a JSON endpoint.

It takes Homebrew's curl when present and falls back to `PATH` silently — on a Mac that fallback
is Apple's build, which is blocked more often.

### Reading what landed

| content-type       | do                                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `text/html`        | `pandoc --from html --to gfm --wrap=none timetable.html --output timetable.md`, then `Read` with `offset`/`limit`; `grep` it |
| `application/pdf`  | **do not convert** — `Read` it with `pages:`                                                                       |
| `application/json` | `jq` it                                                                                                            |

`Read` renders PDF pages **as images**, so column alignment survives — and in a timetable, a grid
or a scanned table the alignment _is_ the data. Extracting a PDF to text destroys it. When the
grid is rotated, diagonal or otherwise awkward, render and crop it: `pdftoppm -r 200 -png`, then
`sips -c/-z` to zoom, then `Read` the image.

Without `pandoc`, `Read` the raw `.html` with `offset`/`limit` and `grep` it. Noisy, but
complete. Never fall back to a pipe.

## The decision table

Driven by rung 1's verdict, not by judgement:

| verdict                                    | reading                  | action                                          |
| ------------------------------------------ | ------------------------ | ----------------------------------------------- |
| `200` · html · body has text               | ✅                       | pandoc → `Read`, done                           |
| `200` · pdf                                | ✅                       | `Read pages:`, done                             |
| `200` · very large index                   | wrong target             | **lateral** — feed, API, filtered page          |
| `403`/`429`                                | fingerprint or challenge | ↑ **rung 2**, then rung 3 if it holds           |
| `200` but body nearly empty                | JS shell                 | **lateral first** (find the API), then ↑ rung 3 |
| data behind a form or a click              | not fetchable            | **rung 4 directly**, skip rungs 1–3             |
| `404`                                      | wrong URL, or gone       | **one lateral** — check the path, then stop     |
| `500`/`502`/`504`, or a bare `503`         | the server is failing    | **no rung helps** — one retry later, then stop  |
| `000` · `0b` · curl 35/28 · openssl silent | the host is dead         | **no rung helps** — report and stop             |
| `401` · login · paywall · signup           | out of scope             | **stop** — never log in, register or pay        |

Three notes, for what reads wrong at a glance.

**A server error is not a block.** `404`, `500`, `502`, a bare `503`, a timeout, or TCP
connecting while TLS returns nothing — all server-side, none of it anti-bot. No rung reaches a
server that will not answer, rung 5 included, since Safari leaves from the same IP. Confirm a
silent host with `openssl s_client -connect host:443 </dev/null`. The one exception is a `503`
**whose body is a challenge page** — if it names Cloudflare or asks you to wait while your
browser is checked, that is the fingerprint row, not this one. Read the body before believing
the code.

**A JS shell announces an API.** Before launching a browser to render the page, find where it
pulls its data from: grep the JS bundle for endpoint names, try `/api`, `/swagger.json`,
`.well-known/`. Rendering is more expensive and less verifiable than the source. Call the
endpoint with the same rung-1 script — add `--header 'Accept: application/json'`, and when it
needs the session the page set, point `--cookie`/`--cookie-jar` at the page's own jar.

**No rung crosses a wall, and none is allowed to.** Two limits stack, and either alone is enough
to stop. _Technically_: rungs 1–4 carry no identity, and rung 5 finds **no usable session** —
this Mac browses private, nothing stays signed in. The one authenticated route is a storage
state the
user exported beforehand and you inject at rung 3 or 4. _By authority_: even where the form is
fillable, logging in, registering or paying is never yours to do — no credentials typed, no
terms accepted, no email or phone number submitted, no card. Report what the page gates and let
them decide.

## Rung 2 — a browser's fingerprint, without a browser

Rung 1 already sends a coherent header set, so a `403` that survives it is not a header problem.
It is usually a TLS or HTTP/2 fingerprint check, which no curl flag reaches.

`impersonate.py` ships next to this file. Address it through `${CLAUDE_SKILL_DIR}`, never a
relative path — under Claudian the working directory is the vault root, not the skill's project.

```sh
uv run "${CLAUDE_SKILL_DIR}/impersonate.py" --output timetable.html "$URL"   # safari by default
uv run "${CLAUDE_SKILL_DIR}/impersonate.py" --impersonate chrome --output timetable.html "$URL"
uv run "${CLAUDE_SKILL_DIR}/impersonate.py" --list                        # declared targets
```

`--output` obeys rung 1's rule: a name, resolved under `$FETCH_DIR`, reported as `file=`.

`--list` prints the _declared_ targets, some of which are not compiled into the free build and
fail with `ImpersonateError` — the unnumbered aliases (`safari`, `chrome`, `firefox`, `edge`) are
the safe bets.

It does not run JS: an SPA shell stays a shell, and an active Cloudflare challenge still needs a
real engine. Reach for it on a fingerprint verdict, not by preference — rung 1 stays the default,
and this one exposes a fraction of curl's surface (no ranges, no resume, no HEAD, no upload).

> [!warning] Its byte count is not comparable to curl's
> `%{size_download}` is bytes **on the wire**, the script returns the **decoded** body. On a
> gzipped page the ratio easily exceeds 5× — do not read a content difference into it.

## Rung 3 — a headless browser, one shot

Fetch to an artefact, read the artefact — the same shape as rung 1, with an engine behind it. No
server, no session, nothing persisted, and it runs wherever Bash does, Claudian included:

```sh
# Reuse the Playwright CLI already installed as a dependency of the MCP.
# Single source of truth: the version pinned in .mcp.json. No download.
PW=$(for d in ~/.npm/_npx/*/; do [ -d "$d/node_modules/@playwright/mcp" ] &&
     echo "$d/node_modules/playwright/cli.js"; done | head -1)

node "$PW" screenshot --browser webkit --full-page --wait-for-selector <sel> "$URL" "$FETCH_DIR/timetable.png"
node "$PW" pdf --browser chromium --wait-for-selector <sel> "$URL" "$FETCH_DIR/timetable.pdf"
```

The Playwright CLI resolves nothing — spell the destination out, with
`${FETCH_DIR:=/tmp/fetch/$CLAUDE_CODE_SESSION_ID}` when the shell has not set it yet.

If `$PW` comes back empty, the MCP has never run on this machine: trigger any MCP call once to
populate the npx cache, or go straight through the MCP tools.

> [!important] A pinned version, and never Chrome
> **Never `--browser chrome`** or `--channel chrome`: not the system browser, only the Chromium
> Playwright manages under `~/Library/Caches/ms-playwright/`.
>
> **Never a bare `npx playwright`** with no version — it pulls a different Chromium from the
> MCP's, and you pay for both. The CLI has no version of its own: it borrows the MCP's, so
> `.mcp.json` is the one thing to update.

Then `Read` the file — pixels for the screenshot, `pages:` for the PDF. `--load-storage <file>`
injects a saved login without persisting anything; `--device`, `--lang` and `--proxy-server` are
there when a site varies by client. To disguise at this rung use `--device`, never a raw UA
string: it sets UA, viewport and platform **together**, where a bare UA contradicts the engine.

Not everything yields at the first engine. Hardened anti-bot systems refuse headless Chromium
and say so **in the page rather than in the status code** — a `200` whose body is an "access
restricted" notice, sometimes naming an IP as though that were the cause. It usually is not:
**retry with the other engine before climbing** — `--browser chromium` ↔ `--browser webkit`,
starting with WebKit on a Mac. When both are refused, climb to **rung 5**, not rung 4: rung 4 is
this same headless Playwright and will be refused the same way.

## Rung 4 — a browser you can drive

Climb here for a **loop**, never for a block: click, fill, read, decide, click again — a form, a
delivery-slot picker, any multi-step flow the CLI cannot express in one command. It is also
where you land when the flow itself is unknown, since you can observe between actions instead of
guessing selectors blind.

The `playwright` MCP is configured `--headless --isolated`: nothing on disk, no profile survives
the session. It is pinned to one engine, so the engine swap stays rung 3's job. Its tool surface
costs context in every session that loads it — reach for it when the CLI genuinely cannot do the
job, not by preference.

Credentials without a fat profile, at either rung: a saved storage state — `--load-storage` on
the CLI, `browser_set_storage_state` on the MCP. Isolated session **plus** injected state =
logged in, nothing persisted. That state file is a secret — never commit it, never keep it in
the project.

## Rung 5 — safari

Not an identity rung — a **plausibility** rung. It drives the real Safari on the user's Mac
through Apple Events: a real WebKit engine, not headless, real window geometry, from their own
IP. Nothing on this ladder looks more like a person browsing, which is why an anti-bot verdict
lands here once both Playwright engines have been refused.

It carries **no session**. This Mac browses private, so nothing stays signed in between windows
— there is no cookie jar to inherit. Never climb here for a login or a paywall; those stop at
the table.

Announce the climb before making it. It opens windows on the user's own screen, and it is
fragile.

**Never the native-input tools here.** `safari_native_click`, `safari_native_type` and
`safari_native_keyboard` go through CGEvent, which on macOS 26+ **silently no-ops** — the call
reports success, nothing happened, and you cannot tell from the result. That is the exact
failure this ladder exists to prevent, at its most expensive rung. Use `safari_click`,
`safari_fill` or `safari_evaluate`, which go through the extension. When anything here behaves
oddly, `safari_doctor` names the broken link in the permission chain.

## When a rung is missing

The browser rungs are separate MCP servers — `playwright` for rungs 3–4, `safari` for rung 5 —
and neither is required for rungs 1–2 to work. If the table says climb and the tool is absent:

- say so plainly — which rung, and what it would have unblocked;
- stop at the rung reached, and **never present a rung-1 partial as the whole thing**.

An impossible escalation is a result to report, not a silence.

## Traceability

For anything that outlives the turn, record next to the content:

- the URL actually reached — `%{url_effective}`, after redirects, not the one typed;
- the date it was fetched, whenever the data has a shelf life (a timetable, a forecast, an
  opening hour);
- **how many independent sources agree.** A single-source fact is flagged as such; two
  sources that contradict each other are both kept, with the contradiction stated, never
  silently arbitrated;
- **a field observation as its own class** — a price actually paid, a door actually locked
  outranks any number of concordant pages, which can agree and still all be wrong.

## Guardrails

- One request at a time against the same host; `--max-time` always set.
- Keep the fetched file — re-reading it is free, re-fetching is not. It survives the whole
  session under `$FETCH_DIR`.
- Report the rung that succeeded, and what was left unread.
