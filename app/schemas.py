"""APIでやり取りするデータの形（入力チェックのルール）。

FastAPI は、ここに書いた形とリクエストの中身を自動で照らし合わせます。
合わなければ、関数が呼ばれる前に 422（入力が不正）のエラーを返してくれます。
"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .rules import CONDITION_KEYS

Level = Literal["high", "medium", "low", "junk"]
Word = Annotated[str, Field(min_length=1, max_length=200)]  # 空文字は「全部に一致」してしまうので禁止


class RuleIn(BaseModel):
    """ルールを作る・変えるときに送る中身。"""
    name: str = Field(min_length=1, max_length=100)
    level: Level
    position: int | None = Field(default=None, ge=1)  # 省略すると、作成時は最後・更新時は今のまま
    enabled: bool = True
    from_contains: list[Word] | None = None
    subject_contains: list[Word] | None = None
    body_contains: list[Word] | None = None
    gmail_label: list[Word] | None = None
    has_list_unsubscribe: bool | None = None

    def conditions(self) -> dict:
        """指定された条件だけを辞書にして返す（DBの conditions 列に入れる中身）。"""
        return {k: v for k in CONDITION_KEYS if (v := getattr(self, k)) not in (None, [])}

    @model_validator(mode="after")
    def _need_condition(self):
        if not self.conditions():
            raise ValueError("条件を1つ以上指定してください")
        return self


class RuleOut(RuleIn):
    """APIが返すルール。DBが振った番号（id）と、確定した順番が付く。"""
    id: int
    position: int
