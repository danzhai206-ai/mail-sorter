"""Gmail API とのやりとり。

認証の流れ（OAuth）:
1. 初回は data/credentials.json（Google Cloudで作る「アプリの身分証」）を使い、
   ブラウザで自分のGoogleアカウントにログインして許可する。
2. 許可されると data/token.json（「合鍵」）が保存される。
3. 2回目以降は token.json を使うので、ブラウザでのログインは不要。
"""
import base64
import html
import re

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config
from .models import Email

# アプリに与える権限（スコープ）
# - gmail.readonly: 読むだけ
# - gmail.modify:   読む・ラベル変更に加え、送信やゴミ箱移動もできる（完全削除だけはできない）
if config.GMAIL_READONLY:
    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
else:
    SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def get_credentials(interactive: bool = False) -> Credentials:
    creds = None
    if config.TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE))
        if not creds.has_scopes(SCOPES):
            creds = None  # 権限の設定を変えたので、ログインし直す

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            config.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except RefreshError:
            creds = None  # 合鍵が無効になった。ログインし直す。

    if not interactive:
        raise RuntimeError(
            "Gmailにログインしていません。先に `python -m app.auth` を実行してください。"
        )
    if not config.CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"{config.CREDENTIALS_FILE} がありません。README の「Google Cloud の設定」を見てください。"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)  # ブラウザが開く
    config.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", raw)).strip()


def extract_body(payload: dict) -> str:
    """メールの本文を取り出す。テキスト版があればそれを、無ければHTML版を文字だけにして使う。"""
    plain, htmls = [], []

    def walk(part: dict):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            htmls.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    if htmls:
        return html_to_text("\n".join(htmls))
    return ""


def parse_message(msg: dict) -> Email:
    payload = msg.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    lower = {k.lower(): v for k, v in headers.items()}
    return Email(
        id=msg["id"],
        thread_id=msg.get("threadId", ""),
        sender=lower.get("from", ""),
        subject=lower.get("subject", "(件名なし)"),
        date=lower.get("date", ""),
        snippet=html.unescape(msg.get("snippet", "")),
        body=extract_body(payload),
        label_ids=msg.get("labelIds", []),
        headers=headers,
    )


class GmailClient:
    def __init__(self, interactive: bool = False):
        creds = get_credentials(interactive=interactive)
        self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._label_ids: dict[str, str] | None = None

    def profile_email(self) -> str:
        return self.service.users().getProfile(userId="me").execute()["emailAddress"]

    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        resp = self.service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        return [m["id"] for m in resp.get("messages", [])]

    def get_email(self, msg_id: str) -> Email:
        msg = self.service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        return parse_message(msg)

    def ensure_label(self, name: str) -> str:
        """ラベルが無ければ作り、そのIDを返す。「親/子」と書くと入れ子のラベルになる。"""
        if self._label_ids is None:
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
            self._label_ids = {l["name"]: l["id"] for l in labels}
        if name not in self._label_ids:
            created = self.service.users().labels().create(
                userId="me",
                body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            ).execute()
            self._label_ids[name] = created["id"]
        return self._label_ids[name]

    def modify(self, msg_id: str, add: list[str], remove: list[str]) -> None:
        self.service.users().messages().modify(
            userId="me", id=msg_id, body={"addLabelIds": add, "removeLabelIds": remove}
        ).execute()
