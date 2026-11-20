"""自分のPCで動くAI（Ollama）による重要度の判定。完全無料で、メールがPCの外に出ない。

Ollama は「AIを動かすサーバー」です。PCの中で http://localhost:11434 という窓口を開いて待っていて、
このプログラムはそこに質問を送り、答えを受け取ります（Web画面とブラウザの関係と同じ）。

  このアプリ ──「このメールの重要度は？」──→ Ollamaサーバー（PCの中）
            ←──{"level": "high", ...}──────

AIへの説明書（SYSTEM_PROMPT）や答えの形（OUTPUT_SCHEMA）は Claude 版と共通です。
"""
import json
import logging

import httpx

from . import config
from .ai_classifier import OUTPUT_SCHEMA, SYSTEM_PROMPT, build_prompt
from .models import LEVELS, Decision, Email

log = logging.getLogger(__name__)


class OllamaClassifier:
    def __init__(self, model: str | None = None, user_instructions: str = "", url: str | None = None):
        self.model = model or config.OLLAMA_MODEL
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        self.system = SYSTEM_PROMPT
        if user_instructions.strip():
            self.system += "\n\n受信者についての情報:\n" + user_instructions.strip()

    def classify(self, email: Email, corrections: list[dict] | None = None) -> Decision | None:
        """判定できなかったときは None を返す（呼び出し側で既定値を使う）。"""
        prompt = build_prompt(email, corrections or [], config.AI_BODY_CHARS)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": prompt},
            ],
            "format": OUTPUT_SCHEMA,  # 答えをこのJSONの形に固定する
            "think": False,           # 考える過程を省いて速くする（仕分け程度なら十分）
            "stream": False,
            "options": {"temperature": 0},  # 毎回同じ答えになりやすくする
        }
        try:
            resp = httpx.post(f"{self.url}/api/chat", json=body, timeout=120)
            resp.raise_for_status()
        except httpx.ConnectError:
            log.error("Ollamaに接続できません。Ollamaが起動しているか確認してください（%s）", self.url)
            return None
        except httpx.HTTPStatusError as e:
            log.error("Ollamaエラー (%s): %s", e.response.status_code, e.response.text[:200])
            return None
        except httpx.TimeoutException:
            log.error("Ollamaの返事が遅すぎました（タイムアウト）")
            return None

        text = resp.json().get("message", {}).get("content", "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.warning("AIの返答をJSONとして読めませんでした: %r", text[:200])
            return None
        if data.get("level") not in LEVELS:
            return None
        return Decision(level=data["level"], reason=data.get("reason", ""), source="ai")
