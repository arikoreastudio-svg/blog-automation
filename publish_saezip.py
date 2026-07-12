#!/usr/bin/env python3
"""
publish_saezip.py
"새집일기" 블로그(saezip-diary.blogspot.com) 전용 발행 스크립트.

절대 원칙 (코드로 강제):
  - 블로그 ID는 여기 SAEZIP_BLOG_ID에 하드코딩된 값만 쓴다.
    .env의 BLOGGER_BLOG_ID(여행 블로그 ID)는 이 스크립트에서 아예 안 쓴다.
  - 항상 임시저장(draft)으로만 올린다 (isDraft=True / publish=False).
  - 기존 글을 되돌리거나(revert) 상태를 바꾸는 동작은 이 스크립트에 없다.
    (그런 동작이 필요하면 사용자에게 먼저 물어보고 별도로 처리해야 한다)

사용법:
  python3 publish_saezip.py \\
    --title "글 제목" \\
    --body body.html \\
    --permalink curtain-blind-xxx \\
    --labels "라벨1,라벨2,라벨3" \\
    --image IMAGE_1 "query a;query b" \\
    --image IMAGE_2 "query c;query d" \\
    --exclude-file ../other_post_with_images.md \\
    --exclude-file ../another_post.html

옵션 설명:
  --title        글 제목 (필수)
  --body         본문 HTML 파일 경로. [[IMAGE_1]], [[IMAGE_2]] ... 형태의
                 자리를 찾아 이미지로 치환한다. (필수)
  --permalink    커스텀 URL 슬러그 (영문). 최선을 다해 시도하지만, Blogger가
                 draft 상태에서는 실제 반영 여부를 보여주지 않으므로
                 직접 게시 전 Blogger 편집 화면에서 재확인 권장. (선택)
  --labels       쉼표로 구분한 라벨 목록. 15개를 넘으면 자동으로 뒤에서부터
                 줄여가며 실제로 들어가는 최대 개수를 찾는다
                 (Blogger API가 라벨 총량에 제한이 있는 것으로 실측 확인됨).
  --image        "PLACEHOLDER" "검색어1;검색어2;검색어3" 형태로 반복 지정.
                 세미콜론으로 구분한 검색어를 순서대로 시도해서, 결과가
                 있는 첫 검색어의 사진 중 좋아요가 가장 많은 걸 고른다.
  --exclude-file 이미 다른 글에 쓴 이미지와 안 겹치게, 그 글의 파일(.md 또는
                 HTML)에서 photo-<id> 패턴을 뽑아 제외 목록에 추가한다.
                 여러 번 지정 가능.
  --dry-run      실제로 발행하지 않고, 검색된 이미지와 최종 본문만 보여준다.
"""

import argparse
import os
import re
import sys

try:
    import requests
except ImportError:
    print("requests 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install requests")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import add_images as ai
except ImportError:
    print("[오류] add_images.py를 같은 폴더에서 찾을 수 없습니다.")
    sys.exit(1)

try:
    import publish_to_blogger as pb
except ImportError:
    print("[오류] publish_to_blogger.py를 같은 폴더에서 찾을 수 없습니다.")
    sys.exit(1)

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("Google API 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)


# ⚠️ 새집일기 블로그 ID. .env의 BLOGGER_BLOG_ID(여행 블로그)는 절대 쓰지 않는다.
SAEZIP_BLOG_ID = "2115552525920052216"
TRAVEL_BLOG_ID_TO_AVOID = "1208669495299732956"  # 안전장치 비교용

MAX_LABELS_HARD_CAP = 15  # 실측으로 확인된 Blogger API 라벨 제한


def photo_identifier(url):
    """이미지 URL에서 중복 비교용 식별자를 뽑는다.
    (add_images.py의 정규화된 'id' 필드는 'unsplash:<api_id>' 형식이라 기존
    글 파일 안의 이미지 URL과 직접 비교할 수 없어서, 여기서는 URL 슬러그를
    공통 식별자로 써서 exclude-file 스캔 결과와 신규 검색 결과를 같은
    기준으로 비교한다.)"""
    if not url:
        return None
    m = re.search(r"photo-[a-zA-Z0-9]+-[a-zA-Z0-9]+", url)
    if m:
        return m.group(0)
    m = re.search(r"pexels-photo-\d+", url)
    if m:
        return m.group(0)
    return url


def extract_used_photo_ids(file_paths):
    """다른 글 파일들에서 이미 쓰인 사진의 URL 슬러그를 뽑아 제외 목록을 만든다."""
    used = set()
    for path in file_paths:
        if not os.path.exists(path):
            print(f"    [경고] --exclude-file '{path}' 파일을 찾을 수 없습니다. 건너뜁니다.")
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r"photo-[a-zA-Z0-9]+-[a-zA-Z0-9]+", text):
            used.add(m.group(0))
        for m in re.finditer(r"pexels-photo-\d+", text):
            used.add(m.group(0))
    return used


