"""Exercise the real sender class with lightweight AstrBot component doubles."""
import ast
import asyncio
import itertools
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core import data


class Plain:
    def __init__(self, text):
        self.text = text


class Image:
    pass


class Event:
    def __init__(self, chain):
        self.chain = chain
        self.sent = []
        # Deliberately not the original text: the guard must use the full chain.
        self.message_str = 'https://example.com/x'

    def get_messages(self):
        return self.chain

    def chain_result(self, segments):
        return segments

    async def send(self, segments):
        self.sent.append(segments)


@pytest.fixture
def sender():
    path = Path(__file__).resolve().parents[1] / 'core/sender.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    future = ast.parse('from __future__ import annotations').body[0]
    env = dict(vars(data), Plain=Plain, Image=Image, Path=Path,
               Task=asyncio.Task, chain=itertools.chain, re=re,
               logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                      error=lambda *a: None))
    exec(compile(ast.Module(body=[future, cls], type_ignores=[]), str(path), 'exec'), env)
    renderer = SimpleNamespace(render_card=AsyncMock())
    return env['MessageSender'](SimpleNamespace(single_heavy_render_card=False,
                                               forward_threshold=99), renderer)


@pytest.fixture
def result():
    return data.ParseResult(platform=data.Platform('test', '测试平台'),
                            url='https://example.com/x', title='标题', text='正文')


@pytest.mark.asyncio
@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
async def test_equal_full_text_stops_all_sends_and_fallback(sender, result, newline):
    output = sender._build_text_summary(result)
    event = Event([Plain('  ' + output.replace('\n', newline) + '\n')])
    sender._send_group = AsyncMock(side_effect=AssertionError('must not send'))
    sender._build_text_fallback = lambda result: pytest.fail('must not fall back')
    await sender.send_parse_result(event, result)
    assert event.sent == []
    sender.renderer.render_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_split_plain_segments_compare_as_complete_message(sender, result):
    result.contents = [data.TextContent('补充内容')]
    full = sender._build_text_summary(result) + '补充内容'
    event = Event([Plain(full[:10]), Plain(full[10:])])
    await sender.send_parse_result(event, result)
    assert event.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['link_only', 'short_link', 'prefix', 'changed_title',
                                 'internal_space', 'missing_text_content', 'empty'])
async def test_different_text_is_sent(sender, result, kind):
    full = sender._build_text_summary(result)
    inputs = {
        'link_only': result.url,
        'short_link': 'https://short.example/x',
        'prefix': '请解析：' + full,
        'changed_title': full.replace('标题: 标题', '标题: 另一个标题'),
        'internal_space': full.replace('标题: 标题', '标题:  标题'),
        'missing_text_content': full,
        'empty': '',
    }
    if kind == 'missing_text_content':
        result.contents = [data.TextContent('新的补充内容')]
    event = Event([Plain(inputs[kind])])
    await sender.send_parse_result(event, result)
    assert len(event.sent) == 1
    assert ''.join(seg.text for seg in event.sent[0]) == full + (
        '新的补充内容' if kind == 'missing_text_content' else '')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['input_image', 'output_image', 'output_video',
                                  'force_merge', 'render_card', 'multiple_groups'])
async def test_media_and_structured_output_bypass_text_guard(sender, result, case):
    chain = [Plain(sender._build_text_summary(result))]
    if case == 'input_image':
        chain.append(Image())
    elif case == 'output_image':
        result.contents = [data.ImageContent(Path('image.png'))]
    elif case == 'output_video':
        result.contents = [data.VideoContent(Path('video.mp4'))]
    elif case == 'force_merge':
        result.send_groups = [data.SendGroup(force_merge=True)]
    elif case == 'render_card':
        result.send_groups = [data.SendGroup(render_card=True)]
    else:
        result.send_groups = [data.SendGroup(), data.SendGroup()]
    # Verify normal dispatch remains reachable without requiring media IO here.
    sender._send_group = AsyncMock(return_value=True)
    await sender.send_parse_result(Event(chain), result)
    assert sender._send_group.await_count == (2 if case == 'multiple_groups' else 1)


@pytest.mark.asyncio
async def test_forward_threshold_bypasses_plain_text_comparison(sender, result):
    sender.cfg.forward_threshold = 1
    sender._send_group = AsyncMock(return_value=True)
    await sender.send_parse_result(Event([Plain(sender._build_text_summary(result))]), result)
    sender._send_group.assert_awaited_once()


@pytest.mark.asyncio
async def test_repost_is_part_of_full_comparison(sender, result):
    result.repost = data.ParseResult(platform=result.platform, text='转发正文')
    await sender.send_parse_result(Event([Plain(sender._build_text_summary(result))]), result)
    sender.renderer.render_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_fallback_still_runs_when_normal_send_fails(sender, result):
    sender._send_group = AsyncMock(return_value=False)
    event = Event([Plain(result.url)])
    await sender.send_parse_result(event, result)
    assert len(event.sent) == 1
    assert event.sent[0][0].text == result.header + '\n' + result.text
