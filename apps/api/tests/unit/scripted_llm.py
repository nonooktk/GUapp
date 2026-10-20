"""台本つきの LLM アダプタ（P2 追補d テスト設計 1 章 #1・DS-DEC-105）。

`app.dependency_overrides[get_llm_adapter]` で差し替えて使う。台本は呼び出し順に 1 つずつ消費し、
足りなくなったら最後の 1 つを繰り返す。台本の中身は、返す出力・投げる例外・遅延・トークン数。
受け取った `LLMRequest` をすべて `requests` に記録する（固定指示・資料・履歴・質問の確認用）。
実際の LLM・ネットワークは使わない。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from app.adapters.llm import LLMError, LLMRequest, LLMResult
from app.schemas.chat import ChatLLMItem, ChatLLMOutput


@dataclass(frozen=True)
class Step:
    """台本の 1 回分。`error` があれば投げ、無ければ `output` を返す。`delay` は秒。"""

    output: ChatLLMOutput | None = None
    error: BaseException | None = None
    delay: float = 0.0
    input_tokens: int | None = 123
    output_tokens: int | None = 45


def out(
    intent: str = "recommend",
    message: str = "条件に合う商品をお選びしました。",
    ids: Sequence[int] = (),
    reason: str = "使いやすい一枚です。",
) -> ChatLLMOutput:
    """LLM の出力（付録 B）を作る。`ids` の各 ID に同じ `reason` を付ける。"""
    return ChatLLMOutput(
        intent=intent,  # type: ignore[arg-type]
        message=message,
        items=[ChatLLMItem(product_id=i, reason=reason) for i in ids],
    )


def fail(kind: str) -> Step:
    return Step(error=LLMError(kind))  # type: ignore[arg-type]


class ScriptedLLMAdapter:
    available = True
    model = "scripted-model"

    def __init__(self, *script: Step | ChatLLMOutput | BaseException, name: str = "openai") -> None:
        self.name = name  # type: ignore[assignment]
        self._script: list[Step] = [
            s
            if isinstance(s, Step)
            else Step(error=s)
            if isinstance(s, BaseException)
            else Step(output=s)
            for s in (script or (out("out_of_scope", ""),))
        ]
        self.requests: list[LLMRequest] = []
        self.calls = 0
        self.inflight = 0
        self.max_inflight = 0

    async def generate(self, request: LLMRequest) -> LLMResult:
        step = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        self.requests.append(request)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if step.delay:
                await asyncio.sleep(step.delay)
            if step.error is not None:
                raise step.error
            assert step.output is not None
            return LLMResult(
                output=step.output,
                model=self.model,
                input_tokens=step.input_tokens,
                output_tokens=step.output_tokens,
            )
        finally:
            self.inflight -= 1