def resolve_image(placeholder, query_list, exclude_ids, used_in_this_run):
    """세미콜론으로 구분된 검색어를 순서대로 시도해서 사진을 찾는다."""
    for query in query_list:
        query = query.strip()
        if not query:
            continue
        try:
            results, used_query = ai.search_all_sources_with_fallback(query)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            print(f"    [경고] '{query}' 검색 실패(HTTP {status}). 다음 검색어로 넘어갑니다.")
            continue
        except requests.exceptions.RequestException as e:
            print(f"    [경고] '{query}' 검색 중 네트워크 오류: {e}. 다음 검색어로 넘어갑니다.")
            continue

        combined_exclude = exclude_ids | used_in_this_run
        candidates = [
            p for p in results
            if photo_identifier(p.get("regular_url")) not in combined_exclude
        ]
        pool = candidates if candidates else results
        photo = ai.pick_best_photo(pool)
        if not photo:
            continue

        print(f"    [{placeholder}] 검색어 '{query}' -> {photo['source']}: {photo['regular_url']}")
        print(f"        촬영자: {photo['photographer_name']} | alt: {photo.get('alt_description')}")
        return photo, used_query

    print(f"    [안내] [{placeholder}] 자리는 어떤 검색어로도 사진을 찾지 못했습니다. 비워둡니다.")
    return None, None


def build_labels_that_fit(service, blog_id, post_id, title, content, labels):
    """라벨을 전부 넣어보고, 실패하면 개수를 이진 탐색으로 줄여가며
    실제로 들어가는 최대 라벨 조합을 찾는다."""
    if len(labels) > MAX_LABELS_HARD_CAP:
        print(f"    [안내] 라벨이 {len(labels)}개라 {MAX_LABELS_HARD_CAP}개로 먼저 줄입니다 "
              f"(Blogger API 제한으로 확인된 값).")
        labels = labels[:MAX_LABELS_HARD_CAP]

    def try_labels(subset):
        try:
            service.posts().update(
                blogId=blog_id, postId=post_id,
                body={"title": title, "content": content, "labels": subset},
                publish=False,
            ).execute()
            return True
        except HttpError:
            return False

    if not labels:
        return []

    if try_labels(labels):
        return labels

    print("    [안내] 라벨 전체가 한 번에 안 들어가서, 실제로 들어가는 최대 개수를 찾습니다...")
    lo, hi = 0, len(labels)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if try_labels(labels[:mid]):
            lo = mid
        else:
            hi = mid - 1

    final_labels = labels[:lo]
    if lo < len(labels):
        dropped = labels[lo:]
        print(f"    [안내] 최종적으로 {lo}개까지 성공. 제외된 라벨: {dropped}")
    if final_labels:
        try_labels(final_labels)  # 마지막으로 확실히 반영
    return final_labels


