"""Gmailへの初回ログイン。 実行: python -m app.auth"""
from .gmail_client import GmailClient

if __name__ == "__main__":
    client = GmailClient(interactive=True)
    print(f"ログインできました: {client.profile_email()}")
    print("data/token.json に合鍵を保存しました。次は python -m app.run_once を試してください。")
