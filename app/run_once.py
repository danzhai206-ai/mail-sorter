"""1回だけ仕分けを実行する。 実行: python -m app.run_once"""
import logging

from . import config
from .sorter import can_modify, run_once

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not can_modify():
        print("※ お試しモード（DRY_RUN / GMAIL_READONLY）のため、Gmailは変更せず判定結果だけ記録します")
    results = run_once()
    print(f"{len(results)} 件を仕分けしました")
