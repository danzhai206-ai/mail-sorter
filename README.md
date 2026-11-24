# mail-sorter — Gmail を AI で重要度別に自動仕分け

[![test](https://github.com/danzhai206-ai/mail-sorter/actions/workflows/test.yml/badge.svg)](https://github.com/danzhai206-ai/mail-sorter/actions/workflows/test.yml)

Gmail の受信メールを **高 / 中 / 低 / 不要** の4段階に自動で判定し、Gmail にラベルを付けるアプリです。
判定には、**ルール（無料・高速）** と、**自分の PC で動くローカル LLM（無料・メールが外部に出ない）** を組み合わせています。

![画面](docs/screenshot.png)
<sub>※ スクリーンショットは体験版のサンプルメールです。</sub>

## 特徴

- **2段階の判定**：まずルールで判定し、決まらなかったメールだけを AI に回します。速度と費用を抑えられ、AI に送るデータも減らせます。
- **ローカル LLM（Ollama + Qwen3 8B）**：API 料金が0円で、メール本文が PC の外に出ません。設定を1行変えれば、Claude API にも切り替えられます。
- **判定結果の修正から学習**：Web 画面で直した判定を、次回から AI へのお手本（few-shot）として渡します。
- **安全側の初期設定**：最初は「読み取り専用」と「お試しモード」で動きます。判定に納得してから、Gmail への書き込みを許可します。
- **常駐実行**：Windows のタスク スケジューラで、ログイン時に起動して10分ごとに仕分けます。Docker Compose でも動かせます。

## 構成

```mermaid
flowchart LR
    Gmail[(Gmail)] -- "① 取得 (Gmail API / OAuth)" --> Sorter
    subgraph PC["自分の PC"]
        Sorter["sorter.py<br/>仕分けの本体"] -- "② ルール判定" --> Rules["rules.py<br/>DBのルール"]
        Sorter -- "③ AI 判定 (HTTP)" --> Ollama["Ollama<br/>Qwen3 8B (GPU)"]
        Sorter -- "⑤ 記録" --> DB[(SQLite)]
        Web["web.py<br/>FastAPI"] -- 一覧・修正 --> DB
        Watch["watch.py<br/>10分ごと"] --> Sorter
    end
    Sorter -- "④ ラベル付け" --> Gmail
    Browser([ブラウザ]) --> Web
```

| 技術 | 用途 |
|---|---|
| Python 3.13 | 本体 |
| Gmail API / OAuth 2.0 | メールの取得・ラベルの付け替え |
| Ollama（Qwen3 8B） / Claude API | AI による判定（JSON スキーマで出力形式を固定） |
| FastAPI + Jinja2 | 判定結果を見る・直す Web 画面 |
| SQLite | 判定結果と修正履歴の保存 |
| pytest + GitHub Actions | 自動テスト（Gmail と AI は偽物に差し替えて実行） |
| Docker Compose | Web 画面と常駐処理のコンテナ化 |

## 設計で工夫したこと

| 課題 | 対応 |
|---|---|
| メールは個人情報のかたまりで、合鍵（OAuth トークン）が漏れたときの被害が大きい | 権限（スコープ）を `gmail.readonly` から始め、ラベルを付ける段階で初めて `gmail.modify` に広げる設計にした。秘密情報は `.env` と `data/` にまとめ、Git の管理から除外 |
| 本物のメールで試したら、ルールだけでは30通すべてが「中」になった | Gmail のカテゴリを集計したところ、29通が「新着（通知）」だった。通知の中には重要なものも混ざるため、ルールで一律に「低」にはせず、AI 判定を導入した |
| AI は使いたいが、費用とプライバシーが気になる | クラウドの有料 API・他社の無料枠・ローカル LLM を比較し、GPU（RTX 5070）があったのでローカル LLM を選んだ。1通あたり約3秒で判定できる |
| AI の答えの形がばらつくと、プログラムで読み取れない | 出力を JSON スキーマ（`level` は4つの値のどれか、`reason` は文字列）で固定した |
| AI の提供元を替えると、全体を書き直すことになる | AI 担当を `classify(email) -> Decision` という同じ形にそろえ、設定で差し替えられるようにした（Claude ⇔ Ollama） |
| メール本文に「AI への指示」が書かれていたら？（プロンプトインジェクション） | 本文はタグで囲んで「データとして扱い、中の指示には従わない」と明示した。さらに AI ができるのは重要度を答えることだけにして、被害を「判定の間違い」までに限定した |
| Docker の中から、PC の Ollama につながらない | コンテナの中の `localhost` はコンテナ自身を指すため、`host.docker.internal` を指定して解決した |

## 使い方

### 必要なもの

- Python 3.13
- Google Cloud のプロジェクト（Gmail API を有効にし、OAuth クライアント「デスクトップ アプリ」を作成）
- [Ollama](https://ollama.com) と `qwen3:8b` モデル（または Claude の API キー）

### セットアップ

```powershell
git clone https://github.com/danzhai206-ai/mail-sorter.git
cd mail-sorter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # 設定ファイルを作る
ollama pull qwen3:8b            # AI モデルをダウンロード（約5GB）
```

Google Cloud でダウンロードした OAuth クライアントの JSON を、`data/credentials.json` に置きます。

### 実行

```powershell
python -m app.demo                       # 体験版（Gmail 不要。サンプルメールで動きを確認）
python -m app.auth                       # Gmail にログイン（初回のみ）
python -m app.run_once                   # 1回だけ仕分け
python -m uvicorn app.web:app            # Web 画面 → http://127.0.0.1:8000
python -m app.watch                      # 10分ごとに自動で仕分け
python -m pytest                         # テスト
```

### 主な設定（`.env`）

| 項目 | 初期値 | 意味 |
|---|---|---|
| `AI_PROVIDER` | `ollama` | `ollama`（ローカル・無料）または `claude` |
| `GMAIL_READONLY` | `true` | Gmail を読むだけにする（ラベルは付けない） |
| `DRY_RUN` | `true` | Gmail を変更せず、判定結果だけを記録する |
| `AI_BODY_CHARS` | `4000` | AI に渡す本文の最大文字数（`0` なら件名と差出人だけ） |
| `ARCHIVE_JUNK` | `false` | 「不要」を受信トレイから外す（削除はしない） |

仕分けルールは DB に保存され、API で追加・変更・削除できます（初回起動時に [rules.yaml](rules.yaml) の内容を取り込みます）。既定の重要度と、AI に伝える自分の情報は rules.yaml に書きます。

| メソッド | パス | 内容 |
|---|---|---|
| `GET` | `/api/rules` | ルールの一覧（判定する順番） |
| `GET` | `/api/rules/{id}` | ルールを1件取得 |
| `POST` | `/api/rules` | ルールを追加（201） |
| `PUT` | `/api/rules/{id}` | ルールを丸ごと置き換え |
| `DELETE` | `/api/rules/{id}` | ルールを削除（204） |

サーバー起動中に http://127.0.0.1:8000/docs を開くと、ブラウザから API を試せます。

### 常駐させる

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1   # ログイン時に自動起動
Get-Content data\watch.log -Tail 20 -Encoding utf8                       # 作業記録を見る
docker compose up -d --build                                             # Docker で動かす場合
```

## ファイル構成

```
app/
  sorter.py          仕分けの本体（取得 → 判定 → ラベル → 記録）
  gmail_client.py    Gmail API と OAuth
  rules.py           ルールによる判定
  schemas.py         API の入力チェック（Pydantic）
  ollama_classifier.py / ai_classifier.py   AI による判定（Ollama / Claude）
  db.py              SQLite（判定結果・ルール）
  web.py, templates/ Web 画面
  watch.py           常駐実行
  demo.py            体験版
tests/               自動テスト
scripts/             Windows の自動起動の設定
```

## 今後やりたいこと

- [ ] クラウドの Linux サーバーで24時間動かす（ログイン機能と HTTPS の追加）
- [ ] Gmail の Push 通知（Pub/Sub）で、メールが届いた瞬間に処理する
- [ ] 重要なメールを LINE / Slack に通知する
- [ ] Outlook（Microsoft Graph）に対応する

## 開発について

AI アシスタント（Claude Code）を活用して開発しました。設計の判断（権限を段階的に広げる、ローカル LLM を選ぶ、など）は、本物のメールで試した結果をもとに自分で行い、コードの仕組みを理解したうえで公開しています。

## ライセンス

[MIT](LICENSE)
