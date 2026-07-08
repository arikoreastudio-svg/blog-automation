#!/usr/bin/env python3
"""
add_images.py
article.md의 [이미지: 설명] 자리를 Unsplash에서 찾은 실제 사진으로 교체해
article_with_images.md로 저장한다. (원본 article.md는 건드리지 않는다)

동작:
  1. article.md에서 [이미지: 설명] 패턴을 모두 찾는다.
  2. 각 설명(한국어)에서 키워드를 뽑아 영어 검색어로 변환한다.
     (외부 번역 API 없이, 자주 쓰이는 단어를 매핑하는 방식)
  3. Unsplash Search Photos API로 검색하고, 결과 중 좋아요(likes)가
     가장 많은 사진을 "가장 잘 어울리는 사진"으로 선택한다.
  4. Unsplash API 가이드라인에 따라 다운로드 트래킹을 호출하고,
     촬영자/Unsplash 출처를 사진 밑에 표기한다.
"""

import os
import re
import sys
import time

try:
    import requests
except ImportError:
    print("requests 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install requests")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("python-dotenv 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install python-dotenv")
    sys.exit(1)

load_dotenv()

ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

SOURCE_FILE = "article.md"
OUTPUT_FILE = "article_with_images.md"
APP_NAME = "blog-automation"  # Unsplash 링크의 UTM 출처 표기용

REQUEST_TIMEOUT = 15
DELAY_BETWEEN_REQUESTS = 1.0  # 초당 요청을 과도하게 보내지 않기 위한 텀 (시간당 50회 제한 보호)

# 한국어 이미지 설명 -> 영어 검색 키워드 매핑 (오프라인, API/키 불필요)
# 이미지 설명에 아래 단어가 포함되어 있으면 대응하는 영어 단어를 검색어에 사용한다.
KEYWORD_MAP = {
    "노트북": "laptop",
    "데스크": "desk",
    "책상": "desk",
    "화면": "screen",
    "스크린샷": "screenshot",
    "클로즈업": "closeup",
    "로고": "logo",
    "히어로": "hero banner",
    "팀원": "team",
    "협업": "collaboration",
    "회의": "meeting",
    "도구": "tool",
    "콘텐츠": "content",
    "캘린더": "calendar",
    "검토": "reviewing document",
    "문서": "document",
    "편집": "editing",
    "문법": "grammar",
    "교정": "proofreading",
    "제안": "suggestion",
    "AI": "artificial intelligence",
    "생성": "generative",
    "문장": "writing text",
    "자연스러운": "natural",
    "과정": "process",
    "비포": "before",
    "애프터": "after",
    "그래픽": "graphic design",
    "작가": "writer",
    "마케터": "marketer",
    "원고": "manuscript",
    "최종": "final draft",
    "만족스러운": "happy",
    "표정": "portrait",
    "모습": "person working",
    "타이핑": "typing",
    "글쓰기": "writing",
    "사진": "photo",
}

FALLBACK_QUERY = "writing desk technology"


def build_query(description):
    """한국어 설명에서 키워드를 뽑아 영어 검색어를 만든다."""
    hits = []
    for kr, en in KEYWORD_MAP.items():
        idx = description.find(kr)
        if idx != -1:
            hits.append((idx, en))
    if not hits:
        return FALLBACK_QUERY
    hits.sort(key=lambda x: x[0])
    seen = []
    for _, en in hits:
        if en not in seen:
            seen.append(en)
    return " ".join(seen[:5])


def search_unsplash(query, per_page=5):
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {ACCESS_KEY}"}
    params = {"query": query, "per_page": per_page, "orientation": "landscape"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("results", [])


def pick_best_photo(results):
    """검색 결과 중 좋아요 수가 가장 많은 사진을 '가장 잘 어울리는 사진'으로 선택한다."""
    if not results:
        return None
    return max(results, key=lambda p: p.get("likes", 0))


def trigger_download_event(photo):
    """Unsplash API 가이드라인: 사진을 실제로 사용할 때 다운로드 트래킹을 호출해야 한다."""
    try:
        url = photo["links"]["download_location"]
        headers = {"Authorization": f"Client-ID {ACCESS_KEY}"}
        requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"    [경고] 다운로드 트래킹 호출 실패(무시하고 계속 진행): {e}")


