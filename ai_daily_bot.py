#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书 AI ToC 资讯日报机器人
- 每天抓取 AI 领域（尤其 ToC 产品）资讯
- 用大模型从产品经理视角归纳
- 推送到飞书群

依赖：requests（pip install requests）
环境变量：
  FEISHU_WEBHOOK_URL  飞书自定义机器人 Webhook
  DEEPSEEK_API_KEY    DeepSeek API Key（或换成其他大模型）
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
# 配置区
# ─────────────────────────────────────────────
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
DEEPSEEK_API_KEY   = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL   = "https://api.deepseek.com/v1/chat/completions"

# 北京时区
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")
WEEKDAY_MAP = ["周一","周二","周三","周四","周五","周六","周日"]
WEEKDAY = WEEKDAY_MAP[datetime.now(CST).weekday()]

# RSS 资讯源（全部免费，无需 API Key）
RSS_SOURCES = [
    {
        "name": "少数派",
        "url": "https://sspai.com/feed",
        "keywords": ["AI", "人工智能", "大模型", "ChatGPT", "Copilot", "生成式"],
        "focus": "国内AI产品评测与用户体验"
    },
    {
        "name": "36氪",
        "url": "https://36kr.com/feed",
        "keywords": ["AI", "人工智能", "大模型", "产品", "发布", "融资"],
        "focus": "国内AI创业/产品动态"
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "keywords": ["AI", "artificial intelligence", "GPT", "LLM", "product", "launch"],
        "focus": "海外AI产品发布"
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/index.xml",
        "keywords": ["AI", "artificial intelligence", "chatbot", "model", "tool"],
        "focus": "科技媒体AI报道"
    },
    {
        "name": "Product Hunt",
        "url": "https://www.producthunt.com/feed?category=artificial-intelligence",
        "keywords": ["AI", ""],
        "focus": "海外最新AI产品上线"
    },
]

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def fetch_rss(source: dict, max_items: int = 8) -> list[dict]:
    """抓取并过滤 RSS 条目"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AI-Daily-Bot/1.0)"
    }
    items = []
    try:
        resp = requests.get(source["url"], headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # 兼容 RSS 2.0 和 Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = (
            root.findall(".//item") or
            root.findall(".//atom:entry", ns) or
            root.findall(".//entry")
        )

        for entry in entries:
            title = (
                getattr(entry.find("title"), "text", "") or
                getattr(entry.find("{http://www.w3.org/2005/Atom}title"), "text", "") or
                ""
            ).strip()
            
            link = (
                getattr(entry.find("link"), "text", "") or
                (entry.find("{http://www.w3.org/2005/Atom}link") or {}).get("href", "") or  # type: ignore
                ""
            ).strip()
            
            desc = (
                getattr(entry.find("description"), "text", "") or
                getattr(entry.find("summary"), "text", "") or
                getattr(entry.find("{http://www.w3.org/2005/Atom}summary"), "text", "") or
                ""
            )[:300].strip()

            if not title:
                continue

            # 关键词过滤（有关键词列表时才过滤）
            kws = source.get("keywords", [])
            if kws and any(kws):
                combined = (title + desc).lower()
                if not any(kw.lower() in combined for kw in kws if kw):
                    continue

            items.append({
                "title": title,
                "link": link,
                "desc": desc,
                "source": source["name"]
            })

            if len(items) >= max_items:
                break

    except Exception as e:
        print(f"[WARN] 抓取 {source['name']} 失败: {e}")

    return items


def collect_all_news() -> str:
    """汇总所有资讯源，返回文本"""
    all_items = []
    for source in RSS_SOURCES:
        items = fetch_rss(source)
        print(f"[INFO] {source['name']}: 抓取到 {len(items)} 条")
        all_items.extend(items)

    if not all_items:
        return "今日暂无抓取到资讯。"

    lines = []
    for item in all_items:
        lines.append(f"[{item['source']}] {item['title']}")
        if item['desc']:
            lines.append(f"  摘要：{item['desc'][:120]}")
        if item['link']:
            lines.append(f"  链接：{item['link']}")
        lines.append("")

    return "\n".join(lines)


def summarize_with_llm(raw_news: str) -> str:
    """调用 DeepSeek 大模型，从 PM 视角归纳"""
    if not DEEPSEEK_API_KEY:
        return "⚠️ 未配置 DEEPSEEK_API_KEY，跳过 AI 归纳。\n\n原始资讯：\n" + raw_news[:1500]

    prompt = f"""你是一位资深产品经理，专注于 AI ToC（面向用户的消费级AI产品）领域。
今天是 {TODAY}（{WEEKDAY}）。

请根据以下原始资讯，生成一份简洁有价值的日报摘要，要求：

1. **今日核心洞察**（1-2句话，抓住最重要的趋势/变化）
2. **新品 & 功能更新**（列出3-5条，格式：产品名 → 核心功能 → 解决的用户痛点）
3. **PM视角趋势**（2-3条，聚焦：用户需求变化、竞争格局、商业模式创新）
4. **值得关注的用户信号**（真实反馈/投票/评论中反映的用户诉求，如有）

要求：
- 语言简洁，每条不超过50字
- 聚焦 ToC 产品，过滤纯技术/学术内容
- 如果今日资讯较少，可结合近期趋势补充背景
- 不要编造不存在的产品或数据

---
原始资讯：
{raw_news[:3000]}
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.4
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ERROR] LLM 调用失败: {e}")
        return f"AI归纳失败（{e}），以下为原始资讯：\n\n" + raw_news[:1500]


def send_to_feishu(summary: str):
    """发送消息卡片到飞书"""
    if not FEISHU_WEBHOOK_URL:
        print("[ERROR] 未配置 FEISHU_WEBHOOK_URL")
        return

    # 构造富文本消息卡片
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📱 AI ToC 产品日报 | {TODAY} {WEEKDAY}"
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": summary
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"来源：少数派 / 36氪 / TechCrunch / The Verge / Product Hunt | 由 AI 从 PM 视角归纳整理"
                        }
                    ]
                }
            ]
        }
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=card, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            print("[INFO] ✅ 飞书推送成功！")
        else:
            print(f"[WARN] 飞书返回异常: {result}")
    except Exception as e:
        print(f"[ERROR] 飞书推送失败: {e}")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def main():
    print(f"[INFO] 开始执行 AI 日报 — {TODAY}")

    print("[INFO] 正在抓取资讯...")
    raw_news = collect_all_news()
    print(f"[INFO] 抓取完成，共 {len(raw_news)} 字符")

    print("[INFO] 正在调用大模型归纳...")
    summary = summarize_with_llm(raw_news)
    print("[INFO] 归纳完成")
    print("=" * 50)
    print(summary)
    print("=" * 50)

    print("[INFO] 正在推送到飞书...")
    send_to_feishu(summary)

    print("[INFO] 全部完成 ✅")


if __name__ == "__main__":
    main()
