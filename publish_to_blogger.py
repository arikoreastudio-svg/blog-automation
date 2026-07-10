#!/usr/bin/env python3
"""
publish_to_blogger.py
article_with_images.md를 읽어 블로그용 HTML로 변환한 뒤,
Blogger API v3로 내 블로그에 '임시저장(draft)' 상태로 올린다.

동작:
  1. article_with_images.md를 읽는다.
  2. 첫 번째 H1을 글 제목으로, 나머지를 본문으로 분리한다.
  3. 본문 마크다운을 HTML로 변환하고, 이미지/표/링크/강조/사진 출처 등이
     블로그에서 보기 좋도록 인라인 스타일을 입힌다.
  4. Google OAuth로 로그인한 뒤(최초 1회만 브라우저 필요), Blogger API v3로
     draft(임시저장) 글을 생성한다.
"""

import os
import re
import sys
import argparse

try:
    import markdown as md
except ImportError:
    print("markdown 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install markdown")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    print("beautifulsoup4 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install beautifulsoup4")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("python-dotenv 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install python-dotenv")
    sys.exit(1)

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("Google API 라이브러리가 필요합니다. 다음 명령으로 설치하세요:")
    print("  pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)


load_dotenv()

DEFAULT_SOURCE_FILE = "article_with_images.md"
TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/blogger"]

CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET")
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")


# ---------------------------------------------------------------------------
# 1. 마크다운 -> 블로그용 HTML 변환
# ---------------------------------------------------------------------------

def split_title_and_body(content, source_file):
    """첫 번째 H1을 글 제목으로 분리하고, 나머지를 본문 마크다운으로 반환한다."""
    match = re.search(r"^#\s+(.+?)\s*$", content, re.MULTILINE)
    if not match:
        print(f"[오류] '{source_file}'에서 H1(# 제목)을 찾지 못했습니다.")
        sys.exit(1)
    title = match.group(1).strip()
    body = content[:match.start()] + content[match.end():]
    return title, body.strip()


def _first_content_tag(p_tag):
    """<p> 태그의 첫 실제 자식 태그를 반환 (공백 텍스트는 건너뜀)."""
    for child in p_tag.contents:
        if isinstance(child, NavigableString) and not child.strip():
            continue
        return child
    return None


def _is_caption_paragraph(p_tag):
    """<p><em>...</em></p> 형태(사진 출처, 안내 문구)인지 확인한다."""
    contents = [c for c in p_tag.contents if not (isinstance(c, NavigableString) and not c.strip())]
    return len(contents) == 1 and getattr(contents[0], "name", None) == "em"


def _is_pros_cons_paragraph(p_tag):
    """**Pros:** / **Cons:** 로 시작하는 문단인지 확인한다."""
    first = _first_content_tag(p_tag)
    if first is None or getattr(first, "name", None) != "strong":
        return False
    text = first.get_text(strip=True)
    return text in ("Pros:", "Cons:")


def markdown_to_blog_html(body_md):
    # "**Pros:** ...\n**Cons:** ..." 처럼 빈 줄 없이 붙어 있으면 마크다운이 한 문단으로
    # 합쳐버리므로, Cons 줄 앞에 빈 줄을 넣어 별도 문단으로 분리한다.
    body_md = re.sub(r"\n(\*\*Cons:\*\*)", r"\n\n\1", body_md)

    raw_html = md.markdown(body_md, extensions=["tables"])
    soup = BeautifulSoup(raw_html, "html.parser")

    # 표는 가로 스크롤 가능한 래퍼로 감싸고, 보기 좋게 스타일링한다.
    for table in soup.find_all("table"):
        table["style"] = "width:100%;border-collapse:collapse;font-size:14px;margin:8px 0;"
        for th in table.find_all("th"):
            th["style"] = "text-align:left;padding:10px 12px;background:#f4f4f2;border:1px solid #ddd;"
        for td in table.find_all("td"):
            td["style"] = "padding:10px 12px;border:1px solid #ddd;vertical-align:top;"
        wrapper = soup.new_tag("div", style="overflow-x:auto;margin:20px 0 28px;")
        table.wrap(wrapper)

    for h2 in soup.find_all("h2"):
        h2["style"] = ("font-size:22px;font-weight:700;margin:40px 0 14px;"
                        "padding-bottom:8px;border-bottom:2px solid #eee;color:#111;")

    for img in soup.find_all("img"):
        img["style"] = "max-width:100%;height:auto;display:block;margin:28px auto 6px;border-radius:4px;"

    for a in soup.find_all("a"):
        a["style"] = "color:#a8402a;text-decoration:underline;"

    for p in soup.find_all("p"):
        if _is_caption_paragraph(p):
            p["style"] = "font-size:13px;color:#888;margin:-6px 0 24px;text-align:center;"
        elif _is_pros_cons_paragraph(p):
            p["style"] = ("font-size:14.5px;color:#555;margin:0 0 8px;"
                           "padding-left:12px;border-left:3px solid #ddd;")
        else:
            p["style"] = "font-size:16px;line-height:1.75;margin:0 0 18px;color:#222;"

    body_html = str(soup)

    wrapped = (
        '<div style="font-family:Georgia,\'Times New Roman\',serif;'
        'max-width:720px;margin:0 auto;color:#222;">'
        f"{body_html}"
        "</div>"
    )
    return wrapped


# ---------------------------------------------------------------------------
# 2. Google OAuth 인증
# ---------------------------------------------------------------------------

def print_env_setup_guide():
    print("""
[.env 설정 방법]
프로젝트 폴더(blog-automation)의 .env 파일에 아래 세 줄을 추가하세요:

   BLOGGER_CLIENT_ID=여기에_Client_ID
   BLOGGER_CLIENT_SECRET=여기에_Client_Secret
   BLOGGER_BLOG_ID=여기에_블로그_ID

발급 방법:
1. https://console.cloud.google.com/ 에서 프로젝트를 만들고
   'Blogger API v3'를 사용 설정(Enable)하세요.
2. '사용자 인증 정보(Credentials)' > 'OAuth 클라이언트 ID 만들기'에서
   애플리케이션 유형을 반드시 '데스크톱 앱(Desktop app)'으로 선택하세요.
3. 생성된 Client ID와 Client Secret을 위 형식대로 .env에 붙여넣으세요.
4. OAuth 동의 화면이 '테스트' 상태라면, 로그인에 사용할 본인 구글 계정을
   '테스트 사용자'로 추가해야 로그인 시 차단되지 않습니다.
5. 블로그 ID는 Blogger 관리자 페이지 주소나
   '설정 > 기본사항'에서 확인할 수 있습니다 (숫자로 된 ID).
""")


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"[경고] 저장된 토큰 파일을 읽는 데 실패했습니다({e}). 새로 로그인합니다.")
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            print("저장된 로그인 정보로 토큰을 자동 갱신했습니다.")
        except Exception as e:
            print(f"[경고] 토큰 자동 갱신에 실패했습니다({e}). 다시 로그인합니다.")
            creds = None

    if not creds or not creds.valid:
        print("\n브라우저를 열어 구글 로그인/승인을 진행합니다 (최초 1회만 필요합니다)...")
        client_config = {
            "installed": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# 3. Blogger API 발행
# ---------------------------------------------------------------------------

def _handle_http_error(e):
    print(f"\n[오류] Blogger API 요청이 실패했습니다 (HTTP {e.resp.status}).")
    if e.resp.status == 404:
        print("  블로그 ID 또는 글 ID가 잘못됐을 수 있습니다. .env의 BLOGGER_BLOG_ID나 --post-id를 다시 확인해 주세요.")
    elif e.resp.status == 403:
        print("  이 계정이 해당 블로그의 관리자가 아니거나, Blogger API 사용 설정이 안 됐을 수 있습니다.")
    else:
        print(f"  상세: {e}")
    sys.exit(1)


def publish_draft(title, html_content, creds):
    """새 임시저장(draft) 글을 만든다."""
    service = build("blogger", "v3", credentials=creds)
    post_body = {"title": title, "content": html_content}
    try:
        result = service.posts().insert(blogId=BLOG_ID, body=post_body, isDraft=True).execute()
    except HttpError as e:
        _handle_http_error(e)
    return result


def update_draft(post_id, title, html_content, creds):
    """기존 글(주로 임시저장 글)을 같은 postId로 덮어써서, 새 draft가 따로
    생기지 않고 하나의 글만 계속 갱신되게 한다. publish 파라미터를 주지
    않으면 기존 상태(임시저장이면 임시저장)가 그대로 유지된다."""
    service = build("blogger", "v3", credentials=creds)
    post_body = {"title": title, "content": html_content}
    try:
        result = service.posts().update(blogId=BLOG_ID, postId=post_id, body=post_body).execute()
    except HttpError as e:
        _handle_http_error(e)
    return result


def main():
    parser = argparse.ArgumentParser(description="완성된 마크다운 글을 Blogger에 임시저장으로 발행")
    parser.add_argument("source", nargs="?", default=DEFAULT_SOURCE_FILE,
                         help=f"발행할 마크다운 파일 (기본값: {DEFAULT_SOURCE_FILE})")
    parser.add_argument("--post-id", default=None,
                         help="이 글 ID로 기존 글(주로 임시저장 글)을 덮어쓴다. "
                              "지정하지 않으면 새 임시저장 글을 만든다.")
    args = parser.parse_args()
    source_file = args.source

    missing = [name for name, val in [
        ("BLOGGER_CLIENT_ID", CLIENT_ID),
        ("BLOGGER_CLIENT_SECRET", CLIENT_SECRET),
        ("BLOGGER_BLOG_ID", BLOG_ID),
    ] if not val]
    if missing:
        print(f"[오류] .env에서 다음 값을 찾지 못했습니다: {', '.join(missing)}")
        print_env_setup_guide()
        sys.exit(1)

    if not os.path.exists(source_file):
        print(f"[오류] '{source_file}' 파일을 찾을 수 없습니다. 같은 폴더에서 실행해 주세요.")
        sys.exit(1)

    with open(source_file, encoding="utf-8") as f:
        content = f.read()

    title, body_md = split_title_and_body(content, source_file)
    print(f"글 제목: {title}")

    html_content = markdown_to_blog_html(body_md)
    print(f"HTML 변환 완료 ({len(html_content):,}자)")

    try:
        creds = get_credentials()
    except Exception as e:
        print(f"[오류] 구글 로그인에 실패했습니다: {e}")
        print("Client ID/Secret이 올바른지, OAuth 동의 화면에 테스트 사용자로 등록됐는지 확인해 주세요.")
        sys.exit(1)

    if args.post_id:
        print(f"\nBlogger의 기존 글(ID: {args.post_id})을 새 내용으로 덮어씁니다...")
        result = update_draft(args.post_id, title, html_content, creds)
        print("\n완료! 기존 글을 업데이트했습니다. (새 draft가 따로 생기지 않았습니다)")
    else:
        print("\nBlogger에 임시저장(draft) 글을 생성합니다...")
        result = publish_draft(title, html_content, creds)
        print("\n완료! 임시저장 글이 생성됐습니다.")

    print(f"  글 ID: {result.get('id')}")
    print(f"  링크: {result.get('url', '(초안은 목록에서 확인하세요)')}")
    print("  Blogger 관리자 페이지의 '임시글' 목록에서 확인 후, 직접 '게시' 버튼을 눌러주세요.")


if __name__ == "__main__":
    main()
