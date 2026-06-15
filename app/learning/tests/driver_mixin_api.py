import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

import tests.db as db
from app.learning.tests import setup
from app.shared import clock
from tests.e2e.drivers.protocols import ApiProtocol


class LearningApiMixin(ApiProtocol):
    # ── state ────────────────────────────────────────────────────────────────
    def _ensure_learn(self) -> None:
        if not hasattr(self, "_learn_clients"):
            self._learn_clients: dict = {}
            self._learn_handle: dict = {}
            self._learn_org: dict = {}
            self._learn_uid: dict = {}
            self._deck_defs: list = []
            self._learn_current: str | None = None

    # Default deterministic "today" for scenarios that don't pin one explicitly.
    _DEFAULT_DATE = "2024-09-01"

    def _today(self) -> date:
        return clock.now().date()

    def _reset_learning(self) -> None:
        self._learn_clients = {}
        self._learn_handle = {}
        self._learn_org = {}
        self._learn_uid = {}
        self._deck_defs = []
        self._learn_current = None

    async def _seed(self, fn):
        assert db._test_connection is not None, "No test transaction"
        async with AsyncSession(bind=db._test_connection, expire_on_commit=False) as s:
            result = await fn(s)
            await s.commit()
            return result

    # ── users / orgs ──────────────────────────────────────────────────────────
    def _user(self, name: str) -> str:
        self._ensure_learn()
        key = name.lower()
        self._learn_current = key
        if key not in self._learn_clients:
            email = f"{key}@example.com"
            client = self._make_client_for(email)
            resp = self._run(client.get("/organizations", headers={"accept": "application/json"}))
            assert resp.status_code == 200 and resp.json(), f"no org for {email}: {resp.text}"
            org = resp.json()[0]
            self._learn_clients[key] = client
            self._learn_handle[key] = org["handle"]
            self._learn_org[key] = uuid.UUID(org["id"])
            self._learn_uid[key] = uuid.UUID(self._user_id_for_email(email))
        return key

    def _api(self, key: str, method: str, path: str, **kw):
        client = self._learn_clients[key]
        url = f"/{self._learn_handle[key]}/learning{path}"
        resp = self._run(getattr(client, method)(url, **kw))
        return resp

    def _json(self, key: str, path: str):
        resp = self._api(key, "get", path, headers={"accept": "application/json"})
        assert resp.status_code == 200, f"GET {path} -> {resp.status_code}: {resp.text}"
        return resp.json()

    async def _materialize(self, org_id: uuid.UUID, session: AsyncSession) -> None:
        for pos, (name, resource, cards) in enumerate(self._deck_defs):
            await setup.create_deck(session, org_id, name, resource, pos, cards)

    # ── catalog & subscription ─────────────────────────────────────────────────
    def define_deck(self, name: str, resource: str | None, cards: list[dict]) -> None:
        self._ensure_learn()
        self.ensure_clock(self._DEFAULT_DATE)
        self._deck_defs.append((name, resource, cards))

    def want_to_learn(self, name: str, deck: str) -> None:
        key = self._user(name)
        org_id = self._learn_org[key]
        self._run(self._seed(lambda s: self._materialize(org_id, s)))
        resp = self._api(key, "post", "/subscriptions", data={"deck": deck})
        assert resp.status_code == 200, f"subscribe -> {resp.status_code}: {resp.text}"

    # ── preset progress ─────────────────────────────────────────────────────────
    def preset_card(self, name: str, ext: str, level: int, days_ago: int) -> None:
        key = self._user(name)
        org_id, uid = self._learn_org[key], self._learn_uid[key]
        last = self._today() - timedelta(days=days_ago)

        async def _do(s):
            cid = await setup.card_id_by_external(s, org_id, ext)
            await setup.set_state(s, org_id, uid, cid, level, last)

        self._run(self._seed(_do))

    def preset_deck(self, name: str, deck: str, level: int, days_ago: int) -> None:
        key = self._user(name)
        org_id, uid = self._learn_org[key], self._learn_uid[key]
        last = self._today() - timedelta(days=days_ago)

        async def _do(s):
            deck_id = await setup.deck_id_by_name(s, org_id, deck)
            for cid in await setup.deck_card_ids(s, deck_id):
                await setup.set_state(s, org_id, uid, cid, level, last)

        self._run(self._seed(_do))

    def preset_table(self, name: str, rows: list[dict]) -> None:
        key = self._user(name)
        org_id, uid = self._learn_org[key], self._learn_uid[key]

        async def _do(s):
            for r in rows:
                cid = await setup.card_id_by_external(s, org_id, r["ID"])
                d, m, y = r["Date de dernière révision"].split("/")
                last = date(int(y), int(m), int(d))
                await setup.set_state(s, org_id, uid, cid, int(r["Niveau"]), last)

        self._run(self._seed(_do))

    # ── session actions ─────────────────────────────────────────────────────────
    def start_session(self, name: str) -> None:
        self._user(name)

    def look_today(self, name: str) -> None:
        self._user(name)

    def mark(self, name: str, ext: str, outcome: str) -> None:
        key = self._user(name)
        resp = self._api(key, "post", f"/cards/{ext}/reviews", data={"outcome": outcome})
        assert resp.status_code == 200, f"mark -> {resp.status_code}: {resp.text}"

    def mark_all_learned(self, name: str) -> None:
        key = self._user(name)
        for card in self._json(key, "/sessions")["cards"]:
            self.mark(name, card["external_id"], "learned")

    def reveal_answer(self, name: str, ext: str, answer: str) -> None:
        key = self._user(name)
        detail = self._json(key, f"/cards/{ext}")
        assert detail["answer"] == answer, f"answer {detail['answer']!r} != {answer!r}"

    def look_resources(self, name: str) -> None:
        self._user(name)

    # ── assertions ──────────────────────────────────────────────────────────────
    def assert_due_count(self, name: str, n: int) -> None:
        key = self._user(name)
        count = self._json(key, "/sessions")["count"]
        assert count == n, f"expected {n} due cards, got {count}"

    def assert_first_card(self, name: str, ext: str, question: str) -> None:
        key = self._user(name)
        cards = self._json(key, "/sessions")["cards"]
        assert cards, "no due cards"
        assert cards[0]["external_id"] == ext, f"first card {cards[0]['external_id']} != {ext}"
        assert cards[0]["question"] == question, (
            f"question {cards[0]['question']!r} != {question!r}"
        )

    def assert_order(self, name: str, rows: list[dict]) -> None:
        key = self._user(name)
        cards = self._json(key, "/sessions")["cards"]
        actual = [(c["external_id"], c["level"]) for c in cards]
        expected = [(r["ID"], int(r["Niveau"])) for r in rows]
        assert actual == expected, f"order {actual} != {expected}"

    def assert_resources(self, name: str, rows: list[dict]) -> None:
        key = self._user(name)
        items = self._json(key, "/resources")
        actual = [(i["deck"], i["resource"]) for i in items]
        expected = [(r["Paquet"], r["Ressources"]) for r in rows]
        assert actual == expected, f"resources {actual} != {expected}"

    def assert_no_resources(self, name: str) -> None:
        key = self._user(name)
        items = self._json(key, "/resources")
        assert items == [], f"expected no resources, got {items}"

    def _current(self) -> str:
        assert self._learn_current is not None, "no acting user"
        return self._learn_current

    def assert_level(self, ext: str, level: int) -> None:
        detail = self._json(self._current(), f"/cards/{ext}")
        assert detail["level"] == level, f"level {detail['level']} != {level}"

    def assert_last_review_today(self, ext: str) -> None:
        detail = self._json(self._current(), f"/cards/{ext}")
        assert detail["last_reviewed_on"] == self._today().isoformat(), (
            f"last review {detail['last_reviewed_on']} != today {self._today().isoformat()}"
        )

    def assert_next_review_in(self, ext: str, days: int) -> None:
        detail = self._json(self._current(), f"/cards/{ext}")
        expected = (self._today() + timedelta(days=days)).isoformat()
        assert detail["next_review_on"] == expected, (
            f"next review {detail['next_review_on']} != {expected}"
        )
