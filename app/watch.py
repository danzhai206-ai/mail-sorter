"""一定間隔で仕分けを繰り返す（常駐用）。 実行: python -m app.watch

Ctrl+C で止まります。サーバーに置くときはこれを動かし続けます。
"""
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from . import config
from .sorter import run_once

log = logging.getLogger("watch")


def setup_logging() -> None:
    """作業記録を data/watch.log に残す（裏で動いていて画面が無いときも、あとで確認できる）。"""
    handlers = [RotatingFileHandler(config.DATA_DIR / "watch.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr:  # 画面（ターミナル）があるときは、画面にも出す
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


if __name__ == "__main__":
    setup_logging()
    log.info("%d分ごとに仕分けします（DRY_RUN=%s）", config.INTERVAL_MINUTES, config.DRY_RUN)
    while True:
        try:
            results = run_once()
            log.info("%d 件を仕分けしました", len(results))
        except Exception:
            # 1回失敗しても止まらず、次の回でもう一度試す
            log.exception("仕分け中にエラーが起きました")
        time.sleep(config.INTERVAL_MINUTES * 60)
