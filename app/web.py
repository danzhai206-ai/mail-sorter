"""判定結果を見るWeb画面（FastAPI）。

実行: python -m uvicorn app.web:app --reload
ブラウザで http://127.0.0.1:8000 を開く。

⚠ この画面にはログイン機能がありません。自分のPC（127.0.0.1）でだけ動かしてください。
  インターネットに公開するのは、ログイン機能を付けてから（段階6）です。
"""
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config, db, sorter
from .models import LEVEL_NAMES, LEVELS
from .schemas import RuleIn, RuleOut

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="メール仕分け")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
db.init_db()

_gmail = None


def gmail():
    """Gmailへの接続は最初に必要になったときに1回だけ作る。"""
    global _gmail
    if _gmail is None:
        from .gmail_client import GmailClient
        _gmail = GmailClient()
    return _gmail


@app.get("/")
def index(request: Request, level: str | None = None, message: str | None = None):
    if level not in LEVELS:
        level = None
    return templates.TemplateResponse(request, "index.html", {
        "messages": db.recent(200, level),
        "counts": db.counts(),
        "levels": LEVELS,
        "level_names": LEVEL_NAMES,
        "current": level,
        "dry_run": not sorter.can_modify(),
        "notice": message,
    })


@app.post("/run")
def run_now():
    try:
        results = sorter.run_once(gmail=gmail())
        msg = f"{len(results)} 件を仕分けしました"
    except Exception as e:
        log.exception("仕分けに失敗")
        msg = f"エラー: {e}"
    return RedirectResponse(f"/?message={quote(msg)}", status_code=303)


@app.post("/messages/{msg_id}/level")
def change_level(msg_id: str, level: str = Form(...)):
    if level not in LEVELS:
        raise HTTPException(400, "不正な重要度です")
    if db.get(msg_id) is None:
        raise HTTPException(404, "メールが見つかりません")
    sorter.change_level(gmail() if sorter.can_modify() else None, msg_id, level)
    return RedirectResponse("/", status_code=303)


@app.get("/api/messages")
def api_messages(level: str | None = None, limit: int = 100):
    """JSONで結果を返すAPI（他のプログラムから使う練習用）。"""
    return [dict(r) for r in db.recent(min(limit, 500), level if level in LEVELS else None)]


@app.get("/health")
def health():
    """サーバーが動いているかの確認用（段階6で監視に使う）。"""
    return {"status": "ok"}


# ---------- ルールのAPI（CRUD: 作成 Create / 読む Read / 更新 Update / 削除 Delete） ----------

def _rule_or_404(rule_id: int) -> dict:
    rule = db.get_rule(rule_id)
    if rule is None:
        raise HTTPException(404, "ルールが見つかりません")
    return rule


@app.get("/api/rules", response_model=list[RuleOut])
def api_list_rules():
    """ルールの一覧（判定する順番に並ぶ）。"""
    return db.list_rules()


@app.get("/api/rules/{rule_id}", response_model=RuleOut)
def api_get_rule(rule_id: int):
    return _rule_or_404(rule_id)


@app.post("/api/rules", response_model=RuleOut, status_code=201)
def api_create_rule(body: RuleIn):
    """ルールを追加する。成功すると 201（作成した）を返す。"""
    return db.create_rule(body.name, body.level, body.conditions(), body.position, body.enabled)


@app.put("/api/rules/{rule_id}", response_model=RuleOut)
def api_update_rule(rule_id: int, body: RuleIn):
    """ルールを丸ごと置き換える。"""
    rule = db.update_rule(rule_id, body.name, body.level, body.conditions(), body.position, body.enabled)
    if rule is None:
        raise HTTPException(404, "ルールが見つかりません")
    return rule


@app.delete("/api/rules/{rule_id}", status_code=204)
def api_delete_rule(rule_id: int):
    """ルールを削除する。成功すると 204（中身なしで成功）を返す。"""
    if not db.delete_rule(rule_id):
        raise HTTPException(404, "ルールが見つかりません")
    return Response(status_code=204)
