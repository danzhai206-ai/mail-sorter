"""設定の読み込み。

設定は2か所にあります。
- .env       … APIキーや動作のオン/オフ（環境変数）
- rules.yaml … 仕分けルール（自分で編集する）
"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# 秘密情報や実行結果を置くフォルダ（Gitには入れない）
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CREDENTIALS_FILE = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", DATA_DIR / "credentials.json"))
TOKEN_FILE = DATA_DIR / "token.json"
DB_FILE = Path(os.getenv("DB_FILE", DATA_DIR / "mail_sorter.db"))
RULES_FILE = Path(os.getenv("RULES_FILE", BASE_DIR / "rules.yaml"))

USE_AI = _bool("USE_AI", True)
# どのAIを使うか: ollama（自分のPC・無料） / claude（Anthropic・有料）
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").strip().lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
AI_BODY_CHARS = int(os.getenv("AI_BODY_CHARS", "4000"))

FETCH_QUERY = os.getenv("FETCH_QUERY", "in:inbox newer_than:2d")
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "30"))
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "10"))

DRY_RUN = _bool("DRY_RUN", True)
# true: Gmailの権限を「読むだけ」にする（ラベルは付けられない。漏れても被害が小さい）
GMAIL_READONLY = _bool("GMAIL_READONLY", True)
ARCHIVE_JUNK = _bool("ARCHIVE_JUNK", False)
STAR_HIGH = _bool("STAR_HIGH", True)
LABEL_PREFIX = os.getenv("LABEL_PREFIX", "AI仕分け")


def load_rules() -> dict:
    """rules.yaml を読み込む。ファイルが無ければ空の設定を返す。"""
    if not RULES_FILE.exists():
        return {}
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8")) or {}