def main():
    parser = argparse.ArgumentParser(
        description="새집일기 블로그 전용 발행 스크립트 (항상 임시저장/draft)"
    )
    parser.add_argument("--title", required=True, help="글 제목")
    parser.add_argument("--body", required=True, help="본문 HTML 파일 경로 ([[IMAGE_N]] 자리 포함)")
    parser.add_argument("--permalink", default=None, help="커스텀 URL 슬러그 (영문, 선택)")
    parser.add_argument("--labels", default="", help="쉼표로 구분한 라벨 목록")
    parser.add_argument("--image", nargs=2, action="append", default=[],
                         metavar=("PLACEHOLDER", "QUERIES"),
                         help='예: --image IMAGE_1 "query a;query b"')
    parser.add_argument("--exclude-file", action="append", default=[],
                         help="이미지 중복을 피할 기존 글 파일 (여러 번 지정 가능)")
    parser.add_argument("--dry-run", action="store_true",
                         help="실제로 발행하지 않고 결과만 미리 본다")
    args = parser.parse_args()

    if not os.path.exists(args.body):
        print(f"[오류] 본문 파일 '{args.body}'을 찾을 수 없습니다.")
        sys.exit(1)

    with open(args.body, encoding="utf-8") as f:
        content = f.read()

    labels = [x.strip() for x in args.labels.split(",") if x.strip()]

    print("=" * 70)
    print(f"대상 블로그: 새집일기 ({SAEZIP_BLOG_ID})")
    if SAEZIP_BLOG_ID == TRAVEL_BLOG_ID_TO_AVOID:
        print("[치명적 오류] SAEZIP_BLOG_ID가 여행 블로그 ID와 같습니다. 발행을 중단합니다.")
        sys.exit(1)
    print(f"제목: {args.title}")
    print(f"라벨: {labels}")
    print("=" * 70)

    # 1) 이미지 검색
    exclude_ids = extract_used_photo_ids(args.exclude_file)
    if exclude_ids:
        print(f"\n중복 방지 대상 사진 ID {len(exclude_ids)}개 로드 완료.\n")

    print("이미지 검색을 시작합니다...")
    used_in_this_run = set()
    report_rows = []
    for placeholder, query_str in args.image:
        query_list = query_str.split(";")
        photo, used_query = resolve_image(placeholder, query_list, exclude_ids, used_in_this_run)
        if not photo:
            continue
        used_in_this_run.add(photo_identifier(photo["regular_url"]))
        ai.trigger_download_event(photo)
        alt_text = ai.resolve_alt_text(photo, used_query or query_list[0])
        source_label = "Unsplash" if photo["source"] == "unsplash" else "Pexels"
        block = (
            f'<img src="{photo["regular_url"]}" alt="{alt_text}" '
            f'style="width:100%;height:auto;border-radius:10px;">\n'
            f'<p style="font-size:0.85em;color:#888;text-align:center;">'
            f'Photo by {photo["photographer_name"]} on {source_label}</p>'
        )
        tag = f"[[{placeholder}]]"
        if tag not in content:
            print(f"    [경고] 본문에 {tag} 자리가 없습니다.")
            continue
        content = content.replace(tag, block)
        report_rows.append((placeholder, photo["regular_url"], photo["photographer_name"], alt_text))

    remaining = re.findall(r"\[\[IMAGE_\d+\]\]", content)
    if remaining:
        print(f"\n[안내] 아직 채워지지 않은 이미지 자리: {remaining}")

    if args.dry_run:
        print("\n--dry-run 모드라 실제로 발행하지 않습니다. 최종 본문 미리보기:\n")
        print(content[:2000], "..." if len(content) > 2000 else "")
        return

    # 2) Blogger 발행 (본문 먼저, 라벨은 이어서 — 대용량 요청 시 400 오류 회피)
    creds = pb.get_credentials()
    service = build("blogger", "v3", credentials=creds)

    post_body = {"title": args.title, "content": content}
    if args.permalink:
        post_body["url"] = f"https://saezip-diary.blogspot.com/2026/07/{args.permalink}.html"

    print("\nBlogger에 임시저장(draft) 글을 생성합니다 (본문만 먼저)...")
    try:
        result = service.posts().insert(blogId=SAEZIP_BLOG_ID, body=post_body, isDraft=True).execute()
    except HttpError as e:
        if args.permalink:
            print(f"    [경고] 커스텀 퍼머링크 포함 발행 실패({e}). 퍼머링크 없이 재시도합니다.")
            post_body.pop("url", None)
            result = service.posts().insert(blogId=SAEZIP_BLOG_ID, body=post_body, isDraft=True).execute()
        else:
            print(f"[오류] 발행 실패: {e}")
            sys.exit(1)

    post_id = result.get("id")
    print(f"본문 발행 완료. postId={post_id}, status={result.get('status')}")

    final_labels = []
    if labels:
        print("\n라벨을 추가합니다...")
        final_labels = build_labels_that_fit(service, SAEZIP_BLOG_ID, post_id, args.title, content, labels)

    print("\n" + "=" * 70)
    print("완료 리포트")
    print("=" * 70)
    print(f"postId: {post_id}")
    print(f"요청한 퍼머링크: {args.permalink or '(지정 안 함)'}")
    print("  주의: draft 상태에서는 Blogger가 실제 반영 여부를 보여주지 않습니다.")
    print("  직접 게시하시기 전에 Blogger 편집 화면에서 링크 설정을 확인해 주세요.")
    print(f"draft 확인 링크: https://saezip-diary.blogspot.com/ (관리자 페이지 > 임시글 목록)")
    print(f"최종 라벨({len(final_labels)}개): {final_labels}")
    if len(labels) > len(final_labels):
        print(f"  [안내] 요청한 라벨 {len(labels)}개 중 {len(labels) - len(final_labels)}개가 빠졌습니다.")
    print("\n이미지:")
    for placeholder, url, photographer, alt in report_rows:
        print(f"  [{placeholder}] {url}")
        print(f"    촬영자: {photographer} | alt: {alt}")
    if remaining:
        print(f"\n[안내] 채워지지 않은 자리: {remaining}")


if __name__ == "__main__":
    main()
