#!/usr/bin/env python3
"""每日简报生成脚本

从 subscriptions.json 读取订阅源，逐个获取最新内容，生成简报。
简报格式对标微信公众号「CGT 每日公众号文摘」样式：
  - 按分类分区：脑机接口 / 手术机器人 / 再生医学 / 其他重点
  - 每条：序号 · 摘录时间 + 标题 + 摘要 + 阅读原文链接

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
import re

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 分类体系
CATEGORY_EMOJI = {
    "脑机接口": "🧠",
    "手术机器人": "🤖",
    "再生医学": "🔬",
    "其他重点": "📌",
}

CATEGORY_ORDER = ["脑机接口", "手术机器人", "再生医学", "其他重点"]

# 分类关键词规则
CATEGORY_KEYWORDS = {
    "脑机接口": ["脑机", "BCI", "脑电", "神经接口", "脑控", "脑刺激", "DBS", "深部脑刺激",
                "帕金森", "神经调控", "脑机接口", "脑植入", "神经假体", "脑机协同",
                "脑电信号", "EEG", "皮层脑机", "脊髓刺激", "运动解码"],
    "手术机器人": ["手术机器人", "达芬奇", "机器人辅助", "微创手术", "外科机器人",
                  "腹腔镜机器", "骨科机器", "介入机器", "导航手术", "机器人手术",
                  "柔性机器人", "微创机器", "腔镜机器", "手术导航"],
    "再生医学": ["再生医学", "干细胞", "iPSC", "类器官", "间充质", "组织工程",
                "器官修复", "细胞疗法", "CAR-T", "CAR-NK", "基因治疗", "基因编辑",
                "AAV", "CRISPR", "免疫细胞", "细胞治疗", "体内CAR", "外泌体",
                "器官芯片", "3D生物打印", "组织修复", "再生", "细胞重编程"],
}


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
    try:
        req = urllib.request.Request(rsshub_base, headers={"User-Agent": UA})
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def fetch_rss(rss_url):
    """获取并解析 RSS feed"""
    parsed = urllib.parse.urlparse(rss_url)
    encoded_path = urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;=")
    encoded_url = urllib.parse.urlunparse((
        parsed.scheme, parsed.netloc, encoded_path,
        parsed.params, parsed.query, parsed.fragment
    ))

    req = urllib.request.Request(encoded_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")

    root = ET.fromstring(data)
    items = []
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    for item in root.iter("item"):
        entry = {}
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        date_el = item.find("pubDate")
        author_el = item.find("author")
        dc_creator = item.find("dc:creator", ns)

        entry["title"] = title_el.text if title_el is not None else ""
        entry["link"] = link_el.text if link_el is not None else ""
        entry["description"] = (desc_el.text or "")[:300] if desc_el is not None else ""
        entry["pubDate"] = date_el.text if date_el is not None else ""
        entry["author"] = author_el.text if author_el is not None else (dc_creator.text if dc_creator is not None else "")
        items.append(entry)

    return items


def is_duplicate(article_url, content_index):
    for a in content_index.get("articles", []):
        if article_url and article_url in a.get("original_url", ""):
            return True
    return False


def is_valid_rss_url(url):
    if not url:
        return False
    if "待补充" in url:
        return False
    if not url.startswith("http"):
        return False
    return True


def classify_item(item, source):
    """根据关键词自动分类"""
    title = item.get("title", "")
    desc = item.get("description", "")
    source_name = source.get("name", "")
    text = f"{title} {desc} {source_name}"

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat

    return "其他重点"


def format_pub_time(pub_date_str):
    """将 RSS 的 pubDate 转为简洁格式 MM-DD HH:MM"""
    if not pub_date_str:
        return ""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(pub_date_str.strip(), fmt)
            return dt.strftime("%m-%d %H:%M")
        except ValueError:
            continue
    return pub_date_str[:16] if len(pub_date_str) > 16 else pub_date_str


def generate_briefing(workspace, subs, content_index, rsshub_available):
    """生成每日简报，返回条目列表"""
    rsshub_base = subs.get("rsshub_base", "http://localhost:1200")
    all_items = []

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
                    print(f"  ⏭️ {name}: rss_url 未配置，跳过", file=sys.stderr)
                    continue

                rss_url = rss_url.replace("http://localhost:1200", rsshub_base)
                print(f"  📡 获取 RSS: {name}", file=sys.stderr)
                items = fetch_rss(rss_url)

                for item in items[:5]:
                    if not is_duplicate(item.get("link", ""), content_index):
                        category = classify_item(item, source)
                        item["_category"] = category
                        item["_source_name"] = name
                        all_items.append(item)

            elif stype == "website":
                url = source.get("url", "")
                if not url:
                    continue
                print(f"  🌐 爬取网站: {name}", file=sys.stderr)

        except Exception as e:
            print(f"  ❌ {name}: 抓取失败 - {e}", file=sys.stderr)

    return all_items


def save_briefing(workspace, items):
    """保存简报为 Markdown，按脑机接口/手术机器人/再生医学/其他重点分类"""
    today = datetime.date.today()
    briefings_dir = os.path.join(workspace, "briefings")
    os.makedirs(briefings_dir, exist_ok=True)
    filepath = os.path.join(briefings_dir, f"{today.isoformat()}.md")

    # 按分类分组
    categories = {}
    for item in items:
        cat = item.get("_category", "其他重点")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    lines = []
    total = len(items)
    workspace_name = os.path.basename(workspace.rstrip("/"))
    lines.append(f"# {workspace_name} 每日文摘 - {today.isoformat()}({total}篇)\n")

    global_idx = 0
    for cat_name in CATEGORY_ORDER:
        if cat_name not in categories:
            continue
        cat_items = categories[cat_name]
        emoji = CATEGORY_EMOJI.get(cat_name, "📌")

        lines.append(f"{emoji} {cat_name}{len(cat_items)}篇\n")

        for item in cat_items:
            global_idx += 1
            title = item.get("title", "无标题")
            desc = item.get("description", "").strip()
            link = item.get("link", "")
            pub_time = format_pub_time(item.get("pubDate", ""))

            time_tag = f" · 摘录时间{pub_time}" if pub_time else ""
            lines.append(f"{cat_name}#{global_idx:02d}{time_tag}")
            lines.append(f"**{title}**")

            if desc:
                # 截断过长摘要
                if len(desc) > 150:
                    cut = desc[:150]
                    last_p = max(cut.rfind('。'), cut.rfind('，'), cut.rfind('；'))
                    if last_p > 50:
                        desc = desc[:last_p+1]
                    else:
                        desc = cut + "…"
                lines.append(desc)

            if link:
                lines.append(f"[阅读原文 →]({link})")

            lines.append("")

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

    with open(filepath, "r", encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    main()
