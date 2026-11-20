"""仕分けの本体。「取得 → 判定 → Gmailに反映 → 保存」を行う。"""
import logging

from . import config, db
from .ai_classifier import AIClassifier
from .models import LEVEL_NAMES, LEVELS, Decision, Email
from .rules import classify_by_rules

log = logging.getLogger(__name__)


def make_classifier(user_instructions: str = ""):
    """設定（AI_PROVIDER）に合わせて、AI担当を1人用意する。"""
    if config.AI_PROVIDER == "claude":
        return AIClassifier(user_instructions=user_instructions)
    from .ollama_classifier import OllamaClassifier
    return OllamaClassifier(user_instructions=user_instructions)


def can_modify() -> bool:
    """Gmailを変更してよいか。お試しモードか読み取り専用なら変更しない。"""
    return not config.DRY_RUN and not config.GMAIL_READONLY


def label_name(level: str) -> str:
    return f"{config.LABEL_PREFIX}/{LEVEL_NAMES[level]}"


def decide(email: Email, rules_config: dict, ai: AIClassifier | None) -> Decision:
    # 1. まずルールで判定（無料・高速）
    decision = classify_by_rules(email, rules_config)
    if decision:
        return decision
    # 2. ルールで決まらなければAIで判定
    if ai:
        decision = ai.classify(email, db.recent_corrections())
        if decision:
            return decision
    # 3. どちらもだめなら既定値
    default = rules_config.get("default_level", "medium")
    if default not in LEVELS:
        default = "medium"
    return Decision(level=default, reason="ルールに一致せず、AI判定も使えなかったため既定値", source="default")


def apply_level(gmail, msg_id: str, level: str) -> None:
    """Gmailのラベルを付け替える。他の重要度ラベルは外す。"""
    add = [gmail.ensure_label(label_name(level))]
    remove = [gmail.ensure_label(label_name(l)) for l in LEVELS if l != level]
    if level == "high" and config.STAR_HIGH:
        add.append("STARRED")
    if level == "junk" and config.ARCHIVE_JUNK:
        remove.append("INBOX")  # 受信トレイから外す＝アーカイブ（削除ではない）
    gmail.modify(msg_id, add=add, remove=remove)


def run_once(gmail=None, ai=None) -> list[dict]:
    """1回分の仕分けをして、処理したメールの一覧を返す。"""
    from .gmail_client import GmailClient  # Gmail不要なテストで読み込まずに済むようここで読む

    db.init_db()
    rules_config = config.load_rules()
    gmail = gmail or GmailClient()
    if ai is None and config.USE_AI:
        ai = make_classifier(rules_config.get("ai_instructions", ""))

    results = []
    for msg_id in gmail.list_message_ids(config.FETCH_QUERY, config.MAX_MESSAGES):
        if db.is_processed(msg_id):
            continue
        email = gmail.get_email(msg_id)
        decision = decide(email, rules_config, ai)

        applied = False
        if can_modify():
            apply_level(gmail, msg_id, decision.level)
            applied = True
        db.save(email, decision, applied)

        log.info("[%s] %s | %s (%s: %s)", LEVEL_NAMES[decision.level], email.sender, email.subject,
                 decision.source, decision.reason)
        results.append({"id": msg_id, "subject": email.subject, "level": decision.level})

    # お試しモード中に判定したメールにも、あとからラベルを付ける
    if can_modify():
        pending = db.unapplied()
        for row in pending:
            apply_level(gmail, row["id"], row["level"])
            db.mark_applied(row["id"])
        if pending:
            log.info("判定済みだった %d 通に、あとからラベルを付けました", len(pending))
    return results


def change_level(gmail, msg_id: str, level: str) -> None:
    """画面から重要度を手で直したとき。Gmailのラベルも合わせて直す。"""
    applied = False
    if can_modify():
        apply_level(gmail, msg_id, level)
        applied = True
    db.set_level(msg_id, level, applied)
