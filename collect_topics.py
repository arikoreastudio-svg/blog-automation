#!/usr/bin/env python3
"""
collect_topics.py
AI 툴 / SaaS 리뷰 블로그를 위한 글감 수집기.

무료로 이용 가능한 소스만 사용합니다 (API 키 불필요):
  - Google News RSS      : 최신 뉴스
  - Hacker News Algolia API : 인기 글/토론
  - Reddit 공개 검색 JSON   : 인기 글/토론

키워드를 입력하면 위 소스에서 자료를 모은 뒤,
영어 블로그용 글감 후보 10개(비교·리뷰형 7개 + 최신 뉴스 양념형 3개)를
제안하고 topics.json 파일로 저장합니다.
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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TopicCollectorBot/1.0)"}
REQUEST_TIMEOUT = 10


def clean_html(text):
    """RSS summary에 섞여 있는 HTML 태그 제거"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_google_news(keyword, limit=15):
    """Google News RSS에서 최신 뉴스를 가져온다. (무료, API 키 불필요)"""
    url = f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl=en-US&gl=US&ceid=US:en"
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
                "source": "Google News",
                "score": 0,
            })
    except Exception as e:
        print(f"[경고] Google News 수집 중 오류 발생, 이 소스는 건너뜁니다: {e}")
    return items


def fetch_hackernews(keyword, limit=15):
    """Hacker News Algolia 검색 API에서 인기 글을 가져온다. (무료, API 키 불필요)"""
    url = "https://hn.algolia.com/api/v1/search"
    params = {"query": keyword, "tags": "story", "hitsPerPage": limit}
    items = []
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        for hit in data.get("hits", []):
            title = hit.get("title") or hit.get("story_title")
            if not title:
                continue
            title = re.sub(r"^(Show HN|Ask HN|Tell HN)\s*:\s*", "", title.strip())
            link = hit.get("url") or hit.get("story_url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            points = hit.get("points", 0) or 0
            comments = hit.get("num_comments", 0) or 0
            items.append({
                "title": title.strip(),
                "summary": f"Hacker News · 포인트 {points} · 댓글 {comments}개",
                "link": link,
                "published": hit.get("created_at", ""),
                "published_ts": 0,
                "source": "Hacker News",
                "score": points,
            })
    except Exception as e:
        print(f"[경고] Hacker News 수집 중 오류 발생, 이 소스는 건너뜁니다: {e}")
    return items


def fetch_reddit(keyword, limit=15):
    """Reddit 공개 검색 JSON에서 인기 글을 가져온다. (무료, 로그인/API 키 불필요)"""
    url = "https://www.reddit.com/search.json"
    params = {"q": keyword, "sort": "top", "t": "month", "limit": limit}
    items = []
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = d.get("title", "").strip()
            if not title:
                continue
            ups = d.get("ups", 0) or 0
            items.append({
                "title": title,
                "summary": f"Reddit r/{d.get('subreddit', '')} · 업보트 {ups}개",
                "link": f"https://www.reddit.com{d.get('permalink', '')}",
                "published": datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc).isoformat()
                             if d.get("created_utc") else "",
                "published_ts": d.get("created_utc", 0) or 0,
                "source": "Reddit",
                "score": ups,
            })
    except Exception as e:
        print(f"[경고] Reddit 수집 중 오류 발생(차단되었을 수 있음), 이 소스는 건너뜁니다: {e}")
    return items


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


REVIEW_TEMPLATES = [
    'Is "{title}" Actually Worth It? An Honest {keyword} Review',
    "{keyword} Compared: What \"{title}\" Gets Right (and Wrong)",
    'We Looked Into "{title}" — Here\'s What {keyword} Buyers Should Know',
    "{keyword} Buyer's Guide: Lessons from \"{title}\"",
    'Everyone\'s Talking About "{title}" — Here\'s Our Take on {keyword}',
    "Best {keyword} Options in 2026: Starting with \"{title}\"",
    '"{title}" vs the Rest: {article} {keyword} Comparison',
]

NEWS_TEMPLATES = [
    'Breaking: "{title}" — What It Means for {keyword}',
    "{keyword} News: \"{title}\"",
    'Quick Take: "{title}" and Why It Matters for {keyword} Users',
]

REVIEW_REASONS = [
    "구매 의도가 높은 '비교/리뷰' 키워드는 제휴(Affiliate) 링크 클릭률과 전환율이 높습니다.",
    "이미 반응(포인트/업보트 {score}개)이 검증된 주제라 검색 수요가 있을 가능성이 큽니다.",
    "'vs', '리뷰' 형태의 롱테일 키워드는 광고 경쟁이 상대적으로 낮아 SEO 상위 노출이 쉽습니다.",
    "비교형 콘텐츠는 체류 시간이 길어 애드센스/디스플레이 광고 수익에도 유리합니다.",
    "제품 선택 단계의 독자를 타겟팅하므로 SaaS 제휴 수수료 전환에 특히 적합합니다.",
]

