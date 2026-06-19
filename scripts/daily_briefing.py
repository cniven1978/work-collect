#!/usr/bin/env python3
"""每日简报生成脚本

从 subscriptions.json 读取订阅源，逐个获取最新内容，生成简报。
支持 website（直接爬取）和 wechat（通过 RSSHub）两种类型。

用例:
  python3 daily_briefing.py
  python3 daily_briefing.py --workspace /path/to/work-collect
"""

import json
import sys
import os
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_INTERVAL = 30  # 秒，防反爬


def load_subscriptions(workspace):
    path = os.path.join(workspace, "subscriptions.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_content_index(workspace):
    path = os.path.join(workspace, "content_index.json")
    if not os.path.exists(path):
        return {"articles": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_rsshub_available(rsshub_base):
    """检查 RSSHub 是否可用"""
    try:
        req = urllib.request.Request(rsshub_base, headers={"User-Agent": UA})
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def fetch_rss(rss_url):
    """获取并解析 RSS feed"""
    # 确保中文 URL 被正确编码
    parsed = urllib.parse.urlparse(rss_url)
    # 对 path 部分做 quote（保留 / 和 ASCII 字符）
    encoded_path = urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;=")
    encoded_url = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        encoded_path,
        parsed.params,
        parsed.query,
        parsed.fragment
    ))

    req = urllib.request.Request(encoded_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")

    root = ET.fromstring(data)
    items = []
    for item in root.iter("item"):
        entry = {}
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        date_el = item.find("pubDate")

        entry["title"] = title_el.text if title_el is not None else ""
        entry["link"] = link_el.text if link_el is not None else ""
        entry["description"] = (desc_el.text or "")[:200] if desc_el is not None else ""
        entry["pubDate"] = date_el.text if date_el is not None else ""
        items.append(entry)

    return items


def fetch_website(url):
    """简单爬取网站首页获取最新文章标题（需根据具体网站适配）"""
    return [{"title": "待解析", "link": url, "description": "网站类型需 Agent 按具体结构解析", "pubDate": ""}]


def is_duplicate(article_url, content_index):
    """检查文章是否已收录"""
    for a in content_index.get("articles", []):
        if article_url and article_url in a.get("original_url", ""):
            return True
    return False


def is_valid_rss_url(url):
    """检查 RSS URL 是否有效（非空、非占位符）"""
    if not url:
        return False
    if "待补充" in url:
        return False
    if not url.startswith("http"):
        return False
    return True


def generate_briefing(workspace, subs, content_index, rsshub_available):
    """生成每日简报"""
    rsshub_base = subs.get("rsshub_base", "http://localhost:1200")
    briefing_items = []

    for source in subs.get("sources", []):
        if source.get("status") != "active":
            continue

        stype = source.get("type", "website")
        name = source.get("name", "未知")

        try:
            if stype == "wechat":
                if not rsshub_available:
                    print(f"  ⏭️ {name}: RSSHub 不可用，跳过", file=sys.stderr)
                    continue

                rss_url = source.get("rss_url", "")
                if not is_valid_rss_url(rss_url):
                    print(f"  ⏭️ {name}: rss_url 未配置（含占位符），跳过", file=sys.stderr)
                    continue

                # 替换 rsshub_base 占位符
                rss_url = rss_url.replace("http://localhost:1200", rsshub_base)

                print(f"  📡 获取 RSS: {name}", file=sys.stderr)
                items = fetch_rss(rss_url)

                for item in items[:5]:
                    if not is_duplicate(item.get("link", ""), content_index):
                        briefing_items.append({
                            "source_name": name,
                            "source_type": "wechat",
                            **item,
                        })

            elif stype == "website":
                url = source.get("url", "")
                if not url:
                    continue
                print(f"  🌐 爬取网站: {name}", file=sys.stderr)
                items = fetch_website(url)
                for item in items[:5]:
                    briefing_items.append({
                        "source_name": name,
                        "source_type": "website",
                        **item,
                    })

        except Exception as e:
            print(f"  ❌ {name}: 抓取失败 - {e}", file=sys.stderr)
            briefing_items.append({
                "source_name": name,
                "source_type": stype,
                "title": f"[抓取失败] {name}",
                "link": "",
                "description": str(e),
                "pubDate": "",
            })

    return briefing_items


def save_briefing(workspace, items):
    """保存简报为 Markdown"""
    today = datetime.date.today().isoformat()
    briefings_dir = os.path.join(workspace, "briefings")
    os.makedirs(briefings_dir, exist_ok=True)
    filepath = os.path.join(briefings_dir, f"{today}.md")

    lines = [f"# 每日简报 {today}\n"]

    if not items:
        lines.append("今日无新内容。\n")
    else:
        for i, item in enumerate(items, 1):
            lines.append(f"### {i}. {item.get('title', '无标题')}\n")
            lines.append(f"- **来源**: {item.get('source_name', '未知')} ({item.get('source_type', '')})")
            if item.get("pubDate"):
                lines.append(f"- **时间**: {item['pubDate']}")
            if item.get("description"):
                lines.append(f"- **摘要**: {item['description']}")
            if item.get("link"):
                lines.append(f"- **链接**: {item['link']}")
            lines.append("")

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


def main():
    workspace = os.environ.get("WORKSPACE", "/workspace/work-collect")

    if "--workspace" in sys.argv:
        idx = sys.argv.index("--workspace")
        if idx + 1 < len(sys.argv):
            workspace = sys.argv[idx + 1]

    print(f"=== 每日简报生成 ===", file=sys.stderr)
    print(f"工作区: {workspace}", file=sys.stderr)

    subs = load_subscriptions(workspace)
    rsshub_base = subs.get("rsshub_base", "http://localhost:1200")

    # 检查 RSSHub 可用性
    has_wechat = any(
        s.get("type") == "wechat" and s.get("status") == "active"
        for s in subs.get("sources", [])
    )
    rsshub_available = False
    if has_wechat:
        rsshub_available = is_rsshub_available(rsshub_base)
        if rsshub_available:
            print(f"✅ RSSHub 可用: {rsshub_base}", file=sys.stderr)
        else:
            print(f"⚠️ RSSHub 不可用: {rsshub_base}", file=sys.stderr)
            print(f"   微信公众号源将跳过。部署方法: scripts/setup_rsshub.sh install", file=sys.stderr)

    content_index = load_content_index(workspace)

    print(f"\n📡 开始抓取订阅源...", file=sys.stderr)
    items = generate_briefing(workspace, subs, content_index, rsshub_available)

    print(f"\n📝 生成简报: {len(items)} 条新内容", file=sys.stderr)
    filepath = save_briefing(workspace, items)
    print(f"✅ 简报已保存: {filepath}", file=sys.stderr)

    # 输出简报内容
    with open(filepath, "r", encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    main()
