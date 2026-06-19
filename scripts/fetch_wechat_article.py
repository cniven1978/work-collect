#!/usr/bin/env python3
"""微信公众号文章抓取脚本

用例:
  python3 fetch_wechat_article.py https://mp.weixin.qq.com/s/xxxxx
  python3 fetch_wechat_article.py https://mp.weixin.qq.com/s/xxxxx --format markdown
  python3 fetch_wechat_article.py https://mp.weixin.qq.com/s/xxxxx --format json
  python3 fetch_wechat_article.py https://mp.weixin.qq.com/s/xxxxx --format markdown --output inbox/article.md
"""

import re
import json
import sys
import datetime
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def extract_metadata(html):
    meta = {}

    # 标题
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
    meta["title"] = m.group(1) if m else ""

    # 作者
    m = re.search(r'<meta\s+name="author"\s+content="([^"]*)"', html)
    meta["author"] = m.group(1) if m else ""

    # 公众号名
    m = re.search(r'class="wx_follow_nickname"[^>]*>([^<]+)', html)
    meta["mp_name"] = m.group(1).strip() if m else ""

    # 描述
    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
    meta["description"] = m.group(1) if m else ""

    # 发布时间
    m = re.search(r'\bvar\s+ct\s*=\s*["\']?(\d+)["\']?', html)
    if not m:
        m = re.search(r'\bct\s*=\s*["\'](\d+)["\']', html)
    if m:
        meta["date"] = datetime.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M:%S")
    else:
        meta["date"] = ""

    # __biz
    m = re.search(r'biz:\s*["\']([^"\']+)["\']', html)
    if not m:
        m = re.search(r'__biz["\']?\s*[:=]\s*["\']([^"\']+)["\']', html)
    meta["biz"] = m.group(1) if m else ""

    # show_type
    m = re.search(r'item_show_type\s*=\s*["\'](\d+)["\']', html)
    meta["show_type"] = m.group(1) if m else "0"

    return meta


def extract_content(html):
    """提取微信文章正文，返回 (正文HTML, 图片数)

    使用 div 深度配对精确定位 js_content 的闭合标签，
    避免尾部混入 JS 脚本等非正文内容。
    """
    js_pos = html.find('id="js_content"')
    if js_pos == -1:
        return "", 0

    tag_start = html.find('>', js_pos) + 1

    # 用 div 深度配对找 js_content 的闭合 </div>
    depth = 0
    i = js_pos
    close_pos = len(html)
    search_limit = min(len(html), js_pos + 500000)

    while i < search_limit:
        if html[i:i+5] == '<div ' or html[i:i+5] == '<div>':
            depth += 1
        elif html[i:i+6] == '</div>':
            depth -= 1
            if depth <= 0:
                close_pos = i
                break
        i += 1

    content_html = html[tag_start:close_pos]

    # 处理图片防盗链: data-src -> src
    img_count = len(re.findall(r'data-src=', content_html))
    content_html = re.sub(
        r'<img([^>]*?)data-src="([^"]*)"([^>]*?)>',
        lambda m: f'<img{m.group(1)}src="{m.group(2)}"{m.group(3)}>',
        content_html
    )

    # 处理 mpvoice 音频标签
    content_html = re.sub(
        r'<mpvoice[^>]*voice_encode_fileid="([^"]*)"[^>]*name="([^"]*)"[^>]*>',
        lambda m: f'<audio controls src="https://res.wx.qq.com/voice/getvoice?mediaid={m.group(1)}" title="{m.group(2)}" style="width:100%"/>',
        content_html
    )

    # 处理视频 iframe
    content_html = re.sub(
        r'<iframe[^>]*class="video_iframe"[^>]*data-src="[^"]*vid=(\w+)[^"]*"[^>]*>',
        lambda m: f'<iframe src="https://v.qq.com/txp/iframe/player.html?vid={m.group(1)}&autoplay=false" width="677" height="380" allowfullscreen></iframe>',
        content_html
    )

    return content_html, img_count


def html_to_text(html_content):
    """将 HTML 转为纯文本"""
    text = re.sub(r'<br\s*/?>', '\n', html_content)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def to_markdown(meta, content_html, url=""):
    """生成标准 Markdown 格式文章"""
    text = html_to_text(content_html)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    char_count = len(text)
    reading_time = max(1, char_count // 500)

    original_url = url or "待补充"

    md = f"""---
title: {meta['title']}
source: 微信公众号
author: {meta['author']}
date: {meta['date']}
original_url: {original_url}
collected_at: {now}
tags: []
category: 待分类
reading_time: {reading_time}分钟
---

# {meta['title']}

## 摘要

[待填写：不超过1000字的自主摘要]

## 正文

{text}

### 备注

[如有整理说明或存疑处，在此标注]
"""
    return md


def main():
    if len(sys.argv) < 2:
        print("用法: python3 fetch_wechat_article.py <微信文章URL> [--format json|markdown] [--output FILE]")
        sys.exit(1)

    url = sys.argv[1]
    fmt = "json"
    output_file = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--format" and i + 1 < len(sys.argv):
            fmt = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--output" and i + 1 < len(sys.argv):
            output_file = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    print(f"正在抓取: {url}", file=sys.stderr)
    html = fetch_html(url)
    print(f"页面大小: {len(html)} 字符", file=sys.stderr)

    meta = extract_metadata(html)
    content_html, img_count = extract_content(html)

    print(f"标题: {meta['title']}", file=sys.stderr)
    print(f"作者: {meta['author']}", file=sys.stderr)
    print(f"公众号: {meta['mp_name']}", file=sys.stderr)
    print(f"发布时间: {meta['date']}", file=sys.stderr)
    print(f"图片数: {img_count}", file=sys.stderr)

    if fmt == "json":
        result = {**meta, "images_count": img_count, "content_length": len(html_to_text(content_html))}
        output = json.dumps(result, ensure_ascii=False, indent=2)
    elif fmt == "markdown":
        output = to_markdown(meta, content_html, url)
    else:
        print(f"未知格式: {fmt}", file=sys.stderr)
        sys.exit(1)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"✅ 已保存: {output_file} ({len(output)} 字符)", file=sys.stderr)
    else:
        sys.stdout.buffer.write(output.encode("utf-8"))


if __name__ == "__main__":
    main()
