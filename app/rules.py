"""ルールによる判定（AIを使わない、速くて無料の判定）。

ルールはDBの rules テーブルに保存されています（初回起動時に rules.yaml から取り込み）。
並び順（position）の小さい順に見て、最初に一致したルールの重要度を使います。
1つのルールに条件が複数あるときは「すべて満たす」と一致（AND）。
条件の中のリストは「どれか1つ含む」と一致（OR）。大文字小文字は区別しません。
"""
from .models import LEVELS, Decision, Email

# ルールで使える条件の名前。DB保存・API・判定のすべてでこの一覧を使う
CONDITION_KEYS = ("from_contains", "subject_contains", "body_contains", "gmail_label", "has_list_unsubscribe")


def normalize_conditions(rule: dict) -> dict:
    """ルールから条件だけを取り出し、形をそろえる（文字1つ → リストにする、空は捨てる）。"""
    conditions = {}
    for key in CONDITION_KEYS:
        value = rule.get(key)
        if value is None:
            continue
        if key == "has_list_unsubscribe":
            conditions[key] = bool(value)
            continue
        words = value if isinstance(value, list) else [value]
        words = [str(w) for w in words if str(w).strip()]  # 空文字は「全部に一致」してしまうので捨てる
        if words:
            conditions[key] = words
    return conditions


def _contains_any(text: str, words: list[str]) -> bool:
    text = text.lower()
    return any(str(w).lower() in text for w in words)


def match_rule(email: Email, rule: dict) -> bool:
    checks = []
    if "from_contains" in rule:
        checks.append(_contains_any(email.sender, rule["from_contains"]))
    if "subject_contains" in rule:
        checks.append(_contains_any(email.subject, rule["subject_contains"]))
    if "body_contains" in rule:
        checks.append(_contains_any(email.subject + "\n" + email.body, rule["body_contains"]))
    if "gmail_label" in rule:
        # Gmailが自動で付けるカテゴリ（CATEGORY_PROMOTIONS など）で判定
        wanted = rule["gmail_label"]
        wanted = wanted if isinstance(wanted, list) else [wanted]
        checks.append(any(w in email.label_ids for w in wanted))
    if "has_list_unsubscribe" in rule:
        # メルマガには「配信停止」用のヘッダーが付いていることが多い
        has = "list-unsubscribe" in {k.lower() for k in email.headers}
        checks.append(has == bool(rule["has_list_unsubscribe"]))
    # 条件が1つも書かれていないルールは、誤って全部に一致しないよう無視する
    return bool(checks) and all(checks)


def classify_by_rules(email: Email, config: dict) -> Decision | None:
    for rule in config.get("rules") or []:
        level = rule.get("level")
        if level not in LEVELS:
            continue
        if match_rule(email, rule):
            return Decision(level=level, reason=f"ルール「{rule.get('name', '名前なし')}」に一致", source="rule")
    return None