def build_markdown_block(photo, alt_text):
    img_url = photo["urls"]["regular"]
    photographer_name = photo["user"]["name"]
    photographer_url = f'{photo["user"]["links"]["html"]}?utm_source={APP_NAME}&utm_medium=referral'
    unsplash_url = f"https://unsplash.com/?utm_source={APP_NAME}&utm_medium=referral"
    return (
        f"![{alt_text}]({img_url})\n\n"
        f"*Photo by [{photographer_name}]({photographer_url}) on [Unsplash]({unsplash_url})*"
    )


def print_env_setup_guide():
    print("""
[.env 설정 방법]
1. 프로젝트 폴더(blog-automation)에 '.env' 라는 이름의 파일을 만드세요.
2. 그 안에 아래처럼 한 줄을 넣으세요 (따옴표 없이, 실제 키로 교체):

   UNSPLASH_ACCESS_KEY=여기에_발급받은_Access_Key_붙여넣기

3. Access Key는 https://unsplash.com/developers 에서 무료로 앱을 등록하면
   'Access Key'를 받을 수 있습니다 (Demo 모드, 시간당 50 요청 제한).
4. .env 파일은 이미 .gitignore에 등록되어 있어 GitHub에는 올라가지 않습니다.
""")


def main():
    if not ACCESS_KEY:
        print("[오류] UNSPLASH_ACCESS_KEY를 찾을 수 없습니다. .env 파일이 없거나 키가 비어 있습니다.")
        print_env_setup_guide()
        sys.exit(1)

    if not os.path.exists(SOURCE_FILE):
        print(f"[오류] '{SOURCE_FILE}' 파일을 찾을 수 없습니다. 같은 폴더에서 실행해 주세요.")
        sys.exit(1)

    with open(SOURCE_FILE, encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r"\[이미지:\s*(.+?)\]")
    matches = list(pattern.finditer(content))

    if not matches:
        print(f"[안내] '{SOURCE_FILE}'에서 [이미지: 설명] 형태의 자리를 찾지 못했습니다.")
        sys.exit(0)

    print(f"'{SOURCE_FILE}'에서 이미지 자리 {len(matches)}개를 찾았습니다. Unsplash 검색을 시작합니다.\n")

    counter = {"n": 0}
    unresolved = []

    def replace(match):
        counter["n"] += 1
        idx = counter["n"]
        description = match.group(1).strip()
        print(f"[{idx}/{len(matches)}] \"{description}\"")

        query = build_query(description)
        print(f"    검색어(영문 변환): {query}")

        try:
            results = search_unsplash(query)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 401:
                print("    [경고] Access Key가 유효하지 않습니다(401). 이 자리는 원본 그대로 둡니다.")
            elif status == 403:
                print("    [경고] 요청 한도를 초과했을 수 있습니다(403, 시간당 50회 제한). 이 자리는 원본 그대로 둡니다.")
            else:
                print(f"    [경고] Unsplash 요청 실패(HTTP {status}). 이 자리는 원본 그대로 둡니다.")
            unresolved.append(description)
            return match.group(0)
        except requests.exceptions.RequestException as e:
            print(f"    [경고] 네트워크 오류로 검색에 실패했습니다: {e}. 이 자리는 원본 그대로 둡니다.")
            unresolved.append(description)
            return match.group(0)

        if not results:
            print("    [경고] 검색 결과가 없습니다. 이 자리는 원본 그대로 둡니다.")
            unresolved.append(description)
            return match.group(0)

        photo = pick_best_photo(results)
        trigger_download_event(photo)
        print(f"    선택된 사진: {photo['urls']['regular']}")
        print(f"    촬영자: {photo['user']['name']}")

        time.sleep(DELAY_BETWEEN_REQUESTS)
        return build_markdown_block(photo, description)

    new_content = pattern.sub(replace, content)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"\n완료: '{OUTPUT_FILE}' 파일로 저장했습니다. (원본 '{SOURCE_FILE}'은 그대로입니다)")

    if unresolved:
        print(f"\n[안내] {len(unresolved)}개 자리는 이미지를 찾지 못해 원래의 [이미지: 설명] 표시가 그대로 남아 있습니다:")
        for d in unresolved:
            print(f"  - {d}")


if __name__ == "__main__":
    main()
