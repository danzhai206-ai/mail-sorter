"""体験版：偽物のメールで、本物の仕分けプログラムを動かす。

実行: python -m app.demo

- Gmail の代わりに、下の SAMPLE_EMAILS（偽物のメール6通）を使います。
- 仕分けの本体（sorter.py / rules.py / db.py）は本物をそのまま使います。
- AI は APIキーがあれば本物の Claude、無ければ「代役」（キーワードで判定するだけの偽物）を使います。
- 結果は data/demo.db に保存され、本番のデータとは混ざりません。
"""
import os
import sys
import time
from pathlib import Path

# 設定を読み込む「前」に、体験版用の設定に切り替える
DEMO_DB = Path(__file__).resolve().parent.parent / "data" / "demo.db"
os.environ["DB_FILE"] = str(DEMO_DB)
os.environ["DRY_RUN"] = "true"  # 念のため、Gmailを変更しないモードにする

from . import config, db, rules, sorter  # noqa: E402
from .models import LEVEL_NAMES, Decision, Email  # noqa: E402

PAUSE = 0.6  # 動きを目で追えるように、少し待つ（秒）


def step(text: str) -> None:
    print(text)
    time.sleep(PAUSE)


SAMPLE_EMAILS = [
    Email(id="demo1", thread_id="t1", sender="田中部長 <tanaka@work.example>",
          subject="明日の会議資料の確認をお願いします", date="2026-11-18 09:12", snippet="",
          body="お疲れさまです。明日10時の会議の資料を添付しました。今日中に確認して返信してください。",
          label_ids=["INBOX"]),
    Email(id="demo2", thread_id="t2", sender="Amazon.co.jp <order@amazon.example>",
          subject="ご注文の確認", date="2026-11-18 08:30", snippet="",
          body="ご注文ありがとうございます。お届け予定日は11月20日です。", label_ids=["INBOX"]),
    Email(id="demo3", thread_id="t3", sender="ショップ <sale@shop.example>",
          subject="【本日限り】全品50%OFFセール！", date="2026-11-18 07:00", snippet="",
          body="今だけ全品半額！お見逃しなく！", label_ids=["INBOX", "CATEGORY_PROMOTIONS"]),
    Email(id="demo4", thread_id="t4", sender="SNS通知 <notify@sns.example>",
          subject="あなたの投稿に「いいね」が3件つきました", date="2026-11-17 22:45", snippet="",
          body="あなたの投稿に新しい反応があります。", label_ids=["INBOX", "CATEGORY_SOCIAL"]),
    Email(id="demo5", thread_id="t5", sender="セキュリティ担当 <support@bank-check.example>",
          subject="【至急】アカウントが停止されます", date="2026-11-17 21:10", snippet="",
          body="24時間以内に下のリンクからパスワードを入力しないと、アカウントが停止されます。",
          label_ids=["INBOX"]),
    Email(id="demo6", thread_id="t6", sender="技術ニュース <news@tech.example>",
          subject="今週の技術ニュースまとめ", date="2026-11-17 18:00", snippet="",
          body="今週の注目記事をお届けします。配信停止はこちら。", label_ids=["INBOX"],
          headers={"List-Unsubscribe": "<mailto:unsubscribe@tech.example>"}),
]

# 体験版だけで使う追加ルール（rules.yaml の後に足す）
DEMO_RULES = [
    {"name": "メルマガ（配信停止ヘッダーあり）", "level": "low", "has_list_unsubscribe": True},
]


class FakeGmail:
    """Gmailのふりをする偽物。本物の GmailClient と同じ名前の手順を持っている。"""

    def list_message_ids(self, query, max_results):
        step(f"\n📬 Gmail（偽物）に「新しいメールある？」と聞きました → {len(SAMPLE_EMAILS)} 通ありました")
        return [e.id for e in SAMPLE_EMAILS]

    def get_email(self, msg_id):
        email = next(e for e in SAMPLE_EMAILS if e.id == msg_id)
        print("\n" + "─" * 60)
        step(f"① メールを取得：「{email.subject}」\n   差出人: {email.sender}")
        return email


def traced_rules(email, rules_config):
    """本物のルール判定を呼び、その前後で様子を表示する。"""
    step("② ルール（rules.yaml）と見比べています…")
    decision = rules.classify_by_rules(email, rules_config)
    if decision:
        step(f"   → 当てはまりました！ {decision.reason}")
    else:
        step("   → どのルールにも当てはまりません。AIに聞きます")
    return decision


class StandInAI:
    """APIキーが無いときの代役。キーワードを見るだけで、本物のAIではない。"""

    def classify(self, email, corrections=None):
        step("③ AI（代役）に質問中…  ※APIキーが無いので、本物のClaudeではありません")
        text = email.subject + email.body
        if "至急" in text and "パスワード" in text:
            return Decision("junk", "詐欺の疑い（代役の簡易判定）", "ai")
        if "返信" in text or "確認して" in text:
            return Decision("high", "返信が必要な依頼（代役の簡易判定）", "ai")
        return Decision("medium", "急ぎではない連絡（代役の簡易判定）", "ai")


class TracedAI:
    """本物のClaudeを呼び、その前に様子を表示する。"""

    def __init__(self, real):
        self.real = real

    def classify(self, email, corrections=None):
        model = config.CLAUDE_MODEL if config.AI_PROVIDER == "claude" else f"{config.OLLAMA_MODEL}（自分のPC）"
        step(f"③ 本物のAI（{model}）に質問中…")
        return self.real.classify(email, corrections)


def main():
    if DEMO_DB.exists():
        DEMO_DB.unlink()  # 毎回まっさらな状態から始める

    rules_config = config.load_rules()
    rules_config["rules"] = (rules_config.get("rules") or []) + DEMO_RULES
    config.load_rules = lambda: rules_config      # 体験版ルールを使わせる
    sorter.classify_by_rules = traced_rules       # ルール判定の様子を表示させる

    use_real_ai = config.USE_AI and (config.AI_PROVIDER != "claude" or os.getenv("ANTHROPIC_API_KEY"))
    if use_real_ai:
        ai = TracedAI(sorter.make_classifier(rules_config.get("ai_instructions", "")))
    else:
        ai = StandInAI()

    print("=" * 60)
    print(" 体験版：偽物のメールで仕分けプログラムを動かします")
    print("=" * 60)

    # ここで呼んでいるのは、本番と同じ sorter.run_once
    results = sorter.run_once(gmail=FakeGmail(), ai=ai)

    print("\n" + "=" * 60)
    print(" 結果（本物なら、Gmailにこのラベルが付きます）")
    print("=" * 60)
    for r in db.recent(100):
        print(f"  [{LEVEL_NAMES[r['level']]:　<2}] {r['subject']}")
        print(f"         └ {r['reason']}")
    print(f"\n{len(results)} 通を仕分けしました。結果は {DEMO_DB} に保存しました。")
    print("\nWeb画面で見るには、次の2行を実行して http://127.0.0.1:8000 を開いてください:")
    print(f'  $env:DB_FILE="{DEMO_DB}"')
    print("  python -m uvicorn app.web:app")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
