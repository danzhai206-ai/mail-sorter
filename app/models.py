"""アプリ全体で使うデータの形。"""
from dataclasses import dataclass, field

# 重要度は4段階。左ほど重要。
LEVELS = ["high", "medium", "low", "junk"]
LEVEL_NAMES = {"high": "高", "medium": "中", "low": "低", "junk": "不要"}


@dataclass
class Email:
    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    body: str
    label_ids: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Decision:
    level: str   # LEVELS のどれか
    reason: str  # 判定理由（画面に表示する）
    source: str  # "rule"（ルール）/ "ai"（AI）/ "default"（どちらも使えなかった）
