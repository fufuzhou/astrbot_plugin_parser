"""Run the real handler with fake events, without importing the AstrBot runtime."""
import ast
import asyncio
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


class Plain:
    def __init__(self, text):
        self.text = text


class OtherSegment:
    pass


class Event:
    def __init__(self, text, group=10, sender=100):
        self.message_str = text
        self.unified_msg_origin = f'group:{group}'
        self.message_obj = SimpleNamespace(raw_message={
            'message_id': 1, 'time': 60, 'self_id': 2,
            'group_id': group, 'user_id': sender,
        })
        self.bot = object()

    def get_messages(self):
        return [Plain(self.message_str)]

    def get_self_id(self):
        return '2'

    def is_private_chat(self):
        return False


@pytest.fixture
def plugin():
    root = Path(__file__).resolve().parents[1]
    source = ast.parse((root / 'main.py').read_text(encoding='utf-8-sig'))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in {'on_message', '_get_debounce_session_key'}]
    for method in methods:
        method.decorator_list = []
    debounce_tree = ast.parse((root / 'core/debounce.py').read_text(encoding='utf-8-sig'))
    debounce = next(n for n in debounce_tree.body if isinstance(n, ast.ClassDef))
    from core.arbiter import ArbiterContext
    env = dict(re=re, time=time, PluginConfig=object, AstrMessageEvent=Event,
               AiocqhttpMessageEvent=Event, At=OtherSegment, Json=OtherSegment,
               Reply=OtherSegment, Plain=Plain, ArbiterContext=ArbiterContext,
               logger=SimpleNamespace(debug=lambda *a: None, warning=lambda *a: None),
               TipException=type('TipException', (Exception,), {}),
               ParseException=type('ParseException', (Exception,), {}))
    exec(compile(ast.Module(body=[debounce, *methods], type_ignores=[]), str(root/'main.py'), 'exec'), env)
    harness = type('Harness', (), {m.name: env[m.name] for m in methods})
    obj = harness()
    obj.cfg = SimpleNamespace(whitelist=[], blacklist=[], require_at_in_group=False,
                              enable_reply_parse=False, debounce_interval=300)
    obj.debouncer = env['Debouncer'](obj.cfg)
    obj.calls = []
    obj.wins = False

    async def compete(**kwargs):
        obj.calls.append('arbitrate')
        await asyncio.sleep(0)
        return obj.wins

    async def parse(*args):
        obj.calls.append('parse')
        return SimpleNamespace(get_resource_id=lambda: 'resource-x')

    async def send(*args):
        obj.calls.append('send')

    obj.arbiter = SimpleNamespace(compete=compete)
    obj.sender = SimpleNamespace(send_parse_result=send)
    obj.parser_map = {'example': SimpleNamespace(parse=parse)}
    obj.key_pattern_list = [('example', re.compile(r'https://example.com/\w+'))]
    return obj


@pytest.mark.asyncio
async def test_loser_ignores_other_bots_output_containing_original_link(plugin):
    await plugin.on_message(Event('https://example.com/x'))
    plugin.wins = True
    await plugin.on_message(Event('解析结果 链接: https://example.com/x 标题: test', sender=1))
    assert plugin.calls == ['arbitrate']


@pytest.mark.asyncio
async def test_winner_and_new_group_still_parse(plugin):
    plugin.wins = True
    await plugin.on_message(Event('https://example.com/x'))
    await plugin.on_message(Event('https://example.com/x', group=20))
    assert plugin.calls == ['arbitrate', 'parse', 'send'] * 2


@pytest.mark.asyncio
async def test_concurrent_repeat_is_blocked_before_arbitration_finishes(plugin):
    await asyncio.gather(plugin.on_message(Event('https://example.com/x')),
                         plugin.on_message(Event('https://example.com/x', sender=1)))
    assert plugin.calls == ['arbitrate']


@pytest.mark.asyncio
async def test_different_link_is_not_blocked(plugin):
    await plugin.on_message(Event('https://example.com/x'))
    await plugin.on_message(Event('https://example.com/y'))
    assert plugin.calls == ['arbitrate', 'arbitrate']


@pytest.mark.asyncio
async def test_expired_link_can_retry(plugin):
    await plugin.on_message(Event('https://example.com/x'))
    plugin.debouncer._cache['group:10']['link:https://example.com/x'] -= 301
    plugin.wins = True
    await plugin.on_message(Event('https://example.com/x'))
    assert plugin.calls == ['arbitrate', 'arbitrate', 'parse', 'send']


@pytest.mark.asyncio
async def test_disabling_debounce_explicitly_disables_echo_guard(plugin):
    plugin.debouncer.interval = 0
    await plugin.on_message(Event('https://example.com/x'))
    await plugin.on_message(Event('https://example.com/x', sender=1))
    assert plugin.calls == ['arbitrate', 'arbitrate']
