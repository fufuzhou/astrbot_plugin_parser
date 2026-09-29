"""Run image collection and result assembly without the AstrBot runtime."""
import ast
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from core.data import Platform


TARGET = 'https://wx2.sinaimg.cn/large/00336wGHly1ihl12bt8b9j613p0u0wma02.jpg'
WRAPPER = ('https://weibo.cn/sinaurl?u=https%3A%2F%2Fwx2.sinaimg.cn%2Flarge%2F'
           '00336wGHly1ihl12bt8b9j613p0u0wma02.jpg')
ICON = 'https://h5.sinaimg.cn/upload/2015/01/21/20/timeline_card_small_photo_default.png'


@pytest.fixture
def weibo():
    source = Path(__file__).resolve().parents[1] / 'core/parsers/weibo.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    selected = []
    methods = {'build_weibo_data', '_dedupe_urls', '_dedupe_image_urls',
               '_image_dedupe_key', '_collect_short_links', '_normalize_url',
               '_is_short_link', '_is_direct_image_url'}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_is_non_content_image_url':
            selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == 'WeiboData':
            selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == 'WeiBoParser':
            node.body = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and n.name in methods]
            selected.append(node)
    future = ast.parse('from __future__ import annotations').body[0]
    env = dict(Struct=SimpleNamespace, BaseParser=object, Platform=Platform,
               sub=re.sub, findall=re.findall, urlparse=urlparse)
    exec(compile(ast.Module(body=[future, *selected], type_ignores=[]), str(source), 'exec'), env)
    parser = env['WeiBoParser']()
    parser.create_image_contents = lambda urls: list(urls)
    parser.create_author = lambda name, avatar: name
    parser.result = lambda **kwargs: SimpleNamespace(**kwargs)

    async def expand(links):
        return [TARGET if link == WRAPPER else link for link in links]

    parser._expand_short_links = expand

    def make(text, **kwargs):
        return env['WeiboData'](user=SimpleNamespace(id=2794283127, screen_name='author',
                                  profile_image_url='https://example.com/avatar.jpg'),
                               text=text, bid='RkpBwqHs9',
                               created_at='Wed Sep 30 10:00:00 +0800 2026', **kwargs)
    return parser, make


@pytest.mark.asyncio
async def test_reported_weibo_redirect_image_only_emitted_once(weibo):
    parser, make = weibo
    data = make(f'<a href="{WRAPPER}"><img src="{ICON}">查看图片</a>')
    result = await parser.build_weibo_data(data)
    assert result.contents == [TARGET]


def test_wrapper_is_not_a_direct_image_candidate(weibo):
    _, make = weibo
    assert make(f'<a href="{WRAPPER}">查看图片</a>').image_urls == []


@pytest.mark.asyncio
async def test_real_image_plus_wrapper_is_deduplicated_after_expansion(weibo):
    parser, make = weibo
    result = await parser.build_weibo_data(make(f'<img src="{TARGET}"><a href="{WRAPPER}">图</a>'))
    assert result.contents == [TARGET]


@pytest.mark.asyncio
async def test_retweet_pictures_are_preserved(weibo):
    parser, make = weibo
    repost = make('', pics=[SimpleNamespace(large=SimpleNamespace(url='https://wx1.sinaimg.cn/mw2000/other.jpg'))])
    result = await parser.build_weibo_data(make(f'<a href="{WRAPPER}">图</a>', retweeted_status=repost))
    assert result.contents == [TARGET]
    assert result.repost.contents == ['https://wx1.sinaimg.cn/mw2000/other.jpg']


@pytest.mark.parametrize('url', ['https://wx1.sinaimg.cn/large/a.jpg',
    'https://wx1.sinaimg.cn/large/a.png?quality=90&amp;foo=1',
    'https://wx1.sinaimg.cn/large/a.webp?x=1'])
def test_direct_images_are_kept(weibo, url):
    _, make = weibo
    assert make(f'<img src="{url}">').image_urls == [url.replace('&amp;', '&')]


def test_emoji_and_card_icons_still_filtered(weibo):
    _, make = weibo
    assert make(f'<img src="{ICON}"><img src="https://face.t.sinajs.cn/a.png">').image_urls == []
