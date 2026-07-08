#!/usr/bin/env python3
"""
collect_korea_topics.py
"외국인 대상 한국 여행/맛집" 블로그를 위한 글감 수집기.

무료로 이용 가능한 소스만 사용합니다 (API 키 불필요):
  - Reddit 공개 JSON (r/korea, r/KoreaTravel, r/Seoul, r/koreanfood)
      : 외국인이 실제로 올리는 질문/인기 글
  - Google News RSS
      : 한국 여행/음식 관련 최신 화제

수집한 자료를 바탕으로 영어 블로그 글감 후보 10개
(외국인 실전 질문형 7개 + 최신 화제형 3개)를 제안하고
korea_topics.json 파일로 저장합니다.
"""

import sys
import re
import json
import html
import argparse
from datetime import datetime, timezone
from urllib.parse import quote_plus

try:
    import requests
except ImportError:
    print("requests 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install requests")
    sys.exit(1)

try:
    import feedparser
except ImportError:
    print("feedparser 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install feedparser")
    sys.exit(1)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KoreaTopicCollectorBot/1.0)"}
REQUEST_TIMEOUT = 10

# 외국인 여행자가 실제로 활동하는 서브레딧
SUBREDDITS = ["korea", "KoreaTravel", "Seoul", "koreanfood"]

# 한국 여행/음식 관련 최신 화제를 잡기 위한 검색어들
NEWS_QUERIES = [
    "South Korea travel tips",
    "Seoul travel guide",
    "Korean street food",
    "South Korea tourism",
]


