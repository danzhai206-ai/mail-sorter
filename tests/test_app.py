"""自動テスト。Gmailにも Claude にもつながずに動く。 実行: python -m pytest"""
import base64
import os
import tempfile

# テスト用に一時フォルダのDBを使う（本物のデータを汚さない）
_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["DB_FILE"] = os.path.join(_tmp, "test.db")
os.environ["DRY_RUN"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app import db, sorter  # noqa: E402
from app.ai_classifier import build_prompt  # noqa: E402
from app.gmail_client import parse_message  # noqa: E402
from app.models import Decision, Email  # noqa: E402
from app.rules import classify_by_rules  # noqa: E402


def make_email(**kw) -> Email:
    base = dict(id="m1", thread_id="t1", sender="Shop <news@shop.example>", subject="セールのお知らせ",
                date="Mon, 1 Jan 2026", snippet="", body="今だけ半額", label_ids=["INBOX"], headers={})
    base.update(kw)
    return Email(**base)


RULES = {
    "rules": [
        {"name": "上司", "level": "high", "from_contains": ["boss@work.example"]},
        {"name": "宣伝", "level": "junk", "gmail_label": "CATEGORY_PROMOTIONS"},
        {"name": "メルマガ", "level": "low", "has_list_unsubscribe": True},
        {"name": "条件なし", "level": "high"},  # 条件が無いルールは無視される
    ]
}


def test_rule_from():
    d = classify_by_rules(make_email(sender="Boss <BOSS@work.example>"), RULES)
    assert d.level == "high" and d.source == "rule"


def test_rule_gmail_label():
    d = classify_by_rules(make_email(label_ids=["INBOX", "CATEGORY_PROMOTIONS"]), RULES)
    assert d.level == "junk"


def test_rule_unsubscribe_header():
    d = classify_by_rules(make_email(headers={"List-Unsubscribe": "<mailto:x>"}), RULES)
    assert d.level == "low"


def test_no_rule_match_and_empty_rule_ignored():
    assert classify_by_rules(make_email(), RULES) is None


def test_decide_without_ai_uses_default():
    d = sorter.decide(make_email(), {"default_level": "low"}, ai=None)
    assert d.level == "low" and d.source == "default"


def test_parse_message_prefers_plain_text():
    enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    msg = {
        "id": "abc", "threadId": "t", "snippet": "こんにちは &amp; さようなら", "labelIds": ["INBOX"],
        "payload": {
            "headers": [{"name": "From", "value": "a@b.c"}, {"name": "Subject", "value": "件名"}],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": enc("<p>HTML版</p>")}},
                {"mimeType": "text/plain", "body": {"data": enc("テキスト版")}},
            ],
        },
    }
    e = parse_message(msg)
    assert e.subject == "件名" and e.body == "テキスト版" and e.snippet == "こんにちは & さようなら"


def test_parse_message_html_only():
    enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode()
    msg = {"id": "x", "payload": {"mimeType": "text/html",
                                  "body": {"data": enc("<style>a{}</style><p>本文&amp;です</p>")}}}
    assert parse_message(msg).body == "本文&です"


def test_prompt_truncates_and_includes_corrections():
    p = build_prompt(make_email(body="あ" * 50), [{"sender": "s", "subject": "j", "level": "high"}], body_chars=10)
    assert "先頭 10 文字" in p and "→ high" in p and "あ" * 11 not in p
    assert "本文は送っていません" in build_prompt(make_email(), [], body_chars=0)


