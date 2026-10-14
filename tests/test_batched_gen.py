"""Тесты на app.batched_gen."""

from __future__ import annotations

import asyncio

import pytest

from app.batched_gen import BatchedGenerator, parse_numbered_replies


class TestParseNumberedReplies:
    def test_basic_three_replies(self):
        text = "1. привет\n2. ок\n3. вау"
        out = parse_numbered_replies(text, 3)
        assert out == ["привет", "ок", "вау"]

    def test_single_line_inline(self):
        text = "1. привет 2. ок 3. вау"
        out = parse_numbered_replies(text, 3)
        assert out[0].startswith("привет")
        assert out[1].startswith("ок")
        assert out[2].startswith("вау")

    def test_paren_style(self):
        text = "1) первый\n2) второй"
        out = parse_numbered_replies(text, 2)
        assert out == ["первый", "второй"]

    def test_dash_bullets(self):
        text = "- a\n- b"
        out = parse_numbered_replies(text, 2)
        assert out == ["a", "b"]

    def test_less_than_expected_pads_empty(self):
        out = parse_numbered_replies("1. x", 3)
        assert out == ["x", "", ""]

    def test_more_than_expected_truncates(self):
        out = parse_numbered_replies("1. a\n2. b\n3. c\n4. d", 2)
        assert out == ["a", "b"]

    def test_empty_returns_empty_strings(self):
        out = parse_numbered_replies("", 3)
        assert out == ["", "", ""]


@pytest.mark.asyncio
class TestBatchedGenerator:
    async def test_disabled_falls_back_to_single(self):
        g = BatchedGenerator(enabled=False)

        async def single(p, s):
            return f"single:{p}"

        async def batch(p, s, n):
            raise AssertionError("batch should not be called when disabled")

        out = await g.request(
            "ch", "hello", "system", "ironic",
            single_gen=single, batch_gen=batch,
        )
        assert out == "single:hello"

    async def test_single_request_uses_single_gen(self):
        g = BatchedGenerator(enabled=True, wait_ms=10, max_batch=4)

        async def single(p, s):
            return f"single:{p}"

        async def batch(p, s, n):
            return "1. a\n2. b\n3. c"

        out = await g.request(
            "ch", "hello", "sys", "ironic",
            single_gen=single, batch_gen=batch,
        )
        assert out == "single:hello"

    async def test_two_requests_batch_together(self):
        g = BatchedGenerator(enabled=True, wait_ms=100, max_batch=4)

        called = {"single": 0, "batch": 0}

        async def single(p, s):
            called["single"] += 1
            return "should_not_be_used"

        async def batch(p, s, n):
            called["batch"] += 1
            return "\n".join(f"{i+1}. answer{i}" for i in range(n))

        async def caller(prompt, hint):
            return await g.request(
                "ch", prompt, "sys", hint,
                single_gen=single, batch_gen=batch,
            )

        out1, out2 = await asyncio.gather(
            caller("p1", "ironic"),
            caller("p2", "calm"),
        )
        assert called["batch"] == 1
        assert called["single"] == 0
        assert "answer" in out1
        assert "answer" in out2
        assert out1 != out2

    async def test_max_batch_triggers_immediate_flush(self):
        g = BatchedGenerator(enabled=True, wait_ms=10000, max_batch=2)
        # wait_ms огромный — flush должен случиться по достижению max_batch.

        async def single(p, s):
            return "single"

        async def batch(p, s, n):
            return "1. a\n2. b"

        out1, out2 = await asyncio.gather(
            g.request("ch", "p1", "", "", single_gen=single, batch_gen=batch),
            g.request("ch", "p2", "", "", single_gen=single, batch_gen=batch),
        )
        assert out1 in ("a", "b")
        assert out2 in ("a", "b")

    async def test_separate_buckets_independent(self):
        g = BatchedGenerator(enabled=True, wait_ms=50, max_batch=4)

        async def single(p, s):
            return f"s:{p}"

        async def batch(p, s, n):
            return "\n".join(f"{i+1}. x{i}" for i in range(n))

        # Каналы разные → каждый flush с одним запросом → single_gen.
        out_a, out_b = await asyncio.gather(
            g.request("a", "pa", "", "", single_gen=single, batch_gen=batch),
            g.request("b", "pb", "", "", single_gen=single, batch_gen=batch),
        )
        assert out_a == "s:pa"
        assert out_b == "s:pb"

    async def test_shutdown_unblocks_pending(self):
        g = BatchedGenerator(enabled=True, wait_ms=10000, max_batch=4)

        async def single(p, s):
            await asyncio.sleep(10)
            return "wont_happen"

        async def batch(p, s, n):
            return "1. a"

        task = asyncio.create_task(
            g.request("ch", "p", "", "", single_gen=single, batch_gen=batch)
        )
        await asyncio.sleep(0.05)
        await g.shutdown()
        with pytest.raises(RuntimeError):
            await task