def clean_html(text):
    """RSS summary에 섞여 있는 HTML 태그 제거"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_google_news(query, limit=8):
    """Google News RSS에서 최신 뉴스를 가져온다. (무료, API 키 불필요)"""
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    items = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:limit]:
            published_dt = None
            if getattr(entry, "published_parsed", None):
                published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            items.append({
                "title": entry.get("title", "").strip(),
                "summary": clean_html(entry.get("summary", "")),
                "link": entry.get("link", ""),
                "published": published_dt.isoformat() if published_dt else entry.get("published", ""),
                "published_ts": published_dt.timestamp() if published_dt else 0,
                "source": f"Google News ({query})",
                "score": 0,
            })
    except Exception as e:
        print(f"    [경고] '{query}' 뉴스 검색 중 오류, 건너뜁니다: {e}")
    return items


def fetch_subreddit_top(subreddit, limit=15):
    """서브레딧의 이번 달 인기글을 가져온다. (무료, 로그인/API 키 불필요)"""
    url = f"https://www.reddit.com/r/{subreddit}/top.json"
    params = {"t": "month", "limit": limit}
    items = []
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            if d.get("stickied"):
                continue  # 공지/고정글(주간 질문 모음 등)은 제외
            title = (d.get("title") or "").strip()
            if not title or title == "[deleted]":
                continue
            ups = d.get("ups", 0) or 0
            items.append({
                "title": title,
                "summary": f"r/{subreddit} · 업보트 {ups}개 · 댓글 {d.get('num_comments', 0)}개",
                "link": f"https://www.reddit.com{d.get('permalink', '')}",
                "published": datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc).isoformat()
                             if d.get("created_utc") else "",
                "published_ts": d.get("created_utc", 0) or 0,
                "source": f"r/{subreddit}",
                "score": ups,
                "num_comments": d.get("num_comments", 0) or 0,
            })
        return items, None
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        return [], f"HTTP {status} (차단되었을 수 있음)"
    except Exception as e:
        return [], str(e)


def dedupe(items):
    """제목 기준으로 중복 제거"""
    seen = set()
    result = []
    for it in items:
        key = it["title"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(it)
    return result


def shorten(text, max_len=80):
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


# 제목 뒤에 " — 접미사" 형태로 붙이는 방식이라, 원본 제목이 질문형이든 평서문이든
# 문법이 깨지지 않는다.
GUIDE_TEMPLATES = [
    "{title} — A Complete Guide for First-Time Visitors",
    "{title} — Everything Foreign Tourists Need to Know",
    "{title} — What Locals Wish Tourists Knew",
    "{title} — Explained for Travelers Who've Never Been to Korea",
    "{title} — The Honest, No-Fluff Answer",
    "{title} — A Practical Guide for Your Korea Trip",
    "{title} — Tips From People Who've Actually Done It",
]

NEWS_TEMPLATES = [
    "{title} — What It Means for Your Korea Trip",
    "{title} — Trending Right Now in Korea Travel",
    "{title} — A Quick Take for Travelers",
]

GUIDE_REASONS = [
    "Reddit에서 실제로 업보트 {score}개를 받은 질문이라, 여행 전 같은 고민을 하는 외국인이 많다는 뜻입니다.",
    "댓글 {comments}개가 달릴 정도로 활발히 논의된 주제라, 검색으로도 자주 찾아보는 정보일 가능성이 큽니다.",
    "가이드북엔 잘 안 나오지만 현지에서 직접 부딪혀야 아는 실전 정보라, 여행자 커뮤니티에서 반복적으로 질문됩니다.",
    "교통·결제·문화 차이처럼 여행 전 가장 헷갈려하는 실용적 주제라, 검색 수요가 꾸준합니다.",
    "여행 전 불안감(바가지, 언어장벽, 실수)을 해소해주는 콘텐츠라 클릭과 공유가 잘 되는 유형입니다.",
    "이미 같은 커뮤니티에서 여러 번 반복해서 올라오는 질문이라, 정리된 글의 수요가 검증된 셈입니다.",
    "직접 경험담 기반 정보라, 여행 블로그 특유의 신뢰도(E-E-A-T)를 높이기 좋은 소재입니다.",
]

NEWS_REASONS = [
    "최근 화제가 된 이슈라, 여행을 계획 중인 외국인들이 실시간으로 검색하고 있을 가능성이 큽니다.",
    "시의성 있는 주제는 여행 커뮤니티나 SNS에서 공유되기 좋습니다.",
    "새로운 변화(정책, 개장, 유행)는 여행 일정에 직접 영향을 미치는 정보라 반응 속도가 빠릅니다.",
]


def build_proposal(item, idx):
    """item의 실제 출처(Reddit인지 Google News인지)에 맞는 템플릿/이유를 고른다.
    부족분을 다른 풀에서 채워 넣더라도, 항상 실제 출처에 맞는 문구가 붙도록
    kind를 목표 슬롯이 아니라 item 자체에서 판단한다."""
    is_reddit = item["source"].startswith("r/")
    templates = GUIDE_TEMPLATES if is_reddit else NEWS_TEMPLATES
    reasons = GUIDE_REASONS if is_reddit else NEWS_REASONS
    template = templates[idx % len(templates)]
    reason_template = reasons[idx % len(reasons)]
    title = template.format(title=shorten(item["title"]))
    reason = reason_template.format(
        score=item.get("score", 0),
        comments=item.get("num_comments", 0),
    )
    return {
        "type": "외국인 실전 질문형" if is_reddit else "최신 화제형",
        "title": title,
        "why_foreigners_care": reason,
        "source_title": item["title"],
        "source_link": item["link"],
        "source_from": item["source"],
    }


def generate_proposals(reddit_pool, news_pool, target_guide=7, target_news=3):
    reddit_pool = sorted(reddit_pool, key=lambda x: x.get("score", 0), reverse=True)
    news_pool = sorted(news_pool, key=lambda x: x.get("published_ts", 0), reverse=True)

    n_guide = min(target_guide, len(reddit_pool))
    n_news = min(target_news, len(news_pool))

    selected = reddit_pool[:n_guide] + news_pool[:n_news]

    shortfall = (target_guide - n_guide) + (target_news - n_news)
    if shortfall > 0:
        # 부족분은 남은 풀에서 채우되, build_proposal이 item의 실제 출처를 보고
        # 알맞은 유형/이유를 붙이므로 라벨이 실제와 어긋나지 않는다.
        leftover = reddit_pool[n_guide:] + news_pool[n_news:]
        selected += leftover[: max(0, shortfall)]

    proposals = [build_proposal(item, i) for i, item in enumerate(selected)]

    total_target = target_guide + target_news
    if len(proposals) < total_target:
        print(f"\n[안내] 수집된 자료가 부족해 글감을 {len(proposals)}개만 생성했습니다. "
              f"(목표: {total_target}개)")

    return proposals


def print_proposals(proposals):
    print("\n" + "=" * 74)
    print(f" 외국인 대상 한국 여행/맛집 블로그 글감 후보 {len(proposals)}개")
    print("=" * 74)
    for i, p in enumerate(proposals, 1):
        print(f"\n[{i}] ({p['type']})")
        print(f"  제목(EN): {p['title']}")
        print(f"  외국인이 궁금해하는 이유: {p['why_foreigners_care']}")
        print(f"  참고 원본: {p['source_link']}  (출처: {p['source_from']})")
    print("\n" + "=" * 74)


def main():
    parser = argparse.ArgumentParser(description="외국인 대상 한국 여행/맛집 블로그 글감 수집기")
    parser.add_argument(
        "--queries", nargs="+", default=None,
        help='Google News 검색어 목록 (지정 안 하면 기본값 사용, 예: --queries "Seoul travel" "Seoul food")'
    )
    parser.add_argument(
        "--output", default="korea_topics.json",
        help="결과를 저장할 파일명 (기본값: korea_topics.json)"
    )
    args = parser.parse_args()

    news_queries = args.queries if args.queries else NEWS_QUERIES

    print("한국 여행/맛집 관련 자료를 수집 중입니다... (무료 소스만 사용)\n")

    reddit_items = []
    print("[Reddit]")
    for sub in SUBREDDITS:
        items, err = fetch_subreddit_top(sub)
        if err:
            print(f"  - r/{sub}: 수집 실패 ({err}) — 건너뛰고 계속 진행합니다.")
        else:
            print(f"  - r/{sub}: {len(items)}건 수집")
        reddit_items.extend(items)

    print("\n[Google News]")
    news_items = []
    for query in news_queries:
        items = fetch_google_news(query)
        print(f"  - \"{query}\": {len(items)}건 수집")
        news_items.extend(items)

    reddit_pool = dedupe(reddit_items)
    news_pool = dedupe(news_items)

    print(f"\n중복 제거 후: Reddit {len(reddit_pool)}건, Google News {len(news_pool)}건")

    if not reddit_pool and not news_pool:
        print("\n[오류] 모든 소스에서 자료를 하나도 가져오지 못했습니다. "
              "인터넷 연결을 확인한 뒤 다시 시도해 주세요.")
        sys.exit(1)

    if not reddit_pool:
        print("\n[안내] Reddit이 전부 차단된 것으로 보입니다. "
              "Google News 자료만으로 최대한 글감을 구성합니다.")

    proposals = generate_proposals(reddit_pool, news_pool)
    print_proposals(proposals)

    result_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "news_queries_used": news_queries,
        "sources_collected": {
            "reddit_total": len(reddit_items),
            "reddit_by_subreddit": {
                sub: sum(1 for it in reddit_items if it["source"] == f"r/{sub}")
                for sub in SUBREDDITS
            },
            "google_news_total": len(news_items),
        },
        "proposals": proposals,
        "raw": {
            "reddit_pool": reddit_pool,
            "news_pool": news_pool,
        },
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    print(f"\n결과를 {args.output} 파일로 저장했습니다.")


if __name__ == "__main__":
    main()
