#!/usr/bin/env python3
"""
add_images.py
article.md의 [이미지: 설명] 자리를 Unsplash/Pexels에서 찾은 실제 사진으로
교체해 article_with_images.md로 저장한다. (원본 article.md는 건드리지 않는다)

동작:
  1. article.md에서 [이미지: 설명] 패턴을 모두 찾는다.
  2. 각 설명(한국어)에서 키워드를 뽑아 영어 검색어로 변환한다.
     (외부 번역 API 없이, 자주 쓰이는 단어를 매핑하는 방식)
  3. Unsplash Search Photos API와(설정돼 있다면) Pexels API를 함께 검색해서,
     결과 중 좋아요(likes)가 가장 많은 사진을 "가장 잘 어울리는 사진"으로
     선택한다. (Pexels는 좋아요 수를 제공하지 않아 0으로 취급되므로,
     Unsplash에 괜찮은 결과가 있으면 그쪽이 우선된다.)
  4. Unsplash API 가이드라인에 따라 다운로드 트래킹을 호출하고,
     촬영자/출처(Unsplash 또는 Pexels)를 사진 밑에 표기한다.
"""

import os
import re
import sys
import time
import argparse

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
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

DEFAULT_SOURCE_FILE = "article.md"
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
    # 여행/공항 관련 (한국 여행 블로그용)
    "인천공항": "incheon airport",
    "공항철도": "airport train",
    "공항": "airport",
    "입국장": "airport arrival hall",
    "캐리어": "suitcase luggage",
    "여행객": "traveler",
    "지하철": "subway train",
    "열차": "train",
    "기차": "train",
    "좌석": "train seat",
    "거치대": "luggage rack",
    "리무진버스": "airport shuttle bus",
    "버스": "bus",
    "승차장": "bus station",
    "기다리는": "waiting",
    "사람들": "people",
    "택시": "taxi",
    "서울": "seoul city",
    "시내": "city street",
    "지도": "map",
    "경로": "route",
    "주황색": "orange",
    "달리는": "driving",
    "뒷모습": "back view walking",
    # 명동/쇼핑/시장 관련 (한국 여행 블로그용)
    "명동": "myeongdong seoul",
    "로드샵": "beauty store shop",
    "화장품": "cosmetics",
    "매장": "store interior",
    "테스트": "product testing",
    "길거리": "street",
    "음식": "food",
    "노점": "food stall",
    "떡볶이": "tteokbokki korean street food",
    "호떡": "korean pancake",
    "성당": "cathedral",
    "고딕": "gothic architecture",
    "외관": "building exterior",
    "간판": "shop signage",
    "오가는": "walking crowd",
    "표지판": "sign",
    "출구": "exit sign",
    "광장시장": "gwangjang market",
    "전통시장": "traditional market korea",
    "먹거리": "street food market",
    "빈대떡": "korean pancake food",
    "마약김밥": "korean rice roll food",
    "상인": "market vendor",
    "쇼핑": "shopping",
    # 성수동/카페/팝업 관련 (한국 여행 블로그용)
    "성수동": "seongsu seoul",
    "성수": "seongsu seoul",
    "공장": "factory",
    "창고": "warehouse",
    "개조": "renovated building",
    "붉은": "red brick",
    "벽돌": "brick",
    "인더스트리얼": "industrial interior",
    "카페": "cafe",
    "인테리어": "interior design",
    "커피": "coffee",
    "팝업스토어": "pop-up store",
    "팝업": "pop-up store",
    "줄": "queue line",
    "전경": "storefront",
    "편집숍": "concept store",
    "소품샵": "boutique shop",
    "디저트": "dessert cafe",
    "케이크": "cake",
    "베이커리": "bakery",
    "지하철역": "subway station",
    "성수역": "subway station seoul",
    "뚝섬역": "subway station seoul",
    "서울숲": "seoul forest park",
    "잔디밭": "park lawn",
    "산책로": "walking path park",
    "나무": "trees",
    "우거진": "green nature",
    "풍경": "landscape scenery",
    # 경복궁/한복 관련 (한국 여행 블로그용)
    "경복궁역": "gyeongbokgung station seoul",
    "경복궁": "gyeongbokgung palace korea",
    "한복": "hanbok korean traditional dress",
    "근정전": "korean palace throne hall",
    "광화문": "gwanghwamun gate korea",
    "수문장": "royal guard korea palace",
    "교대식": "changing ceremony guard",
    "갑옷": "traditional armor korea",
    "대여점": "rental shop",
    "진열된": "displayed",
    "다양한": "colorful variety",
    "웅장한": "grand traditional building",
    "목조": "wooden architecture korea",
    "처마": "traditional roof eaves korea",
    "북촌한옥마을": "bukchon hanok village korea",
    "한옥": "hanok korean traditional house",
    "골목": "alley",
    "지붕": "rooftop",
    "이어진": "connected",
    # 광장시장/전통시장 관련 (한국 여행 블로그용)
    "입구": "market entrance",
    "부치고": "cooking pancake",
    "좌판": "market food stall bench",
    "붐비는": "crowded busy",
    "청계천": "cheonggyecheon stream seoul",
    "산책": "walking",
    "종로5가역": "jongno subway station seoul",
    "종로": "jongno seoul",
    # 지하철 이용법 관련 (한국 여행 블로그용)
    "승강장": "subway platform seoul",
    "편의점": "convenience store korea",
    "교통카드": "t-money transit card korea",
    "개찰구": "subway turnstile gate seoul",
    "태그": "tapping card reader",
    "올빼미버스": "night bus seoul korea",
    "심야": "night time city",
    "정류장": "bus stop korea",
    "환승": "transfer",
    "노약자석": "priority seat subway",
    "임산부": "pregnant priority seat",
    "배려석": "priority seat train",
    # 북촌한옥마을 관련 (한국 여행 블로그용)
    "안국역": "anguk station seoul",
    "삼청동": "samcheong-dong seoul",
    "카페거리": "cafe street korea",
    "인사동": "insadong seoul",
    "전망": "viewpoint hanok",
    "언덕": "hillside alley",
    "기와": "tiled roof korea",
    "처마선": "roofline hanok",
    "대문": "traditional gate hanok",
    "한옥카페": "hanok cafe korea",
    "전통가옥": "traditional house korea",
    "고즈넉한": "quiet traditional",
    # 홍대 관련 (한국 여행 블로그용)
    "홍대": "hongdae seoul",
    "홍대입구역": "hongik university station seoul",
    "버스킹": "street busking performance",
    "거리공연": "street performance korea",
    "걷고싶은거리": "hongdae street korea",
    "인디음악": "indie music korea",
    "라이브클럽": "live music club korea",
    "편집숍": "boutique shop korea",
    "프리마켓": "flea market korea",
    "예술시장": "art market korea",
    "벽화": "mural street art",
    "놀이터": "hongdae playground park",
    "연남동": "yeonnam-dong seoul",
    "상수동": "sangsu-dong seoul",
    "합정": "hapjeong seoul",
    "테마카페": "themed cafe korea",
}

