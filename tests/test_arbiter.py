import asyncio
from collections import deque

import pytest

from core.arbiter import ArbiterContext, EmojiLikeArbiter


class Bot:
    def __init__(self, users, feedback, fail_mark=None):
        self.responses = {289: deque(users), 124: deque(feedback)}
        self.marks = []
        self.fail_mark = fail_mark

    async def fetch_emoji_like(self, **kwargs):
        value = self.responses[int(kwargs['emoji_id'])].popleft()
        if isinstance(value, Exception):
            raise value
        if isinstance(value, list):
            return {'emojiLikesList': [{'tinyId': str(uid)} for uid in value]}
        return value

    async def set_msg_emoji_like(self, **kwargs):
        emoji = kwargs['emoji_id']
        self.marks.append(emoji)
        if emoji == self.fail_mark:
            return {'status': 'failed', 'retcode': 1200}
        return {}


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    original = asyncio.sleep

    async def yield_once(_):
        await original(0)

    monkeypatch.setattr('core.arbiter.asyncio.sleep', yield_once)


def ctx(uid=1):
    return ArbiterContext(123, 60, uid)


@pytest.mark.asyncio
async def test_single_bot_must_confirm_itself_twice():
    bot = Bot([[], [1], [1], [1], [1]], [[], [], [1], [1]])
    assert await EmojiLikeArbiter().compete(bot, ctx())
    assert bot.marks == [289, 124]
    assert all(not queue for queue in bot.responses.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [None, {}, {'status': 'failed', 'emojiLikesList': []},
    {'emojiLikesList': None}, {'emojiLikesList': [{'tinyId': 'bad'}]},
    {'emojiLikesList': [{'tinyId': '0'}]}, list(range(1, 21)), TimeoutError()])
async def test_unknown_or_truncated_initial_query_never_registers(response):
    bot = Bot([response], [])
    assert not await EmojiLikeArbiter().compete(bot, ctx())
    assert bot.marks == []


@pytest.mark.asyncio
@pytest.mark.parametrize('a_result', [[], TimeoutError(), [1]])
async def test_reported_double_winner_paths_only_allow_b(a_result):
    # A sees only itself (then the full set), an empty list, or a query failure.
    a = Bot([[], a_result, [1, 2]], [[]])
    b = Bot([[], [1, 2], [1, 2], [1, 2], [1, 2]], [[], [], [2], [2]])
    results = await asyncio.gather(
        EmojiLikeArbiter().compete(a, ctx(1)),
        EmojiLikeArbiter().compete(b, ctx(2)),
    )
    assert results == [False, True]
    assert 124 not in a.marks


@pytest.mark.asyncio
@pytest.mark.parametrize('feedback', [[], [2], [1, 2], TimeoutError()])
async def test_confirmation_requires_exclusively_self(feedback):
    bot = Bot([[], [1], [1], [1]], [[], [], feedback])
    assert not await EmojiLikeArbiter().compete(bot, ctx())


@pytest.mark.asyncio
async def test_membership_change_after_claim_aborts():
    bot = Bot([[], [1], [1], [1, 2]], [[], []])
    assert not await EmojiLikeArbiter().compete(bot, ctx())


@pytest.mark.asyncio
async def test_second_confirmation_can_veto_first():
    bot = Bot([[], [1], [1], [1], [1]], [[], [], [1], [1, 2]])
    assert not await EmojiLikeArbiter().compete(bot, ctx())


@pytest.mark.asyncio
async def test_nonwinner_does_not_promote_itself_on_missing_feedback():
    bot = Bot([[], [1, 2], [1, 2]], [[]])
    assert not await EmojiLikeArbiter().compete(bot, ctx(1))
    assert bot.marks == [289]


@pytest.mark.asyncio
@pytest.mark.parametrize('emoji', [289, 124])
async def test_mark_action_failure_aborts(emoji):
    bot = Bot([[], [1], [1]], [[], []], fail_mark=emoji)
    assert not await EmojiLikeArbiter().compete(bot, ctx())


@pytest.mark.asyncio
async def test_concurrent_duplicate_events_share_local_reservation():
    arbiter = EmojiLikeArbiter()
    bot = Bot([[], [1], [1], [1], [1]], [[], [], [1], [1]])
    results = await asyncio.gather(arbiter.compete(bot, ctx()), arbiter.compete(bot, ctx()))
    assert sorted(results) == [False, True]
    assert bot.marks == [289, 124]


@pytest.mark.asyncio
async def test_api_timeout_is_bounded():
    class HangingBot:
        async def fetch_emoji_like(self, **kwargs):
            await asyncio.Event().wait()
    arbiter = EmojiLikeArbiter()
    arbiter._API_TIMEOUT_SEC = 0.01
    assert not await asyncio.wait_for(arbiter.compete(HangingBot(), ctx()), 1)


@pytest.mark.asyncio
async def test_existing_feedback_blocks_new_registration():
    bot = Bot([[]], [[2]])
    assert not await EmojiLikeArbiter().compete(bot, ctx())
    assert not bot.marks


@pytest.mark.asyncio
async def test_registration_samples_share_window_and_total_wait_is_1_4(monkeypatch):
    from types import SimpleNamespace
    now = [0.0]
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr('core.arbiter.time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr('core.arbiter.asyncio.sleep', sleep)
    bot = Bot([[], [1], [1], [1], [1]], [[], [], [1], [1]])
    assert await EmojiLikeArbiter().compete(bot, ctx())
    assert waits == pytest.approx([0.7, 0.3, 0.2, 0.2])
    assert sum(waits) == pytest.approx(1.4)
