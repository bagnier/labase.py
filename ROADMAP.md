> [!tip] An item listed here is not a debt, it is an opportunity.
> Nothing below is broken or promised. A line opens because it might be worth it — and closes
> just as well with "we're not doing this, delete the line" as with code. Replacing a brick that
> works with a brick that might work is a fair bet when the payoff is less code.


## issues

### bugs

Behaviour the code gets wrong — a lost fact, a silent outage, a harness that lies. Closed by code, one at a time.

- [ ] Three API scenarios failed once in the first full run with the lane on `app_rls`
  (2026-09-21) and pass alone and module-whole: `test_an_org_member_can_use_a_share_link`
  ("Cannot find primary org"), `test_an_occurrence_from_another_version_reopens_a_resolved_issue_as_regressed`
  (401 on the issues screen), and `test_upload_with_xss_characters_in_filename…` erroring at
  teardown on a GoTrue 404. Same family as the `auth.users` intermittents below, unconfirmed.
  [test_scenarios.py](apps/files/tests/e2e/test_scenarios.py)
- [ ] `test_owner_invites_a_new_user_as_member` failed once in a full run (2026-09-21) on a
  `memberships_user_id_fkey` violation — its owner's id no longer in `auth.users` — and passed
  alone. Same family as the rule books' deleted `@rls.local` users, unconfirmed.
  [org-invitations.feature:11](features/org-invitations.feature#L11)
- [ ] The database rule books are intermittent too: three full runs on 2026-09-20 each lost one
  RLS statement test to `InFailedSQLTransactionError` (`test_org_files_rls` twice,
  `test_the_database_gives_each_rule_its_verdict[api_keys:member-may-not-issue-key]` once), every
  one green alone. The harness savepoints each statement, so the abort comes from outside it —
  the likely seam is the FK lock a test transaction holds on `auth.users` against GoTrue's own
  writes to the same rows. The fallout is worse than the failure: the org's `@rls.local` users
  are deleted in the `finally`, but one run left an admin behind, and the two console admin
  scenarios after it failed on "the last admin" not being last. → catch the abort where it
  happens (log the first error, not the second), and make the user cleanup survive it.
  [authorization.py:128](tests/authorization.py#L128), [rls.py](tests/rls.py)
- [ ] The files browser scenarios are intermittent: `make flakehunt N=5` on them failed 2 runs out
  of 5 (2026-09-15), each a 30 s wait for the HTMX response of a row button — delete once, share
  twice. Not dated: never compared against the tree before the dependency upgrade. → `flakehunt`
  on that commit to date it, then whether the request leaves at all.
  [browser_base.py:352](tests/e2e/drivers/browser_base.py#L352),
  [driver_mixin_browser.py:122](apps/files/tests/e2e/driver_mixin_browser.py#L122),
  [driver_mixin_browser.py:235](apps/files/tests/e2e/driver_mixin_browser.py#L235)
- [ ] Nothing in `config.toml` reaches a hosted project — no `supabase config push` anywhere. A
  hosted project mails GoTrue's default templates, whose links carry no `token_hash` for the
  reset route, and keeps its own email quota. → push the config from the deploy path.
- [ ] AGENTS `A GET never delivers a session` ("mailed confirmation … resend on blocked unconfirmed sign-ins"):
  the shipped `config.toml` has `enable_confirmations = false`, so registering signs the account in
  at once, GoTrue never answers `email_not_confirmed` and the resend path is unreachable — while
  the JSON branch still answers "Please verify your email" (checked end to end). → turn
  confirmations on, or say the resend path waits on a deployment that does.
  [config.toml:22](supabase/config.toml#L22), [router.py:621](apps/auth/infra/router.py#L621)
- [ ] AGENTS `A GET never delivers a session` ("settings-gated (`profile.*_enabled`)"): email change and account
  deletion also re-authenticate with a password, so an OAuth-only account cannot use either with
  both settings on — `400 "Current password is incorrect."` (checked on a passwordless account),
  and the form shows the field to everyone. → accept a recent-session proof for a passwordless
  account. [router.py:404](apps/profile/infra/router.py#L404),
  [router.py:608](apps/profile/infra/router.py#L608)
- [ ] AGENTS `Each scenario runs isolated, on both drivers` ("wraps each scenario in a rolled-back transaction"): the rollback isolates
  only what goes through the overridden sessions — GoTrue, the files driver's external orgs and
  Storage objects, `run_sql` given-helpers and the background admin sessions all commit around it,
  each paid for by a hand-written delete or truncate. → state the boundary, or route those writes
  through the test connection. [api_base.py:158](tests/e2e/drivers/api_base.py#L158),
  [driver_mixin_api.py:36](apps/files/tests/e2e/driver_mixin_api.py#L36)


### the text overstates

Code that made a defensible choice AGENTS.md or the README does not describe. Closed by a sentence as often as by code — and `claims.py` follows the sentence.

- [ ] AGENTS `Every business endpoint has two faces`: the "documented REST API" is now held —
  every mutation declares its body, every JSON face its model, and the API lane validates each
  answer against its schema (`tests/e2e/drivers/conformance.py`) — with two edges left: the 51
  `/{org_handle}` operations get their path parameter only from `export_openapi.py`'s patch, and
  the generated client sends no `Accept: application/json` (`smoke.py` adds it by hand). → the
  parameter declared in the app, and a client that asks for JSON.
  [export_openapi.py](scripts/export_openapi.py), [smoke.py:54](scripts/smoke.py#L54)
- [ ] AGENTS `Integration is declarative` (`integration-is-declarative`): the activity-feed filters
  of the org dashboard and the profile hard-code their `<option>`s, and not the same ones — the
  dashboard's add `organizations`, the profile's have `auth` and no `learning` — an app contributes a filter entry outside its mount, and a deleted app keeps its
  "Todos" option; a new app gets none, and nothing fails. → a contributed filter entry, collected
  like `OrgNavQuery`.
  [dashboard.html:57](apps/organizations/templates/organizations/dashboard.html#L57),
  [profile.html:97](apps/profile/templates/profile.html#L97)
- [ ] AGENTS `One clock, one key, one style` ("every primary key"): `LogLine` maps `id` alone as
  its key through `UUIDPk`, where the table's key is `(id, ts)`. → map the composite key.
  [models.py:22](apps/shared/logs/models.py#L22),
  [20260818000015_log_lines.sql:53](supabase/migrations/20260818000015_log_lines.sql#L53)
- [ ] AGENTS `Architecture` (`three-audiences`): several business GETs have no fragment face — the
  calendar router never branches on HTMX (its only `_*.html` is the dashboard tile), nor do
  `list_issues`, `org_dashboard`, `list_members` and `nav_manager`; an HTMX request gets the full
  page. → a fragment per list/view, or a named exception list the test holds.
  [router.py:171](apps/calendar/infra/router.py#L171), [router.py:61](apps/issues/infra/router.py#L61)
- [ ] AGENTS `The dashboard collects one card per app` ("GET /{org}/ → contribs.collect(OverviewQuery)"): there is no
  route at an org's root — `/acme/` redirects to `/acme`, which falls to the public `/{slug}`
  catch-all and 404s; the collection lives at `/{org}/dashboard`. → serve the org root, or say
  `/{org}/dashboard` here and in the Integration table.
  [router.py:309](apps/organizations/infra/router.py#L309)
- [ ] AGENTS `The Timeline reads the journal, the log sink and the issues` (`timeline-writes-nothing`): the app writes twice —
  `_purge` drops a partition and DELETEs from `log_lines`, the source it reads, and `_plant_purge`
  inserts into `task_queue` — while the holder test sees only `emit(`, `session.add` and imported
  DML *spelled inside the package*, so a write delegated to a shared repository is invisible.
  → tighten `test_the_timeline_writes_nothing` to the write helpers a package calls.
  [integration.py:103](apps/timeline/contract/integration.py#L103),
  [test_surfaces.py:489](tests/meta/test_surfaces.py#L489)
- [ ] AGENTS `Three sessions, and RLS by default` ("Each context's FastAPI dependencies live in its own
  `contract/current.py`"): 7 of 17 contexts have that file — calendar's `CalendarRepo`, api_keys'
  `KeyRepo`, pages' `PageRepo`/`PageNavRepo` and timeline's query params sit in their routers, and
  auth's `UsersSettings`, consumed by profile, sits in `contract/settings.py`. → move them, or name
  the exceptions. [router.py:34](apps/calendar/infra/router.py#L34),
  [settings.py:22](apps/auth/contract/settings.py#L22)
- [ ] AGENTS `Every key is a UUIDv7, every token a UUIDv4` (`entity-id-correlates`): the settings facts name their subject with a
  renameable handle — `app_settings` has no surrogate pk, so `OrgOverrideSet` and `SettingsChanged`
  carry the app (`target_app` on `SettingsChanged`), the key and an `entity_name`, with `entity_id` null and `entity_url()` returning
  `None`. → a pk on the settings rows, or state the handle-keyed exception.
  [router.py:497](apps/console/infra/router.py#L497), [live.py:178](apps/shared/settings/live.py#L178)
- [ ] README `Structure` (`structure-tree-is-real`): `features/` holds 31 `.feature` files and 25
  others — 12 `.analysis.md` and 13 `.mockup.html`, up to 32 KB, one with a `<script>` block —
  where the row says "plain text, no code". → move the analyses and mockups out, or redraw the row.
  [profile-activity.mockup.html:325](features/profile-activity.mockup.html#L325)
- [ ] README `` `.env` vs `.env.test` `` ("`static/` is gitignored"): 7 files under `static/` are
  tracked — `css/input.css` (the Tailwind *source*) and six hand-written JS modules; `.gitignore`
  names the generated leaves only. Deleting `static/` on the strength of that sentence loses
  committed code. → say which parts are generated. [.gitignore](.gitignore)
- [ ] README `` `.env` vs `.env.test` `` ("returning 401 on every authenticated request"): the
  error handler turns a 401 into `302 → /auth/login` for a page and `204 + HX-Redirect` for HTMX,
  so a browser hitting the `COOKIES_SECURE` mistake sees an endless bounce to the login page, never
  a 401 (checked on the three request shapes). → describe the symptom that is shown.
  [exceptions.py:89](apps/shared/http/exceptions.py#L89)


### hollow tests

A holder that stays green under the mutation it exists to catch. Closed by a tighter test; the waiver or the holder in `claims.py` moves with it.

- [ ] AGENTS `The database enforces isolation and authorization`: the API lane now runs every
  RLS session as `app_rls` under its caller's claims (`tests/e2e/drivers/test_api_rls.py`), so a
  missing grant fails the scenarios — revoking `SELECT` on `pages` turns all 24 pages scenarios red.
  A dropped *isolation policy* still does not: with "pages: member read" set to `using (true)`, all
  24 pass, because the routes scope by `org_id` in Python and refuse an outsider at the membership
  gate before any query — the double enforcement `python-never-reimplements-isolation` waives.
  → a scenario whose only guard is the policy (a direct read the route does not scope), or name
  the scenarios that claim isolation. [api_transaction.py](tests/e2e/drivers/api_transaction.py),
  [pages.feature:109](features/pages.feature#L109)
- [ ] 16 claimed sentences nothing proves. `UNHELD_TODAY` is the most honest backlog in the repo:
  every waived claim names what would have to be built to hold it. [claims.py:815](tests/meta/claims.py#L815)
- [ ] README `Objectives` (`demo-apps-are-disposable`): non-demo code is hard-wired to the demos,
  and two ratchets now measure it — `test_the_modules_outside_a_demo_that_import_it_are_the_named_ones`
  (four modules import one) and `test_nothing_outside_a_demo_names_it` (68 strings: the harness's
  table lists, other apps' scenarios going through `/todos`, unit tests borrowing a demo's name).
  One of them is production code: `entity_links` maps each app to its detail route by name, where
  a registered surface belongs. → register demo test surfaces and entity routes the way app
  surfaces are; unverified past the ratchets: `make ci` in a clone with todo and learning removed.
  [entity_links.py:18](apps/organizations/contract/entity_links.py#L18),
  [test_surfaces.py](tests/meta/test_surfaces.py), [cleanup.py:61](tests/e2e/cleanup.py#L61),
  [seed.py:27](scripts/seed.py#L27), [rulebooks.py:4](tests/rulebooks.py#L4)
- [ ] AGENTS `` `| None` means optional `` (`none-means-optional`): `_DEFENSIVE_READS` names each
  `or` fallback, `typing.cast` and suppression by the function reading it, but a conditional
  fallback — `x.strftime(...) if u.created_at else ""` — is invisible to it. → add `IfExp` whose
  test is the value it guards. [test_ratchets.py](tests/meta/test_ratchets.py),
  [accounts_router.py:61](apps/auth/infra/accounts_router.py#L61)
- [ ] AGENTS `Assert the settled DOM, never wait on time` (`expect-not-is-visible`): the browser mixins' assertions still read
  text and attributes once (`inner_text()`, `get_attribute()`, `.all()`) — 50 sites, frozen per file
  by `test_the_snapshot_reads_in_assertions_are_the_named_ones`; `count()` is gone. → `expect(...)`
  for each, lowering `_SNAPSHOT_READS_IN_ASSERTIONS`. [test_ratchets.py](tests/meta/test_ratchets.py)


### design and finish

Neither broken nor misdescribed: a type that could be tighter, a boundary the linter cannot see, a rule sitting in the wrong layer, markup and styling debts.

- [ ] Five `SECURITY DEFINER` functions read before or outside an identity — `api_key_principal`,
  `second_factor_enrolled`, `get_invitation_by_token`, `public_pages`, `public_nav_items`.
  `_FUNCTION_GRANTS` counts them; nothing says why each exists or stops the list growing quietly,
  as `_ISOLATION_HELPERS` does for policy helpers. → a named list with a reason per entry.
  [test_db_privileges.py:51](tests/test_db_privileges.py#L51)
- [ ] The avatar route asks the `profiles` policy who may see it, then downloads the blob through
  `admin_storage`: `storage.objects` has no co-member policy, so the decision is the row's, the
  bytes the admin's. → a storage read policy, once avatars leave `org-files` (see bugs).
  [router.py:685](apps/profile/infra/router.py#L685)
- [ ] Sign-in forwards the visitor's address as `Sb-Forwarded-For`, but nothing checked that the
  stack's GoTrue keys its limit on it — the setting that enables it is not named in
  `docs/production.md`. → one test on the test stack: N sign-ins from two forwarded addresses, a
  429 on one only. [supabase.py:19](apps/shared/persistence/supabase.py#L19)
- [ ] AGENTS `Every business endpoint has two faces`: a dozen routes are not RESTful and each
  costs the schema an operation and the client a name. Three PATCHes on the org (`/{org_handle}`,
  `/handle`, `/timezone`) where one `PATCH /{org_handle}` with a `Partial` body would do; a verb
  in the URL — `POST /profile/delete` (an alias of `DELETE /profile`),
  `POST /profile/passkeys/{id}/delete`, `POST /auth/impersonate/stop`,
  `POST /console/accounts/{id}/disable|enable|delete`, `POST /{org_handle}/pages/{slug}/visibility`
  (already accepted by `PATCH /{slug}`); and the calendar's `POST /{event_id}` alias of `PATCH`,
  which is what prints "Duplicate Operation ID" at every schema export. The POST aliases date
  from forms without JS, and the base assumes HTMX everywhere (`hx-delete` on a todo). → one
  route per resource and verb; `_JSON_ONLY` in `tests/meta/test_routes.py` shrinks with them.
  [test_routes.py:35](tests/meta/test_routes.py#L35), [router.py:370](apps/calendar/infra/router.py#L370)
- [ ] AGENTS `Demo apps are disposable, the others loosely coupled`: the only inter-app surfaces are meant to be contracts and the bus,
  yet a test imports another app's infra — allowed on purpose by `allowed_importers =
  ["apps.*.tests.**"]`. → tests of one app reach another through its contract only.
  [test_share_token_rls.py:20](apps/files/tests/test_share_token_rls.py#L20)
- [ ] AGENTS `Demo apps are disposable, the others loosely coupled` (`boundaries-are-hard`): "domain code never imports
  infrastructure" is checked as "never imports a package named `infra`": `auth/domain/service.py`
  imports `httpx`, `supabase_auth` and `get_user_supabase` and calls GoTrue, and
  `console/domain/admins.py` reaches `auth.infra.user_repository` through a contract re-export,
  which `allow_indirect_imports` lets through. → move the I/O to infra, forbid the libraries.
  [service.py:10](apps/auth/domain/service.py#L10), [admins.py:8](apps/console/domain/admins.py#L8),
  [pyproject.toml:271](pyproject.toml#L271)
- [ ] AGENTS `Demo apps are disposable, the others loosely coupled`: templates are an inter-app surface import-linter cannot see — six
  auth templates and shared's `errors/error.html` extend public's `base_public.html`, timeline
  includes `console/_settings.html`. Without public, every error page raises `TemplateNotFound`.
  → shared layouts in `apps/shared/templates/`, or a checked template boundary.
  [login.html:1](apps/auth/templates/login.html#L1),
  [index.html:187](apps/timeline/templates/timeline/index.html#L187)
- [ ] AGENTS `One clock, one key, one style` (`one-component-system`): `input.css` defines 35
  classes outside `@layer components` in plain CSS with raw px — the `.cm-toolbar*`, `.heatmap*`,
  flip-card and `.strip-*`/`.task-*` vocabularies, and `paper` — which inverts the cascade: `paper border-2` computes 1px where `list-panel
  border-2` computes 2px, `task-bar w-56` 72px where `strip-name w-56` is 192px (measured in
  Chromium). The set is frozen by `test_the_classes_outside_the_component_layer_are_the_named_ones`
  and may only shrink; its regex also counts a comment line, which is how `list-panel` is listed.
  → into the component layer, on Tailwind values.
  [input.css:497](static/css/input.css#L497), [test_ratchets.py:1019](tests/meta/test_ratchets.py#L1019)
- [ ] AGENTS `One clock, one key, one style` ("markup is semantic and accessible"): the file
  input (`opacity-0`, its visible label a `pointer-events-none` span), the share URL and the todo
  rename input have no accessible name; the todo edit and delete buttons stay `opacity-0` on
  keyboard focus. → labels, and `focus-visible:opacity-100`.
  [files.html:26](apps/files/templates/files/files.html#L26),
  [_share_result.html:2](apps/files/templates/files/_share_result.html#L2),
  [_list_fragment.html:23](apps/todo/templates/todo/_list_fragment.html#L23)
- [ ] AGENTS `Invariants are types, not checks`: an enum-typed column binds on assignment and in
  signatures only — `Membership(..., role="boss")` passes `ty`, since `DeclarativeBase.__init__`
  takes `**kwargs: Any`, and rows are built that way (`OrgInvitation(...)`). Same for every
  StrEnum column. → typed constructors, or a ty-visible `__init__` on the base.
  [models.py:33](apps/organizations/domain/models.py#L33),
  [repository.py:142](apps/organizations/infra/repository.py#L142)
- [ ] AGENTS `Invariants are types, not checks`: `get_invitation_by_token` returns a bare `dict`,
  and the invitation router compares `status` to string literals — `== "revokd"` passes `ty` and a
  revoked invitation reads as valid. → return a typed read model, compare `InvitationStatus`.
  [repository.py:183](apps/organizations/infra/repository.py#L183),
  [invitation_router.py:64](apps/organizations/infra/invitation_router.py#L64)
- [ ] AGENTS `Invariants are types, not checks`: the Timeline grain is a runtime tuple checked
  once, then `grain: str` below — `bucket_key(now, "yeer")` silently buckets by day, `_axis_keys`
  raises `KeyError`. → a `Literal`. [router.py:43](apps/timeline/infra/router.py#L43),
  [repository.py:50](apps/timeline/infra/repository.py#L50)
- [ ] AGENTS `Invariants are types, not checks`: an org's time zone and a handle are `str`,
  validated in the routers only — `set_timezone(org, "Mars/Olympus_Mons")` passes `ty`, then every
  calendar page raises `ZoneInfoNotFoundError`. → a `ZoneInfo` / handle value object at the
  repository. [repository.py:136](apps/organizations/infra/repository.py#L136),
  [router.py:53](apps/calendar/infra/router.py#L53)
- [ ] AGENTS `Invariants are types, not checks`: a `CalendarEvent` may end before it starts in
  Python — the database refuses the row (`calendar_events_ends_after_starts_check`) and the route
  answers 422, but the domain type holds two bare datetimes. A `Span` value object would carry it,
  checked at construction (no checker rejects `end <= start` by value).
  [models.py:16](apps/calendar/domain/models.py#L16), [router.py:68](apps/calendar/infra/router.py#L68),
  [20260818000013_calendar.sql:17](supabase/migrations/20260818000013_calendar.sql#L17)
- [ ] AGENTS `` `| None` means optional `` ("Not _not yet_"): `BusinessEvent.created_at` is `None`
  on the emitted event and set only on the one a consumer receives — a lifecycle in every reader's
  type, compensated again by `if record.created_at else None` on a `not null` column. → a separate
  delivered type, or the stamp at construction. [types.py:137](apps/shared/events/types.py#L137)
- [ ] AGENTS `Architecture` (`routers-own-http`): business rules sit in routers — todo's
  `creation_enabled` and per-org quota (todo has no domain service), `max_owned_orgs_per_user`,
  calendar's "end after start" and its multi-day span computation. → move them to `domain/`.
  [router.py:88](apps/todo/infra/router.py#L88),
  [router.py:178](apps/organizations/infra/router.py#L178),
  [router.py:61](apps/calendar/infra/router.py#L61)
- [ ] AGENTS `A contract never exports a settings handle`: the rule only bites if request code
  never calls `get_settings(name)` itself, and profile's router reads `get_settings("users")` —
  auth's handle, by string, around `apps/auth/contract/settings.py`. Nothing states or checks it.
  → the `UsersSettings` dependency, and a ratchet on `get_settings` in handlers.
  [router.py:230](apps/profile/infra/router.py#L230)
- [ ] AGENTS `A contract never exports a settings handle` ("org overrides applied under
  `/{org_handle}`"): the full-page slice reads `get_settings("profile").view().avatar_enabled`
  server-wide, while the console accepts a per-org override of it — an org that switches avatars
  off still shows them on its pages. Unverified — to run: override `profile.avatar_enabled=false`
  for an org, `GET /{org}/` as a member, read `profile_avatar_path`. → `FullpageQuery` carries the
  org. [fullpage.py:37](apps/profile/contract/fullpage.py#L37)
- [ ] AGENTS `Import downward, event upward` (`auth-never-imports-organizations`): the contracts
  set `exclude_type_checking_imports = true`, so a `if TYPE_CHECKING: from apps.organizations…` in
  auth keeps all 23 contracts green (scratch run) — `apps/shared/integration/fullpage.py` already
  names a context that way. → drop the exclusion, or forbid the edge in both forms.
  [pyproject.toml:268](pyproject.toml#L268), [fullpage.py:41](apps/shared/integration/fullpage.py#L41)
- [ ] AGENTS `Load metrics belong to their app alone` (`metrics-owns-the-counter`): shared does name the context —
  `metrics_flush_seconds` in `TechnicalSettings`, read only by `apps/metrics`, and shipped as the
  deploy contract `METRICS_FLUSH_SECONDS`; delete the app and the setting survives. It is the only
  poll knob naming a context. → the app declares its own interval.
  [env.py:61](apps/shared/settings/env.py#L61), [.env.example:68](.env.example#L68)
- [ ] AGENTS `One set of helpers branches JSON, fragment and page` ("centralize the … branching"): four routers re-spell the
  header test by hand — timeline and metrics inline, issues and learning into a local `is_htmx`
  that shadows the helper's name — against the module's own "single source of truth for the header".
  → call `is_htmx`. [router.py:326](apps/timeline/infra/router.py#L326),
  [router.py:109](apps/issues/infra/router.py#L109), [router.py:95](apps/learning/infra/router.py#L95),
  [router.py:44](apps/metrics/infra/router.py#L44)
- [ ] AGENTS `A page's context is assembled from slices its apps own` ("declared, prefixed keys"): only the prefix is declared — the keys
  are whatever the coroutine returns, and the module's own "Current providers" table is already
  stale (`profile_avatar_path` is live and read by `base.html`, and unlisted). → declare the key
  set at registration. [fullpage.py:18](apps/shared/integration/fullpage.py#L18),
  [fullpage.py:38](apps/profile/contract/fullpage.py#L38)
- [ ] AGENTS `daisyUI components, never re-spelled utility chains` ("Icons are Phosphor"): the build copies the woff2 only, so an icon renders
  just when `input.css` carries its codepoint by hand — three used names are unmapped and render
  nothing: `ph-mask-happy` (the impersonation banner), `ph-clock-counter-clockwise`,
  `ph-arrow-bend-down-right` (checked in Chromium: `content: none`). → generate the mapping, or a
  test over the names used. [base.html:24](apps/shared/templates/base.html#L24),
  [index.html:118](apps/timeline/templates/timeline/index.html#L118)
- [ ] AGENTS `daisyUI components, never re-spelled utility chains` ("Icons are Phosphor"): the timeline draws its sort state with `▲`/`▼` and
  its filter-clear with `✕`, where `ph-caret-down` and `ph-x` are mapped and `ph-x` already serves
  that meaning in todo. → the Phosphor icons.
  [index.html:151](apps/timeline/templates/timeline/index.html#L151),
  [_combobox.html:45](apps/timeline/templates/timeline/_combobox.html#L45)
- [ ] AGENTS `daisyUI components, never re-spelled utility chains` ("real landmarks"): `invitations/accept.html` is its own document and its
  body is `div`/`h1`/`p` — no `main`, no header, no skip link, where the six other root templates
  carry one. → a landmark, or extend the public shell.
  [accept.html:1](apps/organizations/templates/invitations/accept.html#L1)
- [ ] AGENTS `daisyUI components, never re-spelled utility chains` ("labelled controls, visible focus rings"): the timeline filter's clear
  affordance is a `role="button"` span nested inside the pill button, and its options are plain
  divs — no `tabindex`, no key handler, absent from the tab order (measured), so a keyboard user
  can open the popover and neither choose nor clear. → real buttons and a listbox.
  [_combobox.html:42](apps/timeline/templates/timeline/_combobox.html#L42)
- [ ] "Foundation apps — auth, organizations, console — are what the others are built on: they
  have no on/off switch and are not deleted; only feature apps can be." From AGENTS
  `Demo apps are disposable, the others loosely coupled` ("can be added, disabled, or deleted without touching the others"): every
  app imports `console.contract`, 14 import `auth.contract`, 10 `organizations.contract`, and
  seven apps declare no `feature_switch()`.
  [main.py](apps/main.py)
- [ ] "The front end has one small JS build — the CodeMirror editor bundled by esbuild, next to the
  Tailwind CSS build — and no frontend project." From AGENTS `Every business endpoint has two
  faces` ("no JS build step"): `npm run build:editor` bundles `static/js/codemirror-editor.js`,
  gitignored and run by `make install`. [package.json](package.json), [Makefile:18](Makefile#L18)
- [ ] "A mutation outside Postgres — a GoTrue call, a Storage object — cannot join the fact's
  transaction: it runs first, and its fact commits after it, or is lost with a later failure." From
  AGENTS `Business events are facts, not sagas` ("the fact commits iff the mutation does, with no
  exception"): `add_admin` grants through GoTrue then emits, `account_delete` disables in GoTrue
  then commits `UserDeleted`, `delete_file` removes the object before the commit.
  [router.py:288](apps/console/infra/router.py#L288)
- [ ] "`spread` handlers are per-instance and best-effort: one that raises is logged and not
  retried, and the cursor moves past its fact." From AGENTS `Business events are facts, not sagas`
  ("Reactions are durable"): `settings.reload` and `_reload_observability` run that way on purpose.
  [listener.py:133](apps/shared/events/listener.py#L133)
- [ ] "A policy may also compare `user_id` with `auth.uid()` directly — the per-user rule, a third
  kind next to isolation and authorization, stated in the policy alone." From AGENTS `The database
  enforces isolation and authorization` ("A policy calls two kinds of helper"): `profiles: own …`,
  `memberships: self leave`, `deck_subscriptions` and `card_states: self all` rest on it, and
  `_POLICY_CALLS_SQL` reads `public` functions only, so no held test sees one removed.
  [20260818000014_learning.sql:108](supabase/migrations/20260818000014_learning.sql#L108),
  [test_db_privileges.py:92](tests/test_db_privileges.py#L92)
- [ ] "Every log line is also written to stdout synchronously, on the caller's thread — stdout is
  the durable copy, so a reader that stops reading stalls the server." From AGENTS `Facts, traces, bugs: three records` ("the rest never blocks, slows or fails the action it observes"): the
  `StreamHandler(sys.stdout)` renders and writes each call inline; 2 000 calls against an unread
  pipe did not finish in 3 s (scratch run). [chain.py:192](apps/shared/logs/chain.py#L192)
- [ ] "The API lane calls the app in-process through an ASGI transport — no socket, no HTTP
  server — so the whole request shares the scenario's rolled-back transaction; only the browser
  lane goes over the wire." From AGENTS `Tests are sincere` ("over real HTTP"): the API driver's
  `ASGISyncTransport` wraps `httpx.ASGITransport`.
  [transport.py:11](tests/e2e/drivers/transport.py#L11), [api_base.py:87](tests/e2e/drivers/api_base.py#L87)
- [ ] "Collaborative tables — todos, calendar events, files, page drafts — let every member
  write; owner-only rules are the named exceptions." From AGENTS `Multi-tenancy by default`
  ("Members read, owners write"): the `member all` policies and their migration comments ("no
  owner-only rule in v1", "drafts are collaborative").
  [20260818000012_todo.sql:25](supabase/migrations/20260818000012_todo.sql#L25),
  [20260818000010_pages.sql:47](supabase/migrations/20260818000010_pages.sql#L47)
- [ ] "The personal organization is a console switch, `organizations.auto_create_personal_org`,
  on by default; off, a new account has no org until it creates or joins one." From AGENTS
  `Multi-tenancy by default` ("Every account gets a personal organization at sign-up").
  [integration.py:142](apps/organizations/contract/integration.py#L142)
- [ ] "Three org surfaces live outside `/{org_handle}/…` because their visitor is not a member:
  share-token downloads, the featured org's public pages at the root, and invitation links." From
  AGENTS `Multi-tenancy by default` ("org data lives under `/{org_handle}/…`").
  [router.py:341](apps/files/infra/router.py#L341), [router.py:58](apps/public/infra/router.py#L58),
  [invitation_router.py:21](apps/organizations/infra/invitation_router.py#L21)
- [ ] "The bootstrap promotes whoever registers while no live admin exists — not the first row of
  `auth.users`: a first user gone before delivery, or whose task is retried behind a later one,
  leaves the role to the next." From AGENTS `The first to sign up is admin`, which already hands
  the role on when the first account is gone, not when its task is retried behind a later one: the
  handler tests the live admin count only, and `test_an_anonymized_actor_is_never_promoted` wants
  it so.
  Retry ordering unverified — to run: fail user 1's `list_server_admins` once, tick the worker
  twice under a patched clock, see who is promoted.
  [integration.py:117](apps/console/contract/integration.py#L117)
- [ ] "Time has one clock per layer: Python reads `clock.now()`, SQL stamps its own `now()` for
  what PostgREST and raw inserts write — and a pinned test clock reaches only the first." From
  AGENTS `One clock, one key, one style` ("Time comes from a single clock"): `updated_at`
  triggers, `task_queue.run_at` and the metrics purge are database-stamped, next to Python-stamped
  `created_at` and history windows. [20260818000001_foundation.sql:67](supabase/migrations/20260818000001_foundation.sql#L67),
  [router.py:72](apps/tasks/infra/router.py#L72)
- [ ] "Every table with an entity of its own is keyed by a UUIDv7 `id`; link, settings and counter
  tables keep their natural composite keys." From AGENTS `One clock, one key, one style`
  ("every primary key is a time-ordered UUIDv7"): `app_settings`, `org_app_settings`,
  `memberships`, `consumed_events`, `rate_limit_counters`. `log_lines` is keyed on its uuidv7 plus
  the partition column, which Postgres requires of any unique key on a partitioned table.
  [20260818000005_settings.sql:14](supabase/migrations/20260818000005_settings.sql#L14),
  [20260818000006_queue.sql:59](supabase/migrations/20260818000006_queue.sql#L59)
- [ ] "Where the org comes from the URL, a handler takes the settings dependency; where it comes
  from data — a share token, a stored row — it calls `get_settings(name).for_org(session, org_id)`;
  with no org at all, `.view()`." From AGENTS `A contract never exports a settings handle`
  ("Non-request code uses `get_settings`"): the `get_settings` docstring draws that line, and the
  share download, share-link creation and several account/timeline routes follow it.
  [live.py:318](apps/shared/settings/live.py#L318), [router.py:367](apps/files/infra/router.py#L367)
- [ ] "A third collaboration registry is pull-shaped and string-keyed: `host.fullpage_providers`,
  whose prefixed slice names cross apps through templates alone." From AGENTS `Two collaboration
  objects, two shapes` ("they are different objects — `host.events` … and `host.contribs`"):
  `register_fullpage_provider("profile", …)` yields `profile_handle`, read by the organizations
  dashboard template. The `Page composition` section states the registry, not its place in this
  count. [fullpage.py:1](apps/shared/integration/fullpage.py#L1),
  [integration.py:27](apps/profile/contract/integration.py#L27)
- [ ] "Keying by type trades the magic string for a shared import: emitter and subscriber both
  import the module that defines the event or query type." From AGENTS `Two collaboration objects,
  two shapes` ("no magic strings and no shared imports"): `SettingsChanged` is imported by the
  console and the timeline, `console.contract.overviews` by 19 non-test modules, and organizations
  imports `auth.contract.events` to react. [integration.py:30](apps/timeline/contract/integration.py#L30)
- [ ] "The bus decouples a third time, across instances: an app subscribes to its own fact through
  `spread` to reach every other process — in the emitting one the handler is indeed a function call
  written the long way round." From AGENTS `An app may subscribe to its own business event` ("an
  app reacting to itself is legitimate exactly when it needs the second"): the console emits
  `settings.server_changed` and reloads its own handles on it, with nothing to roll back.
  [router.py:545](apps/console/infra/router.py#L545), [host.py:234](apps/shared/integration/host.py#L234)
- [ ] "A feature may import another feature's contract where the edge is one-way and no contract
  forbids it: `public` reads `pages.contract.public`, `timeline` reads `issues.contract.queries`."
  From AGENTS `Import downward, event upward` (whose two branches are a contract import *down* to
  the three foundations, or an event *up*). [router.py:7](apps/public/infra/router.py#L7),
  [repository.py:24](apps/timeline/infra/repository.py#L24)
- [ ] "Publishers reach `events` in `apps.shared.events.bus`; collectors reach `contribs` in
  `apps.shared.integration.contribs` — two singletons, in two packages." From AGENTS `Import
  downward, event upward` ("publishers/collectors reach the process-wide `bus` singleton
  (`apps.shared.events.bus`)"): that module binds `events`, not `bus`, and `contribs.collect` never
  touches it. [bus.py:151](apps/shared/events/bus.py#L151),
  [contribs.py:65](apps/shared/integration/contribs.py#L65)
- [ ] "`request.finished` is a `warning` on a refusal we made as well as on a dead link of ours —
  every 4xx but 404." From AGENTS `Nothing escapes the log chain` ("`warning` on a dead link of ours, `info`
  otherwise"): `_refused_deliberately` promotes the level, and the middleware's own docstring says
  both halves. [request.py:293](apps/shared/logs/request.py#L293)
- [ ] "A resolved issue regresses on any version that is not the one it was resolved in — git SHAs
  have no ordering, so 'different' is the honest test." From AGENTS `A bug is an issue with a lifecycle` ("regresses on a later version"): an occurrence from an older release during a rolling
  deploy or a rollback reopens the issue and alerts.
  [service.py:60](apps/issues/domain/service.py#L60)
- [ ] "An authentication refusal is a `warning`, not the `info` an ordinary refusal earns: it is a
  signal about a caller, and a run of them is what brute force looks like." From AGENTS `A broken dependency is a bug, a refusal is not` ("an ordinary outcome at `info`"), which `What earns a line` contradicts by
  calling a refused attempt a `warning`: login, mfa, passkey, oauth and register failures all warn,
  and the threshold test's `info` allowlist holds none of them.
  [router.py:270](apps/auth/infra/router.py#L270),
  [test_log_thresholds.py:102](tests/meta/test_log_thresholds.py#L102)
- [ ] "A client raising something of its own is breakage only when the call's outcome is unknown:
  a response the SDK cannot parse *after* the server applied it is an `info`, not an issue." From
  AGENTS `A broken dependency is a bug, a refusal is not` ("a client raising something of its own — which is an issue"):
  `set_server_admin` treats a pydantic `ValidationError` that way, and says why.
  [user_repository.py:70](apps/auth/infra/user_repository.py#L70)
- [ ] "Two of the five lifespan loops stay off the verdict on purpose — the log drain and the
  capture drain are the machinery the seam runs on, so an `exception` from either would re-enter
  the queue it just failed to drain; both warn on every failed tick, with no transition and no
  issue." From AGENTS `A failure that repeats is one bug` ("The five lifespan workers … They tick
  once a second, so the level follows the transition"): `tests/meta/test_loop_verdicts.py` states
  the exclusion, AGENTS.md counts five. [sink.py:290](apps/shared/logs/sink.py#L290),
  [capture.py:211](apps/shared/logs/capture.py#L211)
- [ ] "OAuth and passkeys ship switched off — their settings default to `false`, so a fresh install
  offers email/password and TOTP, and the console is where the rest is turned on." From AGENTS
  `A GET never delivers a session` (which lists the four methods flat and calls only the profile pair
  settings-gated): at the declared defaults the provider and passkey routes answer 404 and the
  login page shows neither. [integration.py:96](apps/auth/contract/integration.py#L96)
- [ ] "Process-wide page context — the theme, the theme list, the log levels — is installed as a
  Jinja global at mount, not as a slice: a per-request route argument is a poor carrier for a
  setting no route chooses." From AGENTS `A page's context is assembled from slices its apps own` ("merges them — called explicitly,
  never injected silently"): `base.html` renders `app_theme()` on every page, from a global no
  route mentions. [integration.py:74](apps/console/contract/integration.py#L74),
  [templates.py:40](apps/shared/http/templates.py#L40)
- [ ] "A bearer credential is not a uuid: the API key is `secrets.token_hex(20)` behind its prefix
  and the PKCE verifier `secrets.token_urlsafe(64)` — a uuid4 carries 122 random bits, the wrong
  shape for a secret. The uuid4 exception covers the two table-stored tokens, invitations and file
  shares." From AGENTS `Every key is a UUIDv7, every token a UUIDv4` ("Security tokens are the deliberate exception — they stay random
  **UUIDv4**"). [service.py:22](apps/api_keys/domain/service.py#L22),
  [service.py:122](apps/auth/domain/service.py#L122)
- [ ] "No suite reruns, and none can: the rerun plugin is deliberately absent, because a rerun
  hides exactly what `make flakehunt` measures." From AGENTS `Assert the settled DOM, never wait on time` ("Reruns are opt-in
  and justified per named suite"): there is no opt-in mechanism and no named suite, and the
  Makefile, `flakehunt.sh` and the ratchet's docstring all say why.
  [Makefile:218](Makefile#L218), [test_ratchets.py:1035](tests/meta/test_ratchets.py#L1035)
- [ ] "Knowing several contexts is ordinary — through their contracts, in the direction `Import
  downward, event upward` allows; `main.py` is the only module that knows *every* context and the
  only one that mounts them." From README `Structure` ("the only place allowed to know several
  contexts at once: `main.py`"): 19 non-test modules import two or more foreign contexts, up to
  three. [router.py:5](apps/public/infra/router.py#L5),
  [integration.py:16](apps/api_keys/contract/integration.py#L16)
- [ ] "A checkout runs two local stacks — the dev one on 543xx, whose endpoints this table lists,
  and its own test stack on the ports its `.env.test` names, with one mailbox per stack and no
  Studio at all." From README `Local Supabase endpoints` (which lists one mail catcher and one
  Studio): `make test`, `make doctor` and `promote-admin` all default to `ENV_FILE=.env.test`, and
  the e2e mailbox reads `MAILPIT_URL` (54424 today) — both catchers are live and hold different
  mail, 108 messages against 69.
  [mailbox.py:30](tests/e2e/drivers/mailbox.py#L30), [test_stack.py:19](scripts/test_stack.py#L19)
- [ ] "`pyright` type-checks in `standard` mode alongside `ty`, and `make lint` fails on its
  errors." From README `` `.env` vs `.env.test` `` ("the `[tool.pyright]` block, which leaves type
  checking to `ty`"): `pyproject.toml` says "Alongside `ty`, not instead" and the run reports a
  `reportArgumentType` error the README implies cannot exist; `.vscode/settings.json` repeats the
  README's wording. [pyproject.toml:120](pyproject.toml#L120), [Makefile:120](Makefile#L120)
- [ ] "One `org-files` bucket serves the whole deployment; an org is isolated by the first path
  segment, which the storage policies cast to its id — and avatars share it under `avatars/`."
  From README `Demo apps` ("`files/` … org-scoped buckets"): the migration creates the single
  bucket and `storage_path` builds `{org_id}/{file_id}_{filename}`.
  [20260818000011_files.sql:85](supabase/migrations/20260818000011_files.sql#L85),
  [storage.py:27](apps/files/infra/storage.py#L27)


## features

- [ ] The console should show a dedicated growth activity report — the sign-ups chart exists on the
  overview, the screen does not.
- [ ] `/console/organizations` should list organisations and give metrics.
- [ ] AARRR metrics
- [ ] Product tour
- [ ] Role-Based Access Control, Named permissions — `owner`/`member` is binary.
- [ ] Awareness, `@citation`, notification
- [ ] ApexCharts heatmap → https://apexcharts.com/javascript-chart-demos/heatmap-charts/basic/
- [ ] accept text/markdown pour apps/pages


## technical opportunities

- [ ] speedup `make finalize`
- [ ] The correlation triplet crosses the timeline↔issues contract as loose kwargs.
  `_issue_kwargs` starts from `_event_kwargs` then `del`s two keys to land on the seven named
  parameters of `search_issue_occurrences`. `TimelineFilter` already *is* that object on the caller
  side: it is flattened, then re-narrowed per source. Adding a filter costs the dataclass,
  `_event_kwargs`, three `del` lists and every contract signature; a `del` on a key the other query
  no longer has is a runtime `KeyError`, not a type error. → a frozen `OccurrenceFilter` in the
  contract, built explicitly by the timeline.
  [repository.py:283](apps/timeline/infra/repository.py#L283),
  [queries.py:32](apps/issues/contract/queries.py#L32)
- [ ] `issue_occurrences` correlates inside the JSONB with no index to serve it — filters on
  `context['org_id'].astext` (same for user_id, request_id) and an `ilike` on
  `cast(context as text)`, against a single `(issue_id, id desc)` index. Every correlated Timeline
  read scans sequentially, and only retention purging bounds the volume. The columns exist on
  `business_events` — issues chose JSONB. → promote the three correlation keys to real columns,
  migration + backfill. [20260818000007_issues.sql:49](supabase/migrations/20260818000007_issues.sql#L49)
- [ ] `AppManifest` covers 6 apps out of 16 — the other ten re-spell the mount ceremony by hand.
  That is exactly the `integration-is-declarative` claim that stays unproven.
  [host.py:80](apps/shared/integration/host.py#L80)
- [ ] Fewer `str`, more types — starting with settings: `SettingsView.__getattr__` returns `Any`,
  so `TodoSettings`, `PublicSettings` and the rest are the same untyped object under different
  names. Hence the three `# type: ignore[assignment]` on `featured_org_handle`, the only ones in
  application code. This is the hole in "invariants are types, not checks".
  [live.py:173](apps/shared/settings/live.py#L173)
- [ ] Route the API-key path through the app's own Storage credentials, keeping the org pin as the
  single source of the path. An API-key principal carries `access_token = ""`, so
  `user_storage_client()` has nothing to present. The precedent already exists: avatar upload goes
  through `admin_storage()` for an authenticated user.
- [ ] Hunt the N+1s — the instrumentation now exists (`db.heavy_request` writes a line as soon as a
  request crosses its query-count or SQL-time threshold); what is left is opening what it reports.
- [ ] `_ENTITY_ROUTES` in `apps/organizations` is a coupling — an app is named there to earn a deep
  link. [entity_links.py:18](apps/organizations/contract/entity_links.py#L18)
- [ ] Should `jinja_globals` live in the host?
- [ ] Split the SQLAlchemy models (`domain`) from the Pydantic models (`contract`), in every app.
- [ ] 48 tuning knobs are still literals — retention windows, poll and purge intervals, retry
  budgets, batch sizes, page lengths, deadlines, caps. AGENTS `No magic number` names them as
  settings; `_KNOBS_AWAITING_PROMOTION` enumerates them and only shrinks, so the count is the
  distance. [test_ratchets.py](tests/meta/test_ratchets.py)
- [ ] Dataclass or Pydantic?
- [ ] Multi-process? One Hypercorn today, and five background loops per process.
- [ ] Command Query Responsibility Segregation?
- [ ] Use SQLAlchemy more the way JPA is used
- [ ] COW, soft deletion, soft update
- [ ] Better styleguide, inspired by my apps and the daisyUI templates.
- [ ] Documents → `pg_jsonschema` (see extensions)
- [ ] Messaging → `pgmq` (see extensions)
- [ ] Cache
- [ ] Email — the `Mailer` port exists; deliverability is a production-readiness item.
- [ ] GDPR export
- [ ] CLI
- [ ] MCP server?
- [ ] i18n — every UI string is hardcoded English. Jinja2 route: Babel/gettext extraction,
  per-request locale (cookie or `Accept-Language`), catalogues per context. Expensive to retrofit.
  → consciously deferred (2026-07-05).
- [ ] Billing — the one link entirely missing from the grammar of a credible SaaS kit
  (auth + teams + billing + email + jobs). Shape: a `billing/` bounded context, standard mount,
  subscription per org managed by the owner, Stripe Checkout + customer portal (no card UI to
  build), a webhook feeding typed events (`SubscriptionChanged`) onto the bus, plan gates readable
  by other apps the way declared settings are, an MRR stat on the console. Domain kept
  vendor-agnostic behind a port, Stripe adapter first. → out of scope (2026-07-05).
  https://github.com/t3dotgg/stripe-recommendations
- [ ] https://12factor.net
- [ ] https://w.pitula.me/fintech-engineering-handbook/
- [ ] https://datacater.io/blog/2021-09-02/postgresql-cdc-complete-guide.html


### production readiness

Going from "it runs on my machine" to "shippable and operable". Already in place, not to be
rebuilt — observability, `health/` probes, cross-instance rate limiting, RLS, security
headers, `Sec-Fetch-Site` CSRF, backup docs. The gap is not the runtime, it is the path to
production and its operation. Full runbook in [production.md](docs/production.md).

- [ ] The preflight's `len(SUPABASE_SECRET_KEY) < 40` threshold is a heuristic that refuses boot
  with no way out. Measured: a real `sb_secret_…` key is 41 characters — a one-character margin.
  Legacy `service_role` keys are very long JWTs and sail through. A false positive locks production
  out. → validate a prefix rather than a length, or downgrade to a warning.
  [preflight.py](apps/shared/settings/preflight.py)
- [ ] Deployment CI/CD — a pipeline gated on `make ci`, an image tagged by version (`apps/issues`
  already tracks regression by version), migration, rollback.
- [ ] Alerting — the issue half is done: `issues.alerting_enabled` + `alert_email` send mail on an
  issue opening or regressing, as a durable consumer — a parked task and a readiness probe that
  falls over open one, so they mail too. What remains is load thresholds (`/metrics` exists), an
  alert per park rather than the first per fingerprint, and a path that does not ride the SMTP it
  may be reporting down. Prometheus scrape + Grafana dashboard.
- [ ] Log shipping — structured JSON out to an aggregator (Loki, CloudWatch…). Overlaps Supabase
  Log Drains.
- [ ] Image scan + CI secret scan — Trivy on the image; talisman, already in pre-commit, promoted
  to a blocking CI gate.
- [ ] Email deliverability — a real provider behind the `Mailer` port, plus SPF/DKIM/DMARC.
- [ ] Uptime monitoring — an external synthetic check on readiness.
- [ ] Explicit timeouts on every outbound call (Supabase, SMTP) — the queue already has its backoff.
- [ ] Harden the CSP — tighten `script-src` / `connect-src` now that the front end is stable.
- [ ] Automated restore drill, and written RTO/RPO targets — the drill is documented, not
  continuously tested.
- [ ] Runbooks — deploy, incident, on-call; SLO and error-budget doc.
- [~] Horizontal scaling guide — the `TaskWorker` is already multi-instance safe; document
  pooler/worker sizing and a load test beyond `perf-smoke`.
- [ ] production.md routes both database URLs through Supavisor in transaction mode, which supports
  neither `LISTEN` — the event listener's wake-up would fall to polling, silently — nor the
  prepared statements asyncpg caches. → session mode or a direct connection, and say which.
  [listener.py:243](apps/shared/events/listener.py#L243), [production.md](docs/production.md)


## possible Supabase integrations

Every entry of supabase.com/features, name and wording as the page carries them, reread against the
tree 2026-09-17. `[x]` is in use, `[~]` partly. `[?]` is for a seam this tree really has and the
feature really answers, with the question still open, and the line says when a paid plan gates it.
`[ ]` is everything else — no seam, or a decision already taken, which the line then names. An
entry that is a Postgres extension, or is built on one, defers to the next list, which is where the
most is left to gain.

- [ ] AI Integrations - Enhance applications with OpenAI and Hugging Face integrations. Follows
  `vector` in the next list.
- [ ] Analytics Buckets (with Iceberg) - Large-scale analytics using Apache Iceberg format.
- [?] Auth Hooks - Customize authentication flows with serverless functions. → an access token hook
  would stamp org membership into the JWT, which most policies re-read through a SECURITY DEFINER
  helper on each query; the per-user and public-read ones have no membership to stamp. The hook is
  itself a Postgres function, and the free plan has it. Against it: a claim stale until the
  refresh, and two paths that never see a GoTrue token — queue tasks and API keys build their own
  claims, so a policy reading the stamp would deny both.
- [x] Authorization via Row Level Security - Control the data each user can access with Postgres
  Policies. The source of truth for isolation, in versioned SQL — `org_file_share_tokens`
  included, the anonymous download reading it with an admin session.
- [ ] Auto-generated GraphQL API via pg_graphql - Fast GraphQL APIs using our custom Postgres
  GraphQL extension. See extensions.
- [~] Auto-generated REST API via PostgREST - RESTful APIs auto-generated from your database. No call
  site of ours: data goes through asyncpg + SQLAlchemy, Storage through `storage3`, and business
  routes are hand-written, each with two faces. It is served all the same, to anyone holding the
  publishable key, and `anon` reaches nothing through it: the foundation migration revokes
  Supabase's default privileges on `public` before the first object exists, and
  `test_db_privileges.py` holds the allow-list.
- [ ] Automatic Embeddings - Automated embedding generation using triggers and queues. Built on
  `vector`, `pgmq`, `pg_net` and `pg_cron`, all four in the next list.
- [?] Branching - Test schema changes without touching production. → `make worktree` already gives
  each checkout its own schema, bucket and test stack, locally. Branching is the same idea on the
  remote, which is what the deployment pipeline under production readiness would need. Pro,
  billed per branch-hour.
- [x] CLI - Use our CLI to develop your project locally and deploy. Versioned SQL migrations, local
  stack, `make db-reset`, one test stack per checkout — and nothing else of `config.toml` ever
  reaches a remote: there is no `supabase config push`.
- [?] Captcha protection - Add Captcha to your sign-in, sign-up, and password reset forms. → those
  three are rate-limited per IP by a limiter that fails open by design, and it is the only per-caller
  limit there is: sign-in and sign-up forward the visitor's address to GoTrue as
  `Sb-Forwarded-For`, but the password reset does not, so on that form GoTrue's own per-IP counter
  sees one caller per instance.
- [ ] Client Library - Flutter - Integrate Supabase into your Flutter applications effortlessly.
- [ ] Client Library - JavaScript - Easily integrate Supabase with your JavaScript applications.
  The browser never holds a token: the JWT stays in an HTTPOnly cookie, so nothing there could
  authenticate a call.
- [x] Client Library - Python - Integrate Supabase easily into your Python applications.
  `supabase-py` for auth and its `storage3` package for Storage, the JWT in an HTTPOnly cookie.
- [ ] Client Library - Swift - Effortlessly connect your Swift applications to Supabase.
- [?] Content Delivery Network - Cache large files using the Supabase CDN. → downloads redirect to
  a Storage origin already, but both handlers mint a fresh signed URL per request, and a new token
  is a new cache key — the cache never warms. Every plan has the basic CDN; caching signed URLs is
  the Smart CDN, from Pro. Reusing a URL is the work, and its cost: a cached entry outlives the
  token that minted it, so an expired share or a removed member keeps access until the object goes.
- [ ] Cron - Schedule recurring Jobs in Postgres. Recurring work re-enqueues itself from Python;
  Supabase Cron is `pg_cron`, so the trade is argued in the next list.
- [?] Custom Identity Providers - Connect any OAuth2 or OIDC identity provider to Supabase Auth.
  → the PKCE round-trip is provider-agnostic and already carries Google and GitHub. Adding one
  means extending the `OAUTH_PROVIDERS` constant, declaring its switch, and teaching the template a
  third icon. Three custom providers on the free plan, unlimited from Pro.
- [?] Custom domains - White-label the Supabase APIs for a branded experience. → during an OAuth
  sign-in the browser is sent to the project's own Supabase domain. The tree needs nothing to
  change it — `SUPABASE_API_URL` is one value, and Storage follows it — so the whole cost is the
  add-on, from Pro.
- [ ] Database Webhooks - Trigger external payloads on database events. Built on `pg_net`, in the
  next list; the in-tree counterpart is the event listener's fan-out off `business_events`.
- [~] Database backups - Projects are backed up daily with Point in Time recovery options. The choice
  is made — [backups.md](docs/backups.md) buys the platform's, from Pro, with PITR as a paid add-on —
  and the tree carries the other half: a restore drill, and `make backup-storage` for the bytes no
  SQL dump holds. Nothing runs either until a hosted project exists.
- [ ] Declarative Schemas - Simplify database management with declarative schema files. Migrations
  are plain SQL written in dependency order, by choice: the README's stack table picks the CLI's
  versioned migrations for full control, and `log_lines` creates its partitions from dynamic SQL,
  which no schema file describes.
- [?] Dedicated Poolers - Co-located connection pooler for maximum performance. → the same question
  as Supavisor below, answered on a paid plan: Supabase points a backend that can reach it at the
  dedicated pooler rather than the shared one.
- [ ] Deno Edge Functions - Globally distributed TypeScript functions to execute custom business
  logic. Nothing here needs code outside the request path or the queue, and a second runtime is a
  second place for business logic to live.
- [~] Email Templates - Customizable email templates for all authentication flows. `recovery`,
  `email_change` and `confirmation` point at the app's own SSR routes — on local stacks only. They
  live in `config.toml`, which nothing pushes, so a hosted project mails GoTrue's defaults and the
  reset route never receives its `token_hash`.
- [x] Email login - Build email logins for your application or website. Forgot/reset flow, and the
  mailed-confirmation path with its resend on a blocked sign-in — built, but `enable_confirmations`
  is off in `config.toml`, so every local stack auto-confirms and the scenario builds its
  unconfirmed user through the admin API.
- [x] File storage - Supabase Storage makes it simple to store and serve files. One bucket per
  deployment, isolated per org by RLS on the first path segment, and immutable share tokens for
  anonymous download. Avatars share the bucket under `avatars/`, a segment the policies cast to a
  uuid: once one exists, any user-scoped listing of the bucket fails. The app never lists that way.
- [ ] Foreign Data Wrappers - Query external data sources as Postgres tables. See extensions.
- [ ] Foreign Key Selector - Easily manage foreign key relationships between tables. The schema is
  authored in SQL migrations, never in Studio.
- [?] Image transformations - Optimize and resize images on-the-fly directly from your Supabase
  storage buckets. → an avatar is downloaded whole through the app and streamed back at upload
  size, cached five minutes per browser. Locally it takes a `[storage.image_transformation]` block
  in `config.toml` and `imgproxy` out of the test stack's exclusions; hosted, it is Pro and
  metered.
- [x] JWT Signing Keys - Asymmetric key management for enhanced JWT security. The app verifies
  RS256/ES256 against the project JWKS, so no shared signing secret ever reaches the process.
- [?] Log Drains - Export logs to Datadog, Grafana, Sentry, S3, and more — now available on Pro.
  → the app writes its own shared `log_lines`; Postgres, GoTrue and Storage keep theirs on the
  platform. The app sees a GoTrue or Storage failure from its side — an error line and an issue —
  but never why, and a Postgres outage takes the Timeline down with it. Answers the "log shipping"
  readiness item from the other side.
- [?] Logs & Analytics - Gain insights into your application’s performance and usage. → the same
  seam as Log Drains: the console Timeline is app-side by construction.
- [ ] MCP Server - Connect your AI tools using the official Supabase Model Context Protocol (MCP)
  server. Not in `.mcp.json`, and not what the "MCP server?" line above asks for, which is one of
  our own.
- [?] Management API - Manage your projects programmatically. → its logs endpoint returns every
  service's lines for the last day, on the free plan's retention — the Timeline could read
  GoTrue's and Storage's side of a failure without a drain.
- [x] Multi-Factor Authentication (MFA) - Add an extra layer of security to your application with
  MFA. GoTrue TOTP factors, enrolment on the profile and step-up at sign-in, behind a console switch.
- [?] Network restrictions - Restrict IP ranges that can connect to your database. → absent from
  production.md, and scriptable through the CLI. It guards the two database URLs, whose passwords
  can reach Postgres from anywhere today; it does nothing for a leaked secret key, which reaches the
  project through its HTTP APIs.
- [?] OAuth2.1 Server - Turn your project into an OAuth 2.1 identity provider. → `api_keys` already
  issues per-org `lbk_…` bearer tokens; an OAuth server is what the "MCP server?" line above needs
  to be more than a personal token. Free plan.
- [ ] OrioleDB - New Postgres storage engine that's better than Heap storage.
- [?] Passwordless login via Magic Links - Build passwordless logins via magic links for your
  application or website. → most of it exists: impersonation already confirms a `magiclink` token,
  and `/auth/confirm` takes any token type and records the sign-in. Missing: the `magic_link`
  template, a sign-in form and a console switch.
- [ ] Persistent Storage - Mount S3 buckets for 97% faster Edge Function cold starts. Follows Deno
  Edge Functions.
- [ ] Phone logins - Provide phone logins using a third-party SMS provider.
- [ ] Policy Templates - Quickly implement common security policies. Policies are written in
  migrations, never in Studio — the org-isolation shape the templates offer is the one the
  SECURITY DEFINER helpers already implement.
- [ ] Postgres Extensions - Enhance your database with popular Postgres extensions. Nothing in the
  tree calls one: `gen_random_uuid()` is core on PG 17, and `uuidv7()` is pure core SQL on purpose.
  See the next list.
- [x] Postgres Roles - Managing access to your Postgres database and configuring permissions. The app
  logs in as its own role and pins `authenticated` per transaction, never from the token; admin
  work runs as `postgres`. Grants are explicit in every migration, and nothing else reaches `anon`
  or `authenticated`: the foundation migration revokes Supabase's default privileges on `public`
  before the first object exists.
- [x] Postgres database - Every project is a full Postgres database. RANGE partitions, `UNLOGGED`,
  triggers, `SECURITY DEFINER`, `FOR UPDATE SKIP LOCKED`, `LISTEN`/`NOTIFY`.
- [ ] PrivateLink - Secure private network connectivity to your Supabase database.
- [ ] Queues - Durable messages with guaranteed delivery. `apps/shared/queue.py` is this,
  hand-written; Supabase Queues is `pgmq`, argued in the next list.
- [ ] Read replicas - Isolate heavy workloads and reduce global latency. There is no read-only
  engine to point at one: the console's reads go to the primary with everything else.
- [?] Realtime - Broadcast - Send messages between connected users through websockets. →
  `live_refresh` polls every 30 s on the Timeline and the Tasks history. Both are admin screens, and
  a private channel needs a token the browser never holds, so a channel means a server-side relay
  too — plus Realtime in the test stack, which drops it.
- [ ] Realtime - Broadcast Authorization - Control access to broadcast channels in real-time.
  Follows Broadcast.
- [ ] Realtime - Broadcast Replay - Access previously sent messages in private channels. Follows
  Broadcast.
- [ ] Realtime - Broadcast from the Database - Trigger broadcast messages directly from Postgres.
  Follows Broadcast.
- [ ] Realtime - Postgres changes - Receive your database changes through websockets. The event
  listener reads the journal itself, woken by `LISTEN`/`NOTIFY` on a direct connection and by
  polling otherwise; Realtime runs unused on the dev stack and is dropped from the test stack.
- [ ] Realtime - Presence - Synchronize shared state between users through websockets. No surface
  shows who else is here; waits on Broadcast and on the "Awareness, `@citation`, notification"
  feature above.
- [ ] Realtime - Presence Authorization - Manage presence information securely in real-time.
  Follows Presence.
- [ ] Regional invocations - Execute an Edge Function in a region close to your database. Follows
  Deno Edge Functions.
- [?] Reports & Metrics - Monitor your project's health with usage insights. → `apps/metrics`
  counts, exposes `/metrics` and renders the Load screen. Connections and cache hit rate are in
  `pg_stat_database`, size in `pg_database_size()`, both on the session the Load screen already
  opens; what only Supabase has is host-side — CPU, memory, disk I/O — through a metrics endpoint
  that starts at Pro.
- [?] Resumable uploads - Upload large files using resumable uploads. → the upload is read whole
  into the process, and only then compared to `max_upload_mb`, so the setting bounds what is kept,
  not what is read. Resuming the app-to-Storage leg would not change that; a signed upload URL,
  which the browser uses directly with no JWT, would.
- [?] Role-Based Access Control (RBAC) - Define and manage user roles securely → exactly the
  "Role-Based Access Control, Named permissions" feature above: `owner`/`member` is binary, and
  most policies only ask membership, never the role. A third role lives outside RLS altogether:
  the server admin, read from `app_metadata` and checked in Python on BYPASSRLS sessions.
  Supabase's pattern stamps the role through a custom access token hook, with the two blind paths
  the Auth Hooks line names.
- [ ] S3 compatibility - Interact with Storage from tools which support the S3 protocol. Nothing
  here needs it: the backup script already holds a key with full Storage access, and the S3 keys
  would be one more secret with the same reach.
- [ ] SOC 2 Compliance - Build with confidence on a SOC 2 compliant platform. A property of the
  platform, from the Team plan, not something to integrate.
- [ ] SQL Editor - A powerful interface for writing and executing SQL queries. Studio is deep-linked
  from each app's console page (`SupabaseLink`), but at the table editor, the Auth users list or the
  Storage bucket — never the SQL editor, and `supabase/snippets/` is empty.
- [?] SSL enforcement - Enforce secure connections to your Postgres clients. → absent from
  production.md, and reachable from the deploy path through the same CLI that runs
  `supabase db push`. No production connection string here states an `sslmode`; the two that do
  are the local `tbls` configs, set to `disable`.
- [?] SSO with SAML - Enterprise single sign-on using SAML protocol. → the same seam as Custom
  Identity Providers, with an org handle already there to map a tenant's domain to its provider;
  the installed client has `sign_in_with_sso`. Pro, billed per MAU past 50.
- [?] Security & Performance Advisor - Optimize your database security and performance
  effortlessly. → its lints run against the local stack already, through Studio, and nothing here
  reads them. Every `public` table has RLS on; the `log_lines` partitions, which do not inherit
  it, are the one candidate left for an error (unverified), and the performance half proposes
  indexes for the unindexed foreign keys.
- [?] Server-side Auth - Helpers for implementing user authentication in popular server-side
  languages. → sign-in, sign-up and refresh already go through `supabase-py`, but the OAuth PKCE
  pair and the code exchange are hand-rolled over `httpx`, where the installed client has a
  `pkce` flow and `exchange_code_for_session`.
- [?] Smart Content Delivery Network - Automatically revalidate assets at the edge via the Smart
  CDN. → the Storage CDN itself from Pro, and the one that caches signed URLs — so the seam, the
  work and the revocation cost of Content Delivery Network.
- [x] Social login - Provide social logins from platforms like Apple, GitHub, and Slack. Google and
  GitHub over PKCE, each behind its own console switch.
- [ ] Supabase AI Assistant - Your intelligent companion for managing Postgres databases.
- [ ] Supabase Pipelines - Replicate Postgres data to analytical destinations.
- [?] Supavisor - A scalable connection pooler for Postgres. → production.md routes both database
  URLs through it in transaction mode, which supports neither prepared statements, which asyncpg
  caches, nor `LISTEN`, on which the event listener waits. Session mode, or a direct connection,
  is the open choice.
- [?] Terraform provider - Manage Supabase infrastructure via Terraform. → the project's settings
  live nowhere in the repo, and the provider's `supabase_settings` carries most of what this list
  touches: SSL enforcement, network restrictions, the pooler, auth hooks, captcha, OAuth secrets,
  SMTP, image transformation, the S3 protocol. Custom domains and log drains have no resource.
- [ ] Third-Party Authentication - Trust JWTs from external authentication providers. GoTrue is the
  only issuer the app trusts; OAuth2.1 Server is the direction worth having.
- [ ] User Impersonation - Experience your application as any user. The app has its own, bannered
  and recorded; Supabase's tests policies in Studio, which is not the same thing.
- [ ] Vault - Manage secrets safely in Postgres. It is `supabase_vault`, argued in the next list.
- [ ] Vector Buckets - S3-backed storage for vector embeddings with similarity search. Follows
  Vector database.
- [ ] Vector database - Store vector embeddings right next to the rest of your data. It is
  `vector`, argued in the next list.
- [ ] Visual Schema Designer - Design your Postgres database schema with an intuitive interface.
  See Foreign Key Selector.
- [ ] Web3 Authentication - Wallet-based authentication for Ethereum and Solana.


## possible extensions integrations

`pg_available_extensions` on the local stack — the half the catalogue above cannot show, and the
one where hand-written bricks double an extension the stack already offers. The stack runs
PostgreSQL 17.6: the hand-rolled `uuidv7()` stays until Supabase ships 18, where it is native — no
horizon, its registry offers 13/14/15/17 and the port is dormant. The 19 defaults are written
`default public.uuidv7()`; unqualified, the swap would be one `drop function`.

Installed:

- [ ] `pgcrypto` 1.3 — installed, called by nothing: its only uuid function is `gen_random_uuid()`,
  a v4 `pg_catalog` has carried since PG 13. No uuidv7, so no substitute for ours. → drop.
- [ ] `supabase_vault` 0.3.1 — installed, unused. Secrets live in the env file the process reads at
  boot, and no SQL needs one; Vault earns its place the day the database calls out itself — a
  `pg_net` webhook carrying a token.
- [ ] `uuid-ossp` 1.1 — installed, unused, and superseded: keys are `uuidv7()`, security tokens the
  core `gen_random_uuid()`.
- [ ] `pg_stat_statements` 1.11 — installed, unused. It sees what the hand-written SQL tally cannot —
  the heaviest statements across every session — and misses what the tally is for: which request
  ran them, the key `db.heavy_request` reports on.
  [sql_stats.py](apps/shared/persistence/sql_stats.py)

Available:

- [ ] `pg_net` 0.20.4 — available, not installed.
- [ ] `index_advisor` 0.2.0 + `hypopg` 1.4.1 — the cheapest win on the list: no coupling at all,
  installed for the length of a session, and it answers the missing `issue_occurrences` index
  (technical opportunities) directly.
- [ ] `pg_partman` 5.3.1 — would replace `roll_log_partitions`, the hand-written SQL function that
  creates `log_lines`' daily partitions and applies retention. Rolling partitions is not a design
  choice, it is maintenance.
  [20260818000015_log_lines.sql:90](supabase/migrations/20260818000015_log_lines.sql#L90)
- [ ] `pgmq` 1.5.1 — Supabase's message queue: table, visibility timeout, archive. It keeps the
  outbox semantics, since `pgmq.send` is SQL and commits with the caller's session like today's
  insert. It covers the transport half of `apps/shared/queue.py`, not the rest: the acting user
  and its RLS session, attempts and parking, recurring singletons, and the reads behind the Tasks
  screen. The bet: less code, against a brick whose every line the README can no longer explain.
  [queue.py](apps/shared/queue.py)
- [ ] `pg_cron` 1.6.4 — would replace the wake-up of purges and rollups, today a re-enqueue in
  Python. It does not replace the queue, only the scheduling: still open whether splitting the
  recurring half in two is a simplification or one more seam. [queue.py:116](apps/shared/queue.py#L116)
- [ ] `vector` 0.8.2 — semantic search. Pages already search their title and body with Postgres
  FTS, no extension; `vector` would add meaning, not words.
- [ ] `pg_jsonschema` 0.3.3 — would validate the JSONB columns in the database (fact payloads,
  occurrence context), where only Python constrains the shape today.
- [ ] `pg_graphql` 1.6.1 — a second generated face for the API. To weigh against the two-faces
  doctrine, which already makes every route readable as JSON.
- [ ] `postgres_fdw` 1.1 / `wrappers` 0.6.2 — read an external source as a Postgres table.
- [ ] `http` 1.6 — outbound calls from the database. Overlaps `pg_net`, the asynchronous one Supabase
  builds on.
- [ ] `pgsodium` 3.1.8 — per-column encryption at rest.