NEWS_REASONS = [
    "시의성 있는 뉴스 반응 글은 구글 디스커버/SNS 유입을 빠르게 끌어올 수 있습니다.",
    "발빠른 뉴스 커버리지는 브랜드를 '해당 분야 최신 정보통'으로 포지셔닝하는 데 도움이 됩니다.",
    "최신 이슈는 백링크와 소셜 공유가 몰리기 쉬워 단기간 트래픽 스파이크를 노릴 수 있습니다.",
]


def shorten(text, max_len=70):
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def build_proposal(item, idx, kind, keyword):
    templates = REVIEW_TEMPLATES if kind == "review" else NEWS_TEMPLATES
    reasons = REVIEW_REASONS if kind == "review" else NEWS_REASONS
    template = templates[idx % len(templates)]
    reason = reasons[idx % len(reasons)]
    article = "An" if keyword[:1].lower() in "aeiou" else "A"
    title = template.format(title=shorten(item["title"]), keyword=keyword, article=article)
    reason = reason.format(score=item.get("score", 0))
    return {
        "type": "비교/리뷰형" if kind == "review" else "최신 뉴스 양념형",
        "title": title,
        "reason": reason,
        "source_title": item["title"],
        "source_link": item["link"],
        "source_from": item["source"],
    }


def generate_proposals(popular_pool, news_pool, keyword, target_review=7, target_news=3):
    popular_pool = sorted(popular_pool, key=lambda x: x.get("score", 0), reverse=True)
    news_pool = sorted(news_pool, key=lambda x: x.get("published_ts", 0), reverse=True)

    proposals = []

    n_review = min(target_review, len(popular_pool))
    for i in range(n_review):
        proposals.append(build_proposal(popular_pool[i], i, "review", keyword))

    n_news = min(target_news, len(news_pool))
    for i in range(n_news):
        proposals.append(build_proposal(news_pool[i], i, "news", keyword))

    shortfall = (target_review - n_review) + (target_news - n_news)
    if shortfall > 0:
        # 부족분은 남은 풀(어느 쪽이든)에서 채워서 최대한 10개에 맞춘다
        leftover_popular = popular_pool[n_review:]
        leftover_news = news_pool[n_news:]
        backup = leftover_popular + leftover_news
        for i, item in enumerate(backup):
            if len(proposals) >= target_review + target_news:
                break
            proposals.append(build_proposal(item, i, "review", keyword))

    if len(proposals) < target_review + target_news:
        print(f"[안내] 수집된 자료가 부족해 글감을 {len(proposals)}개만 생성했습니다. "
              f"(목표: {target_review + target_news}개) 키워드를 좀 더 넓게 입력해보시면 더 많이 모을 수 있어요.")

    return proposals


def print_proposals(proposals, keyword):
    print("\n" + "=" * 70)
    print(f' "{keyword}" 관련 블로그 글감 후보 {len(proposals)}개')
    print("=" * 70)
    for i, p in enumerate(proposals, 1):
        print(f"\n[{i}] ({p['type']})")
        print(f"  제목(EN): {p['title']}")
        print(f"  수익화 포인트: {p['reason']}")
        print(f"  참고 원본: {p['source_link']}  (출처: {p['source_from']})")
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="AI 툴/SaaS 리뷰 블로그 글감 수집기")
    parser.add_argument("keyword", nargs="*", help="관심 키워드 (예: AI writing tools)")
    args = parser.parse_args()

    if args.keyword:
        keyword = " ".join(args.keyword).strip()
    else:
        keyword = input("관심 키워드를 입력하세요 (예: AI writing tools): ").strip()

    if not keyword:
        print("키워드가 비어 있습니다. 프로그램을 종료합니다.")
        sys.exit(1)

    print(f"\n'{keyword}' 관련 자료를 수집 중입니다... (무료 소스만 사용)")

    news_items = fetch_google_news(keyword)
    print(f"  - Google News: {len(news_items)}건 수집")

    hn_items = fetch_hackernews(keyword)
    print(f"  - Hacker News: {len(hn_items)}건 수집")

    reddit_items = fetch_reddit(keyword)
    print(f"  - Reddit: {len(reddit_items)}건 수집")

    news_pool = dedupe(news_items)
    popular_pool = dedupe(hn_items + reddit_items)

    if not news_pool and not popular_pool:
        print("\n[오류] 모든 소스에서 자료를 하나도 가져오지 못했습니다. "
              "인터넷 연결을 확인하거나 다른 키워드로 다시 시도해 주세요.")
        sys.exit(1)

    proposals = generate_proposals(popular_pool, news_pool, keyword)
    print_proposals(proposals, keyword)

    output = {
        "keyword": keyword,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources_collected": {
            "google_news": len(news_items),
            "hacker_news": len(hn_items),
            "reddit": len(reddit_items),
        },
        "proposals": proposals,
        "raw": {
            "news_pool": news_pool,
            "popular_pool": popular_pool,
        },
    }

    with open("topics.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n결과를 topics.json 파일로 저장했습니다.")


if __name__ == "__main__":
    main()
