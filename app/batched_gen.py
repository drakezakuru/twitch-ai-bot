"""Batched generation: один запрос → N стилизованных ответов.

Используется, когда на одном канале сидит несколько ботов и они все
готовятся писать в чат одновременно (auto-chat-тик или одинаковый
smart-trigger). Вместо N независимых LLM-запросов делаем один с
инструкцией «дай N разных по стилю ответов».

Алгоритм:
1. Бот вызывает ``request_batched(channel, prompt, system, n, style_hint)``.
2. Если включён ``BATCHED_GEN_ENABLED`` и в окне ``wait_ms`` подойдут
   ещё запросы — собираем их вместе.
3. По таймауту / при наборе ``max_batch`` — один запрос к AI с
   модифицированным prompt: «верни N ответов, формат: 1. ... 2. ...».
4. Парсим, раздаём по await-future каждому ожидающему.

Если фича выключена или количество < 2 — fallback на обычный путь.

Этот модуль умышленно НЕ привязан к ``ChatAnalyzer`` напрямую — его
можно вызывать из чего угодно. Координация cross-process требует
shared state (Redis/etc), что выходит за рамки v10.4.4. В рамках одного
процесса с несколькими ``BotManager`` — работает.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


_NUM_PREFIX_RE = re.compile(r"^\s*(?:\d+[\.\)\-:]\s*|[\-•]\s*)")


def parse_numbered_replies(text: str, expected_n: int) -> list[str]:
    """Парсит ответ от LLM в виде "1. ... 2. ... 3. ...".

    Возвращает список длины ``expected_n``. Если меньше — добиваем
    пустыми строками. Если больше — обрезаем.
    """
    if not text:
        return [""] * expected_n
    # Разбиваем по началу строки если она начинается с числа+разделителя.
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _NUM_PREFIX_RE.match(stripped):
            if current:
                chunks.append("\n".join(current).strip())
                current = []
            current.append(_NUM_PREFIX_RE.sub("", stripped, count=1))
        elif stripped:
            current.append(stripped)
    if current:
        chunks.append("\n".join(current).strip())
    # Если разбиение не дало ничего — может, ответ в одной строке без
    # переносов; попробуем разделить по "1. ... 2. ...".
    if len(chunks) < expected_n:
        parts = re.split(r"(?<=\D)\s+(?=\d+[\.\)\-:])", text.strip())
        if len(parts) > len(chunks):
            chunks = [_NUM_PREFIX_RE.sub("", p, count=1).strip() for p in parts]
    if len(chunks) >= expected_n:
        return chunks[:expected_n]
    return chunks + [""] * (expected_n - len(chunks))


@dataclass
class _PendingRequest:
    prompt: str
    system: str
    style_hint: str
    future: asyncio.Future


@dataclass
class BatchedGenerator:
    """Pool batched-gen запросов.

    Параметры:

    * ``wait_ms`` — сколько ждать «соседей» прежде чем триггерить
      запрос (200–500 мс — разумный диапазон).
    * ``max_batch`` — максимальный размер batch.
    """

    wait_ms: int = 300
    max_batch: int = 4
    enabled: bool = False

    _buckets: dict[str, list[_PendingRequest]] = field(default_factory=dict)
    _flush_tasks: dict[str, asyncio.Task] = field(default_factory=dict)

    def is_enabled(self) -> bool:
        return self.enabled and self.max_batch >= 2

    async def request(
        self,
        bucket_key: str,
        prompt: str,
        system: str,
        style_hint: str,
        *,
        single_gen: Callable[[str, str], Awaitable[str]],
        batch_gen: Callable[[str, str, int], Awaitable[str]],
    ) -> str:
        """Запросить генерацию. Если batched включён — кооперируемся,
        иначе fallback на ``single_gen``.

        ``single_gen(prompt, system) -> str``
        ``batch_gen(combined_prompt, system, n) -> str``  возвращает
        нумерованный список 1..n.
        """
        if not self.is_enabled():
            return await single_gen(prompt, system)

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        req = _PendingRequest(prompt=prompt, system=system, style_hint=style_hint, future=fut)
        bucket = self._buckets.setdefault(bucket_key, [])
        bucket.append(req)

        # Запустим (или поддержим) flush-task для бакета.
        if bucket_key not in self._flush_tasks:
            self._flush_tasks[bucket_key] = asyncio.create_task(
                self._flush_after_wait(bucket_key, single_gen, batch_gen)
            )

        # Если достигли max_batch — flush сразу.
        if len(bucket) >= self.max_batch:
            task = self._flush_tasks.pop(bucket_key, None)
            if task and not task.done():
                task.cancel()
            asyncio.create_task(self._flush(bucket_key, single_gen, batch_gen))

        return await fut

    async def _flush_after_wait(
        self,
        bucket_key: str,
        single_gen: Callable[[str, str], Awaitable[str]],
        batch_gen: Callable[[str, str, int], Awaitable[str]],
    ) -> None:
        try:
            await asyncio.sleep(self.wait_ms / 1000.0)
        except asyncio.CancelledError:
            return
        self._flush_tasks.pop(bucket_key, None)
        await self._flush(bucket_key, single_gen, batch_gen)

    async def _flush(
        self,
        bucket_key: str,
        single_gen: Callable[[str, str], Awaitable[str]],
        batch_gen: Callable[[str, str, int], Awaitable[str]],
    ) -> None:
        bucket = self._buckets.pop(bucket_key, [])
        if not bucket:
            return
        if len(bucket) == 1:
            req = bucket[0]
            try:
                text = await single_gen(req.prompt, req.system)
                if not req.future.done():
                    req.future.set_result(text)
            except Exception as exc:
                if not req.future.done():
                    req.future.set_exception(exc)
            return

        # Собираем «общий» промпт. Используем prompt первого (часто они
        # одинаковые), а стили — из style_hint каждого.
        first = bucket[0]
        styles = "\n".join(f"{i+1}. {r.style_hint or 'обычный зритель'}" for i, r in enumerate(bucket))
        merged_prompt = (
            f"{first.prompt}\n\n"
            f"Дай {len(bucket)} разных по стилю коротких ответа. "
            f"Формат: «1. <ответ>», «2. <ответ>», и т.д. Каждый — отдельная строка.\n"
            f"Стили:\n{styles}"
        )
        try:
            raw = await batch_gen(merged_prompt, first.system, len(bucket))
            parts = parse_numbered_replies(raw, len(bucket))
            for req, text in zip(bucket, parts):
                if not req.future.done():
                    req.future.set_result(text.strip())
        except Exception as exc:
            logger.warning("batched_gen flush error: %s", exc)
            for req in bucket:
                if not req.future.done():
                    req.future.set_exception(exc)

    async def shutdown(self) -> None:
        for task in list(self._flush_tasks.values()):
            task.cancel()
        self._flush_tasks.clear()
        # Откатим pending future в exception чтобы не подвисли.
        for bucket in list(self._buckets.values()):
            for req in bucket:
                if not req.future.done():
                    req.future.set_exception(RuntimeError("batched_gen shutdown"))
        self._buckets.clear()


__all__ = ["BatchedGenerator", "parse_numbered_replies"]