FALLBACK_QUERY = "writing desk technology"


def build_query(description):
    """한국어 설명에서 키워드를 뽑아 영어 검색어를 만든다.
    "공항철도"(4글자)와 "공항"(2글자)처럼 한 키워드가 다른 키워드의 부분
    문자열이면, 더 긴(더 구체적인) 키워드만 채택해서 "airport train airport"처럼
    같은 단어가 중복/변주되어 검색어가 지나치게 좁아지는 걸 막는다."""
    candidates = []
    for kr, en in KEYWORD_MAP.items():
        idx = description.find(kr)
        if idx != -1:
            candidates.append((idx, idx + len(kr), en, len(kr)))
    if not candidates:
        return FALLBACK_QUERY

    candidates.sort(key=lambda x: (-x[3], x[0]))  # 긴 키워드부터 자리를 차지
    covered = []
    accepted = []
    for start, end, en, _ in candidates:
        if any(start < c_end and end > c_start for c_start, c_end in covered):
            continue
        covered.append((start, end))
        accepted.append((start, en))

    accepted.sort(key=lambda x: x[0])

    # 구(phrase) 단위가 아니라 단어 단위로 중복을 제거한다.
    # (예: "airport train" + "train seat"처럼 서로 다른 구라도 "train"이
    #  겹치면 Unsplash 검색 결과가 0건이 되는 경우가 있어, 같은 단어의
    #  반복을 막아 검색어를 더 짧고 명확하게 만든다)
    words = []
    lowered = []
    for _, phrase in accepted:
        for w in phrase.split():
            if w.lower() not in lowered:
                lowered.append(w.lower())
                words.append(w)

    if not words:
        return FALLBACK_QUERY
    return " ".join(words[:6])