def test_ollama_classifier(monkeypatch):
    import httpx
    from app.ollama_classifier import OllamaClassifier

    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, body=json)
        return httpx.Response(200, json={"message": {"content": '{"level": "high", "reason": "返信が必要"}'}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    d = OllamaClassifier(model="m", url="http://x:1").classify(make_email())
    assert (d.level, d.source) == ("high", "ai")
    assert sent["url"] == "http://x:1/api/chat" and sent["body"]["format"]["required"] == ["level", "reason"]

    def refused(url, json, timeout):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(httpx, "post", refused)
    assert OllamaClassifier(url="http://x:1").classify(make_email()) is None


class FakeGmail:
    def __init__(self, emails):
        self.emails = {e.id: e for e in emails}

    def list_message_ids(self, query, n):
        return list(self.emails)

    def get_email(self, i):
        return self.emails[i]


class FakeWritableGmail(FakeGmail):
    """ラベル変更もできる偽物のGmail。何をされたかを記録する。"""

    def __init__(self, emails):
        super().__init__(emails)
        self.modified = {}

    def ensure_label(self, name):
        return name

    def modify(self, msg_id, add, remove):
        self.modified[msg_id] = add


def test_labels_applied_later_when_dry_run_turned_off(monkeypatch):
    from app import config
    emails = [make_email(id="p1"), make_email(id="p2", label_ids=["CATEGORY_PROMOTIONS"])]
    sorter.run_once(gmail=FakeGmail(emails), ai=FakeAI())          # お試しモードで判定だけ
    assert {r["id"] for r in db.unapplied()} >= {"p1", "p2"}

    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "GMAIL_READONLY", False)
    g = FakeWritableGmail(emails)
    assert sorter.run_once(gmail=g, ai=FakeAI()) == []             # 新しいメールは無い
    assert g.modified["p1"] == ["AI仕分け/中"]                      # でもラベルはあとから付く
    assert g.modified["p2"] == ["AI仕分け/不要"]
    assert not {r["id"] for r in db.unapplied()} & {"p1", "p2"}


class FakeAI:
    def classify(self, email, corrections=None):
        return Decision("medium", "テスト", "ai")


def test_run_once_dry_run_and_web():
    emails = [make_email(id="a1"), make_email(id="a2", label_ids=["CATEGORY_PROMOTIONS"])]
    results = sorter.run_once(gmail=FakeGmail(emails), ai=FakeAI())
    assert {r["id"]: r["level"] for r in results} == {"a1": "medium", "a2": "junk"}
    # 2回目は処理済みなのでスキップされる
    assert sorter.run_once(gmail=FakeGmail(emails), ai=FakeAI()) == []

    from app.web import app
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200 and "セールのお知らせ" in page.text

    r = client.post("/messages/a1/level", data={"level": "high"}, follow_redirects=False)
    assert r.status_code == 303
    row = db.get("a1")
    assert row["level"] == "high" and row["corrected"] == 1
    assert db.recent_corrections()[0]["level"] == "high"

    assert client.post("/messages/a1/level", data={"level": "bad"}).status_code == 400
    assert client.get("/health").json() == {"status": "ok"}


def test_rules_imported_from_yaml_only_once():
    db.init_db()
    names = [r["name"] for r in db.list_rules()]
    assert "Gmailのプロモーション分類" in names           # rules.yaml の中身が入っている
    assert db.import_rules_once([{"name": "x", "level": "high", "from_contains": ["x"]}]) == 0  # 2回目は取り込まない
    assert db.list_rules()[0]["gmail_label"] == ["CATEGORY_PROMOTIONS"]  # 文字1つはリストにそろう


def test_rules_api_crud():
    from app.web import app
    client = TestClient(app)

    # 作成: 201 が返り、番号（id）が振られる
    r = client.post("/api/rules", json={"name": "上司", "level": "high", "from_contains": ["boss@work.example"]})
    assert r.status_code == 201
    rule = r.json()
    assert rule["id"] > 0 and rule["position"] == max(x["position"] for x in db.list_rules())

    # 作ったルールで実際に仕分けされる
    boss = make_email(id="b1", sender="Boss <boss@work.example>", subject="明日の会議")
    assert sorter.run_once(gmail=FakeGmail([boss]), ai=FakeAI()) == [{"id": "b1", "subject": "明日の会議", "level": "high"}]

    # 読む
    assert client.get(f"/api/rules/{rule['id']}").json()["name"] == "上司"
    assert any(x["id"] == rule["id"] for x in client.get("/api/rules").json())

    # 更新: 丸ごと置き換え。position を省略すると順番は変わらない
    r = client.put(f"/api/rules/{rule['id']}", json={"name": "上司", "level": "medium", "subject_contains": ["会議"]})
    assert r.status_code == 200
    updated = r.json()
    assert updated["level"] == "medium" and updated["from_contains"] is None and updated["position"] == rule["position"]

    # 入力チェック: 条件なし・不正な重要度・空文字は 422
    assert client.post("/api/rules", json={"name": "条件なし", "level": "high"}).status_code == 422
    assert client.post("/api/rules", json={"name": "x", "level": "urgent", "from_contains": ["a"]}).status_code == 422
    assert client.post("/api/rules", json={"name": "x", "level": "high", "from_contains": [""]}).status_code == 422

    # 削除: 204。もう一度消そうとすると 404
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 404
    assert client.get(f"/api/rules/{rule['id']}").status_code == 404
    assert client.put("/api/rules/99999", json={"name": "x", "level": "high", "from_contains": ["a"]}).status_code == 404
