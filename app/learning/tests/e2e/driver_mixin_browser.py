import asyncio
import contextlib
import threading
import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import tests.e2e.clock as test_clock
from app.auth.tests.admin_helpers import delete_user_if_exists, find_users
from app.organizations.tests.admin_helpers import orgs_for_user
from app.shared.config import get_settings
from tests.e2e.drivers.browser_base import BrowserBase

from . import setup

_PASSWORD = "Secret1!"


class LearningBrowserMixin(BrowserBase):
    # ── state ────────────────────────────────────────────────────────────────
    def _ensure_learn(self) -> None:
        if not hasattr(self, "_learn_ctx"):
            self._learn_ctx: dict = {}
            self._learn_page: dict = {}
            self._learn_handle: dict = {}
            self._learn_org: dict = {}
            self._learn_uid: dict = {}
            self._deck_defs: list = []
            self._learn_current: str | None = None

    _DEFAULT_DATE = "2024-09-01"

    def _today(self) -> date:
        return test_clock.today()

    def teardown_test(self) -> None:
        self._reset_learning()
        super().teardown_test()

    def _reset_learning(self) -> None:
        for ctx in getattr(self, "_learn_ctx", {}).values():
            with contextlib.suppress(Exception):
                ctx.close()
        self._learn_ctx = {}
        self._learn_page = {}
        self._learn_handle = {}
        self._learn_org = {}
        self._learn_uid = {}
        self._deck_defs = []
        self._learn_current = None

    def _seed(self, fn):
        result: dict = {}
        errors: list = []

        def target() -> None:
            async def go() -> None:
                settings = get_settings()
                url = settings.database_url_service or settings.database_url
                connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
                engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
                try:
                    async with AsyncSession(engine, expire_on_commit=False) as s:
                        result["v"] = await fn(s)
                        await s.commit()
                finally:
                    await engine.dispose()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(go())
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                loop.close()

        t = threading.Thread(target=target)
        t.start()
        t.join()
        if errors:
            raise errors[0]
        return result.get("v")

    # ── users / orgs ──────────────────────────────────────────────────────────
    def _user(self, name: str) -> str:
        self._ensure_learn()
        key = name.lower()
        self._learn_current = key
        if key not in self._learn_ctx:
            assert self._context
            email = f"{key}@example.com"
            delete_user_if_exists(email)
            ctx = self._b.new_context()
            self._setup_context(ctx, email)  # ty: ignore[unresolved-attribute]
            uid = find_users(email)[0].id
            orgs = orgs_for_user(uid)
            assert orgs, f"No org for {email}"
            org = orgs[0]
            self._learn_ctx[key] = ctx
            self._learn_page[key] = ctx.new_page()
            self._learn_handle[key] = org["handle"]
            self._learn_org[key] = uuid.UUID(org["id"])
            self._learn_uid[key] = uuid.UUID(uid)
        return key

    def _page_for(self, key: str):
        return self._learn_page[key]

    def _url(self, key: str, path: str) -> str:
        return f"{self._base_url}/{self._learn_handle[key]}/learning{path}"

    def _goto_today(self, key: str):
        page = self._page_for(key)
        page.goto(self._url(key, "/sessions"), wait_until="load")
        return page

    def _card_state(self, key: str, ext: str) -> dict:
        org_id, uid = self._learn_org[key], self._learn_uid[key]
        return self._seed(lambda s: setup.get_state(s, org_id, uid, ext))

    async def _materialize(self, org_id: uuid.UUID, session: AsyncSession) -> None:
        for pos, (name, resource, cards) in enumerate(self._deck_defs):
            await setup.create_deck(session, org_id, name, resource, pos, cards)

    # ── catalog & subscription ─────────────────────────────────────────────────
    def define_deck(self, name: str, resource: str | None, cards: list[dict]) -> None:
        self._ensure_learn()
        test_clock.ensure(self._DEFAULT_DATE)
        self._deck_defs.append((name, resource, cards))

    def want_to_learn(self, name: str, deck: str) -> None:
        key = self._user(name)
        org_id = self._learn_org[key]
        self._seed(lambda s: self._materialize(org_id, s))
        resp = self._learn_ctx[key].request.post(
            self._url(key, "/subscriptions"), form={"deck": deck}
        )
        assert resp.status == 200, f"subscribe -> {resp.status}"

    # ── preset progress ─────────────────────────────────────────────────────────
    def preset_card(self, name: str, ext: str, level: int, days_ago: int) -> None:
        key = self._user(name)
        org_id, uid = self._learn_org[key], self._learn_uid[key]
        last = self._today() - timedelta(days=days_ago)

        async def _do(s):
            cid = await setup.card_id_by_external(s, org_id, ext)
            await setup.set_state(s, org_id, uid, cid, level, last)

        self._seed(_do)

    def preset_deck(self, name: str, deck: str, level: int, days_ago: int) -> None:
        key = self._user(name)
        org_id, uid = self._learn_org[key], self._learn_uid[key]
        last = self._today() - timedelta(days=days_ago)

        async def _do(s):
            deck_id = await setup.deck_id_by_name(s, org_id, deck)
            for cid in await setup.deck_card_ids(s, deck_id):
                await setup.set_state(s, org_id, uid, cid, level, last)

        self._seed(_do)

    def preset_table(self, name: str, rows: list[dict]) -> None:
        key = self._user(name)
        org_id, uid = self._learn_org[key], self._learn_uid[key]

        async def _do(s):
            for r in rows:
                cid = await setup.card_id_by_external(s, org_id, r["ID"])
                d, m, y = r["Date de dernière révision"].split("/")
                last = date(int(y), int(m), int(d))
                await setup.set_state(s, org_id, uid, cid, int(r["Niveau"]), last)

        self._seed(_do)

    # ── session actions ─────────────────────────────────────────────────────────
    def start_session(self, name: str) -> None:
        self._goto_today(self._user(name))

    def look_today(self, name: str) -> None:
        self._goto_today(self._user(name))

    def mark(self, name: str, ext: str, outcome: str) -> None:
        key = self._user(name)
        page = self._goto_today(key)
        card = page.locator(f".lcard[data-card-id='{ext}']")
        with page.expect_response(
            lambda r: f"/cards/{ext}/reviews" in r.url and r.request.method == "POST"
        ):
            card.locator(f"[data-mark='{outcome}']").click()

    def mark_all_learned(self, name: str) -> None:
        key = self._user(name)
        page = self._goto_today(key)
        ids = [c.get_attribute("data-card-id") for c in page.locator(".lcard").all()]
        for ext in ids:
            self.mark(name, ext, "learned")

    def reveal_answer(self, name: str, ext: str, answer: str) -> None:
        key = self._user(name)
        page = self._goto_today(key)
        card = page.locator(f".lcard[data-card-id='{ext}']")
        with page.expect_response(lambda r: f"/learning/cards/{ext}" in r.url):
            card.locator("[data-reveal]").click()
        text = (card.locator("[data-answer]").text_content() or "").strip()
        assert text == answer, f"answer {text!r} != {answer!r}"

    def look_resources(self, name: str) -> None:
        key = self._user(name)
        self._page_for(key).goto(self._url(key, "/resources"), wait_until="load")

    # ── assertions ──────────────────────────────────────────────────────────────
    def assert_due_count(self, name: str, n: int) -> None:
        key = self._user(name)
        page = self._goto_today(key)
        count = int(page.locator("#learning-session").get_attribute("data-due-count") or "0")
        assert count == n, f"expected {n} due cards, got {count}"

    def assert_first_card(self, name: str, ext: str, question: str) -> None:
        key = self._user(name)
        page = self._goto_today(key)
        first = page.locator(".lcard").first
        assert first.get_attribute("data-card-id") == ext
        text = (first.locator("[data-question]").text_content() or "").strip()
        assert text == question, f"question {text!r} != {question!r}"

    def assert_order(self, name: str, rows: list[dict]) -> None:
        key = self._user(name)
        page = self._goto_today(key)
        cards = page.locator(".lcard").all()
        actual = [
            (c.get_attribute("data-card-id"), int(c.get_attribute("data-card-level") or "0"))
            for c in cards
        ]
        expected = [(r["ID"], int(r["Niveau"])) for r in rows]
        assert actual == expected, f"order {actual} != {expected}"

    def assert_resources(self, name: str, rows: list[dict]) -> None:
        key = self._user(name)
        page = self._page_for(key)
        page.goto(self._url(key, "/resources"), wait_until="load")
        items = page.locator("#learning-resources > [data-resource-deck]").all()
        actual = [
            (
                i.get_attribute("data-resource-deck"),
                (i.locator("[data-resource]").text_content() or "").strip(),
            )
            for i in items
        ]
        expected = [(r["Paquet"], r["Ressources"]) for r in rows]
        assert actual == expected, f"resources {actual} != {expected}"

    def assert_no_resources(self, name: str) -> None:
        key = self._user(name)
        page = self._page_for(key)
        page.goto(self._url(key, "/resources"), wait_until="load")
        assert page.locator("#learning-resources [data-empty]").count() == 1

    def _current(self) -> str:
        assert self._learn_current is not None, "no acting user"
        return self._learn_current

    def assert_level(self, ext: str, level: int) -> None:
        state = self._card_state(self._current(), ext)
        assert state["level"] == level, f"level {state['level']} != {level}"

    def assert_last_review_today(self, ext: str) -> None:
        state = self._card_state(self._current(), ext)
        assert state["last_reviewed_on"] == self._today().isoformat(), (
            f"last_reviewed_on={state['last_reviewed_on']!r} != today={self._today().isoformat()!r}"
        )

    def assert_next_review_in(self, ext: str, days: int) -> None:
        state = self._card_state(self._current(), ext)
        expected = (self._today() + timedelta(days=days)).isoformat()
        assert state["next_review_on"] == expected, f"{state['next_review_on']} != {expected}"