def search_unsplash(query, per_page=5):
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {ACCESS_KEY}"}
    params = {"query": query, "per_page": per_page, "orientation": "landscape"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _normalize_unsplash(photo):
    return {
        "source": "unsplash",
        "id": f"unsplash:{photo.get('id')}",
        "likes": photo.get("likes", 0) or 0,
        "regular_url": photo["urls"]["regular"],
        "page_url": photo["links"]["html"],
        "photographer_name": photo["user"]["name"],
        "photographer_url": photo["user"]["links"]["html"],
        "download_location": photo.get("links", {}).get("download_location"),
        "alt_description": photo.get("alt_description"),
        "description": photo.get("description"),
    }


def search_pexels(query, per_page=5):
    """Pexels Search API로 검색한다. (PEXELS_API_KEY가 없으면 조용히 빈 리스트 반환)"""
    if not PEXELS_API_KEY:
        return []
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": per_page, "orientation": "landscape"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("photos", [])


def _normalize_pexels(photo):
    # Pexels는 좋아요 수를 제공하지 않으므로 0으로 둔다.
    return {
        "source": "pexels",
        "id": f"pexels:{photo.get('id')}",
        "likes": 0,
        "regular_url": photo["src"]["large"],
        "page_url": photo.get("url"),
        "photographer_name": photo.get("photographer", "Unknown"),
        "photographer_url": photo.get("photographer_url", "https://www.pexels.com"),
        "download_location": None,
        "alt_description": photo.get("alt"),
        "description": None,
    }


def search_all_sources(query, per_page=5):
    """Unsplash와(설정돼 있으면) Pexels를 함께 검색해서, 정규화된 형태로 합쳐 반환한다.
    한쪽 소스에서 오류가 나도 다른 쪽 결과는 그대로 살려서 반환한다."""
    results = []

    try:
        unsplash_raw = search_unsplash(query, per_page=per_page)
        results.extend(_normalize_unsplash(p) for p in unsplash_raw)
    except requests.exceptions.HTTPError:
        raise  # 인증/한도 오류는 상위에서 처리하도록 그대로 올린다
    except requests.exceptions.RequestException as e:
        print(f"    [경고] Unsplash 검색 중 네트워크 오류(무시하고 계속): {e}")

    if PEXELS_API_KEY:
        try:
            pexels_raw = search_pexels(query, per_page=per_page)
            results.extend(_normalize_pexels(p) for p in pexels_raw)
        except Exception as e:
            print(f"    [경고] Pexels 검색 실패(무시하고 Unsplash 결과만 사용): {e}")

    return results


def search_all_sources_with_fallback(query, per_page=5):
    """검색어가 너무 구체적이면 결과가 0건일 수 있어서, 단어 수를 점점 줄여가며
    재시도한다 (예: 6단어 -> 4단어 -> 2단어 -> 1단어). HTTP 오류(인증/한도 초과 등)는
    재시도해도 소용없으므로 즉시 그대로 올려보낸다."""
    words = query.split()
    tried = []
    for n in sorted({len(words), 4, 2, 1}, reverse=True):
        if n > len(words) or n in tried:
            continue
        tried.append(n)
        attempt_query = " ".join(words[:n])
        results = search_all_sources(attempt_query, per_page=per_page)
        if results:
            return results, attempt_query
    return [], query


def pick_best_photo(results, exclude_ids=None):
    """결과 중 좋아요 수가 가장 많은 사진을 '가장 잘 어울리는 사진'으로 선택한다.
    같은 글 안에서 이미 쓴 사진(exclude_ids)은 제외해서, 서로 다른 자리인데
    같은 사진이 중복으로 뽑히는 걸 막는다. 제외하고 나면 남는 후보가 없을 때만
    예외적으로 이미 쓴 사진이라도 다시 허용한다."""
    if not results:
        return None
    exclude_ids = exclude_ids or set()
    candidates = [p for p in results if p.get("id") not in exclude_ids]
    pool = candidates if candidates else results
    return max(pool, key=lambda p: p.get("likes", 0))


def trigger_download_event(photo):
    """Unsplash API 가이드라인: 사진을 실제로 사용할 때 다운로드 트래킹을 호출해야 한다.
    (Pexels는 이런 트래킹 호출이 필요 없으므로 Unsplash 사진일 때만 호출한다)"""
    if photo.get("source") != "unsplash" or not photo.get("download_location"):
        return
    try:
        headers = {"Authorization": f"Client-ID {ACCESS_KEY}"}
        requests.get(photo["download_location"], headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"    [경고] 다운로드 트래킹 호출 실패(무시하고 계속 진행): {e}")


def resolve_alt_text(photo, fallback_query):
    """이미지의 alt 텍스트는 항상 영어로 만든다 (번역 API 없이).
    Unsplash/Pexels가 제공하는 사진 자체의 실제 영어 설명(alt_description)이
    있으면 그걸 쓰고, 없으면 검색에 사용한 영어 키워드를 그대로 alt로 쓴다.
    (한국어 자리 설명은 검색/문서화용으로만 쓰고, 최종 alt에는 넣지 않는다)"""
    api_alt = (photo.get("alt_description") or "").strip()
    text = api_alt if api_alt else fallback_query
    if not text:
        return "Photo"
    return text[0].upper() + text[1:]


def build_markdown_block(photo, alt_text):
    img_url = photo["regular_url"]
    photographer_name = photo["photographer_name"]

    if photo.get("source") == "pexels":
        photographer_url = photo["photographer_url"]
        source_label = f"[Pexels](https://www.pexels.com/?utm_source={APP_NAME}&utm_medium=referral)"
    else:
        photographer_url = f'{photo["photographer_url"]}?utm_source={APP_NAME}&utm_medium=referral'
        source_label = f"[Unsplash](https://unsplash.com/?utm_source={APP_NAME}&utm_medium=referral)"

    return (
        f"![{alt_text}]({img_url})\n\n"
        f"*Photo by [{photographer_name}]({photographer_url}) on {source_label}*"
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

[Pexels도 함께 검색하고 싶다면 (선택사항)]
1. https://www.pexels.com/api/ 에서 무료 계정으로 가입하고 API 키를 발급받으세요
   (승인 즉시 발급, 시간당 200회 / 월 20,000회 무료 한도).
2. .env에 아래 한 줄을 추가하세요:

   PEXELS_API_KEY=여기에_발급받은_키_붙여넣기

3. 이 키가 없어도 스크립트는 정상 동작합니다 (Unsplash만 검색).
""")


def main():
    parser = argparse.ArgumentParser(description="마크다운의 [이미지: 설명] 자리를 Unsplash 사진으로 교체")
    parser.add_argument("source", nargs="?", default=DEFAULT_SOURCE_FILE,
                         help=f"입력 마크다운 파일 (기본값: {DEFAULT_SOURCE_FILE})")
    parser.add_argument("-o", "--output", default=None,
                         help="출력 파일명 (기본값: '<입력파일명>_with_images.md')")
    args = parser.parse_args()

    source_file = args.source
    if args.output:
        output_file = args.output
    else:
        base, ext = os.path.splitext(source_file)
        output_file = f"{base}_with_images{ext}"

    if not ACCESS_KEY:
        print("[오류] UNSPLASH_ACCESS_KEY를 찾을 수 없습니다. .env 파일이 없거나 키가 비어 있습니다.")
        print_env_setup_guide()
        sys.exit(1)

    if not os.path.exists(source_file):
        print(f"[오류] '{source_file}' 파일을 찾을 수 없습니다. 같은 폴더에서 실행해 주세요.")
        sys.exit(1)

    with open(source_file, encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r"\[이미지:\s*(.+?)\]")
    matches = list(pattern.finditer(content))

    if not matches:
        print(f"[안내] '{source_file}'에서 [이미지: 설명] 형태의 자리를 찾지 못했습니다.")
        sys.exit(0)

    print(f"'{source_file}'에서 이미지 자리 {len(matches)}개를 찾았습니다. Unsplash 검색을 시작합니다.\n")

    counter = {"n": 0}
    unresolved = []
    used_photo_ids = set()

    def replace(match):
        counter["n"] += 1
        idx = counter["n"]
        description = match.group(1).strip()
        print(f"[{idx}/{len(matches)}] \"{description}\"")

        query = build_query(description)
        print(f"    검색어(영문 변환): {query}")

        try:
            results, used_query = search_all_sources_with_fallback(query)
            if results and used_query != query:
                print(f"    [안내] 원래 검색어로 결과가 없어 '{used_query}'로 줄여서 재검색했습니다.")
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

        photo = pick_best_photo(results, exclude_ids=used_photo_ids)
        used_photo_ids.add(photo.get("id"))
        trigger_download_event(photo)
        alt_text = resolve_alt_text(photo, query)
        print(f"    선택된 사진({photo['source']}): {photo['regular_url']}")
        print(f"    촬영자: {photo['photographer_name']}")
        print(f"    alt 텍스트(영어): {alt_text}")

        time.sleep(DELAY_BETWEEN_REQUESTS)
        return build_markdown_block(photo, alt_text)

    new_content = pattern.sub(replace, content)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"\n완료: '{output_file}' 파일로 저장했습니다. (원본 '{source_file}'은 그대로입니다)")

    if unresolved:
        print(f"\n[안내] {len(unresolved)}개 자리는 이미지를 찾지 못해 원래의 [이미지: 설명] 표시가 그대로 남아 있습니다:")
        for d in unresolved:
            print(f"  - {d}")


if __name__ == "__main__":
    main()
