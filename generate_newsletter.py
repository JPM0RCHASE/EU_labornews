# -*- coding: utf-8 -*-
"""
인사 노무 브리핑 - 주간 뉴스레터 생성 및 Maily 발송
매주 일요일 UTC 22:00 (= 월요일 KST 07:00) 자동 실행

섹션 구성:
  1. 이번 주 꼭 읽어야 할 뉴스 Top 3 + JP 인사이트
  2. 정부·노동부·국회 정책동향
  3. JP's Weekly Insight — 이번 주 가장 많이 받은 질문
  4. 5인 미만 사업장 집중 노동법 이슈
  CTA → 카카오톡 오픈채팅

발행: Maily API (https://maily.so)
저장: newsletter/ 폴더 (날짜별 HTML)
"""
import os
import re
import json
import socket
import shutil
import threading
import http.server
import socketserver
import requests
import urllib.parse
from datetime import datetime, timezone, timedelta
import anthropic

# ── 환경 변수 ─────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
MAILY_API_KEY        = os.environ.get("MAILY_API_KEY", "")
MAILY_PROJECT_ID     = os.environ.get("MAILY_PROJECT_ID", "")
KAKAO_JS_KEY         = os.environ.get("KAKAO_JS_KEY", "")
KAKAO_CHAT_URL       = "https://open.kakao.com/o/gOaNVSwi"   # 공인노무사JP 오픈채팅방
TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID     = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── 날짜 설정 ─────────────────────────────────────────
KST        = timezone(timedelta(hours=9))
TODAY      = datetime.now(KST)
DATE_STR   = TODAY.strftime("%Y%m%d")
DATE_LABEL = TODAY.strftime("%Y. %m. %d.")
WEEKDAY    = ["월", "화", "수", "목", "금", "토", "일"][TODAY.weekday()]
WEEK_NUM   = (TODAY.day - 1) // 7 + 1
WEEK_KO    = ["첫", "둘", "셋", "넷", "다섯"][min(WEEK_NUM - 1, 4)]
WEEK_LABEL = f"{TODAY.year}년 {TODAY.month}월 {WEEK_KO}째주"

os.makedirs("newsletter", exist_ok=True)
OUTPUT      = f"newsletter/newsletter_{DATE_STR}.html"
LATEST      = "newsletter/latest.html"
PNG_OUTPUT  = f"newsletter/newsletter_{DATE_STR}.png"
PNG_LATEST  = "newsletter/latest.png"
VERCEL_URL  = f"https://eu-labornews.vercel.app/newsletter/newsletter_{DATE_STR}.html"
REPO_ROOT   = os.path.dirname(os.path.abspath(__file__))

print(f"[{DATE_LABEL}] 인사 노무 브리핑 뉴스레터 생성 시작...")

# ── Naver 뉴스 수집 ───────────────────────────────────
KEYWORDS = [
    # 섹션 1: 노동·HR 핵심 이슈
    "노란봉투법", "노조법 개정", "원청 사용자성",
    "삼성전자 노사", "현대차 임금협상", "최저임금",
    "부당해고 노동위원회", "임금체불", "산업재해 중대재해",
    "고용노동부 정책", "노동법 개정안", "직장내 괴롭힘",
    # 섹션 2: 정부/노동부/국회 정책동향
    "고용노동부 정책 고시", "고용노동부 지침 행정해석",
    "고용노동부 단속 과태료", "국회 환경노동위원회",
    "노동법 개정안 입법", "정부 노동정책 발표",
    "노동부 행정해석", "국회 노동법 통과",
    # 섹션 4: 5인 미만 사업장
    "5인미만 사업장 노동법", "주휴수당 알바",
    "퇴직금 소상공인", "근로계약서 작성",
    "직원 해고 절차", "가짜 프리랜서 3.3",
]

nav_headers = {
    "X-Naver-Client-Id": NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}
seven_days_ago = TODAY - timedelta(days=7)
collected, seen = [], set()

MAJOR_MEDIA_DOMAINS = [
    "chosun.com", "joongang.co.kr", "donga.com",
    "hani.co.kr", "khan.co.kr",
    "kbs.co.kr", "mbc.co.kr", "sbs.co.kr", "jtbc.co.kr",
    "yonhapnews.co.kr", "yna.co.kr", "newsis.com",
]


def is_major_media(url: str) -> bool:
    return any(domain in url for domain in MAJOR_MEDIA_DOMAINS)


for kw in KEYWORDS:
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=nav_headers,
            params={"query": kw, "sort": "date", "display": 5},
            timeout=10,
        )
        for item in resp.json().get("items", []):
            try:
                pub_dt = datetime.strptime(
                    item.get("pubDate", ""), "%a, %d %b %Y %H:%M:%S %z"
                ).astimezone(KST)
                if pub_dt >= seven_days_ago:
                    title = re.sub(r"<[^>]+>", "", item.get("title", ""))
                    key = title[:20]
                    if key not in seen:
                        seen.add(key)
                        link = item.get("originallink") or item.get("link", "")
                        collected.append({
                            "title": title,
                            "link": link,
                            "description": re.sub(r"<[^>]+>", "", item.get("description", "")),
                            "pubDate": pub_dt.strftime("%Y.%m.%d"),
                            "keyword": kw,
                            "is_major": is_major_media(link),
                        })
            except Exception:
                continue
    except Exception as e:
        print(f"키워드 '{kw}' 오류: {e}")

# 메이저 언론사 기사 우선 정렬
collected.sort(key=lambda x: (0 if x["is_major"] else 1))
major_cnt = sum(1 for n in collected if n["is_major"])
print(f"7일 이내 뉴스 {len(collected)}건 수집 (메이저 언론사 {major_cnt}건)")
news_pool = collected[:30]

news_text = "\n\n".join([
    f"[{i+1}] {'★메이저 ' if n['is_major'] else ''}{n['title']}\n"
    f"날짜:{n['pubDate']} | 링크:{n['link']}\n"
    f"키워드:{n['keyword']}\n요약:{n['description']}"
    for i, n in enumerate(news_pool)
]) if news_pool else "수집된 뉴스 없음"

# ── Claude API 콘텐츠 생성 ────────────────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROMPT = f"""당신은 공인노무사 JP입니다. 오늘은 {DATE_LABEL} {WEEKDAY}요일, {WEEK_LABEL}입니다.
아래 수집된 뉴스를 바탕으로 주간 뉴스레터 콘텐츠를 JSON으로 생성하세요.

수집된 뉴스:
{news_text}

【생성 규칙】
1. 반드시 수집된 뉴스 목록에서만 선별할 것 (임의 생성 금지)
2. 없는 섹션은 공인노무사 JP 실무 인사이트로 대체 (url → https://laborjp.tistory.com)
3. 【섹션 중복 방지 — 최우선 규칙】
   STEP 1: section2_gov_policy 기사를 먼저 선택한다 (고용노동부·국회·정부 정책 관련 기사 우선)
   STEP 2: section1_top3 기사는 반드시 STEP 1에서 사용한 기사와 동일하거나 주제(토픽)가 겹치는 기사를 제외하고 선별한다. 두 섹션의 뉴스 주제는 절대 겹쳐서는 안 된다.
4. section1_top3 선별 시: ★메이저 표시된 조선·중앙·동아·한겨레·경향·KBS·MBC·SBS·JTBC·연합뉴스 기사를 최우선 선별. 메이저 기사 부족 시에만 다른 매체 사용
5. section3_weekly_insight의 질문 도출 근거도 메이저 언론사 기사를 우선 참고
6. JP's Weekly Insight Q&A는 수집 뉴스 기반으로 실제 받을 법한 질문 1개 작성
7. 모든 제목은 질문형 또는 실용적 표현 권장

JSON만 응답. 다른 텍스트 절대 금지:
{{
  "week_label": "{WEEK_LABEL}",
  "section1_top3": [
    {{
      "rank": 1,
      "source": "언론사명",
      "date": "2026.05.12",
      "url": "https://실제URL",
      "category": "주제분류",
      "title": "뉴스 제목",
      "summary": "2~3문장 핵심 요약",
      "insight": "공인노무사 JP 실무 시사점 2~3문장"
    }},
    {{"rank": 2, "source": "...", "date": "...", "url": "...", "category": "...", "title": "...", "summary": "...", "insight": "..."}},
    {{"rank": 3, "source": "...", "date": "...", "url": "...", "category": "...", "title": "...", "summary": "...", "insight": "..."}}
  ],
  "section2_gov_policy": {{
    "title": "정부·노동부·국회 정책동향",
    "sub_title": "이번 주 핵심 정책 이슈",
    "source": "언론사명 또는 공인노무사 JP",
    "date": "2026.05.12",
    "url": "https://실제URL 또는 https://laborjp.tistory.com",
    "policy_bullets": [
      "정책 동향 1 — 구체적 내용",
      "정책 동향 2",
      "정책 동향 3"
    ],
    "policy_insight": "정책 변화에 따른 실무 시사점 2~3문장"
  }},
  "section3_weekly_insight": {{
    "question": "이번 주 가장 많이 받은 질문을 한 문장으로",
    "answer_paragraphs": [
      "답변 단락 1 — 법적 근거 포함",
      "답변 단락 2 — 실무 적용 방법",
      "답변 단락 3 — 주의사항 또는 예외"
    ],
    "cta_line": "더 궁금한 점은 무료 상담으로 확인하세요."
  }},
  "section4_five_fewer": {{
    "title": "5인 미만 사업장 사장님 필독",
    "sub_title": "이번 주 핵심 쟁점",
    "source": "언론사명 또는 공인노무사 JP",
    "date": "2026.05.12",
    "url": "https://실제URL 또는 https://laborjp.tistory.com",
    "key_points": [
      "핵심 포인트 1 — 구체적 수치나 법조항 포함",
      "핵심 포인트 2",
      "핵심 포인트 3",
      "핵심 포인트 4"
    ],
    "action_tip": "즉시 실행 가능한 실무 조언 2~3문장"
  }}
}}"""

print("Claude API 호출 중...")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=6000,
    system=(
        "You are a Korean labor law expert (공인노무사 JP). "
        "Always respond with valid JSON only. No text outside JSON. "
        "Escape all special characters properly. "
        "All text content must be in Korean (UTF-8)."
    ),
    messages=[{"role": "user", "content": PROMPT}],
)
raw = response.content[0].text.strip()


def safe_parse(text: str) -> dict:
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        try:
            return json.loads(text[s: e + 1])
        except Exception:
            pass
    print("⚠ JSON 파싱 실패 — 기본 템플릿 사용")
    today_str = TODAY.strftime("%Y.%m.%d")
    return {
        "week_label": WEEK_LABEL,
        "section1_top3": [
            {
                "rank": i + 1,
                "source": "공인노무사 JP",
                "date": today_str,
                "url": "https://laborjp.tistory.com",
                "category": "노동법 실무",
                "title": f"이번 주 노동·HR 이슈 {i + 1}",
                "summary": "뉴스 수집 중 오류. 다음 주 브리핑을 확인해 주세요.",
                "insight": "구체적 사안은 공인노무사 JP에게 문의하세요.",
            }
            for i in range(3)
        ],
        "section2_gov_policy": {
            "title": "정부·노동부·국회 정책동향",
            "sub_title": "이번 주 핵심 정책 이슈",
            "source": "공인노무사 JP",
            "date": today_str,
            "url": "https://laborjp.tistory.com",
            "policy_bullets": [
                "고용노동부 정책 동향 모니터링 중",
                "국회 노동법 개정 현황 확인 필요",
                "행정해석 변경 사항 점검",
            ],
            "policy_insight": "정책 변화에 따른 실무 대응 방법은 카카오톡 오픈채팅에서 확인하세요.",
        },
        "section3_weekly_insight": {
            "question": "퇴직금을 분할해서 매월 지급해도 되나요?",
            "answer_paragraphs": [
                "근로기준법상 퇴직금은 퇴직 시 일시에 지급이 원칙입니다.",
                "다만 근로자 동의 시 분할 지급 약정이 가능하며, 서면 동의가 필요합니다.",
                "분할 지급 약정 없이 월급에 포함해 지급하면 퇴직금 선급이 무효화될 수 있습니다.",
            ],
            "cta_line": "더 궁금한 점은 무료 상담으로 확인하세요.",
        },
        "section4_five_fewer": {
            "title": "5인 미만 사업장 핵심 이슈",
            "sub_title": "이번 주 점검 포인트",
            "source": "공인노무사 JP",
            "date": today_str,
            "url": "https://laborjp.tistory.com",
            "key_points": [
                "근로계약서 필수 작성",
                "주휴수당 지급 의무 확인",
                "퇴직금 산정 기준 체크",
                "임금체불 예방 조치",
            ],
            "action_tip": "궁금한 사항은 카카오톡 오픈채팅에서 무료 상담을 신청하세요.",
        },
    }


data       = safe_parse(raw)
week_label = data.get("week_label", WEEK_LABEL)
top3       = data.get("section1_top3", [])
gov_policy = data.get("section2_gov_policy", {})
weekly_qa  = data.get("section3_weekly_insight", {})
five_fewer = data.get("section4_five_fewer", {})
print("뉴스레터 콘텐츠 생성 완료")

# ─────────────────────────────────────────────────────
# CSS: 모든 특수문자는 실제 유니코드 문자 사용
#      (CSS \XXXX 이스케이프는 Python 문자열에서 깨짐)
# ─────────────────────────────────────────────────────
CSS_NL = """
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,700;1,900&display=swap');
  @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #f2f2f2;
    font-family: 'Pretendard', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
    font-size: 15px; line-height: 1.75; color: #111;
  }
  .email-wrap { max-width: 600px; margin: 0 auto; background: #fff; }

  /* 상단 그린 바 */
  .top-bar { height: 5px; background: #1a6b3a; }

  /* 헤더 */
  .nl-header {
    padding: 28px 32px 20px;
    border-bottom: 2px solid #111;
    display: flex; align-items: flex-end; justify-content: space-between;
  }
  .nl-brand {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 28px; font-weight: 900; color: #111;
    letter-spacing: -.01em; line-height: 1;
  }
  .nl-brand span { color: #1a6b3a; }
  .nl-issue { font-size: 11px; color: #666; text-align: right; line-height: 1.6; }

  /* 히어로 */
  .nl-hero { padding: 32px 32px 28px; border-bottom: 2px solid #111; }
  .nl-hero-kicker {
    display: flex; align-items: center; gap: 10px;
    font-size: 10px; font-weight: 700; letter-spacing: .2em;
    color: #1a6b3a; text-transform: uppercase; margin-bottom: 14px;
  }
  .nl-hero-kicker::before,
  .nl-hero-kicker::after { content: ''; flex: 0 0 28px; height: 1.5px; background: #1a6b3a; }
  .nl-hero-title {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 32px; font-weight: 900; color: #111;
    line-height: 1.2; margin-bottom: 12px; word-break: keep-all;
  }
  .nl-hero-title em { color: #1a6b3a; font-style: italic; }
  .nl-hero-sub { font-size: 13px; color: #555; line-height: 1.8; }

  /* 섹션 공통 */
  .nl-section { padding: 32px 32px 24px; border-bottom: 2px solid #111; }

  /* Kicker 공통 */
  .kicker {
    display: flex; align-items: center; gap: 10px;
    font-size: 10px; font-weight: 700; letter-spacing: .2em;
    color: #1a6b3a; text-transform: uppercase; margin-bottom: 20px;
    white-space: nowrap;
  }
  .kicker::before { content: ''; flex: 0 0 20px; height: 1.5px; background: #1a6b3a; }
  .kicker::after  { content: ''; flex: 1;         height: 1.5px; background: #1a6b3a; }

  /* Section 01 전용 kicker: 1.5배 + Playfair Display */
  .kicker-s01 {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 15px; font-weight: 900;
    letter-spacing: .03em; text-transform: none;
  }
  .kicker-s01::before { flex: 0 0 24px; height: 2px; }
  .kicker-s01::after  { height: 2px; }

  /* 섹션 1: Top 3 카드 */
  .news-card-nl { border: 1px solid #ddd; margin-bottom: 18px; }
  .news-card-nl:last-child { margin-bottom: 0; }
  .nc-header {
    display: flex; align-items: center; gap: 10px;
    background: #fafafa; padding: 9px 14px; border-bottom: 1px solid #ddd;
  }
  .nc-rank { font-size: 11px; font-weight: 900; color: #1a6b3a; min-width: 22px; text-align: center; }
  .nc-source { font-size: 11px; color: #666; flex: 1; }
  .nc-date { font-size: 11px; color: #999; }
  .nc-body { padding: 16px 14px; }
  .nc-category {
    font-size: 10px; font-weight: 700; color: #1a6b3a;
    letter-spacing: .1em; text-transform: uppercase; margin-bottom: 6px;
  }
  .nc-title {
    font-size: 16px; font-weight: 800; color: #111;
    line-height: 1.4; margin-bottom: 10px; word-break: keep-all;
  }
  .nc-summary { font-size: 13px; color: #444; line-height: 1.8; margin-bottom: 12px; }
  .nc-insight { border-left: 2px solid #1a6b3a; padding: 10px 12px; background: #f7fbf8; }
  .nc-insight-label {
    font-size: 9px; font-weight: 700; color: #1a6b3a;
    letter-spacing: .18em; text-transform: uppercase; margin-bottom: 4px;
  }
  .nc-insight-text { font-size: 12px; color: #333; line-height: 1.8; }
  .nc-footer {
    padding: 8px 14px; background: #fafafa; border-top: 1px solid #ddd; text-align: right;
  }
  .nc-link { font-size: 12px; font-weight: 700; color: #1a6b3a; text-decoration: none; }

  /* 공통 구분선 (Wired식 굵은 2px 블랙) */
  .section-divider { border: none; border-top: 2px solid #111; margin-bottom: 14px; }

  /* 섹션 2: 정부·노동부·국회 */
  .gov-card { border: 1px solid #ddd; padding: 20px; margin-bottom: 12px; }
  .gov-badge {
    display: inline-block; background: #111; color: #fff;
    font-size: 10px; font-weight: 700; padding: 3px 9px;
    letter-spacing: .06em; margin-bottom: 10px;
  }
  .gov-title { font-size: 17px; font-weight: 900; color: #111; margin-bottom: 2px; word-break: keep-all; }
  .gov-sub { font-size: 12px; color: #666; margin-bottom: 14px; }
  .gov-bullets { list-style: none; margin-bottom: 16px; }
  .gov-bullets li {
    font-size: 13px; color: #222; padding: 9px 0 9px 18px;
    border-bottom: 1px solid #e0e0e0; position: relative; line-height: 1.7;
  }
  .gov-bullets li:last-child { border-bottom: none; }
  .gov-bullets li::before {
    content: '▸';
    position: absolute; left: 0; color: #1a6b3a; font-size: 12px; top: 10px;
  }
  .gov-insight { border-left: 2px solid #111; padding: 10px 12px; background: #f8f8f8; font-size: 12px; color: #333; line-height: 1.8; }
  .gov-insight-label { font-size: 9px; font-weight: 700; color: #555; letter-spacing: .16em; text-transform: uppercase; margin-bottom: 4px; }

  /* 섹션 3: JP's Weekly QA */
  .qa-wrap { border: 1.5px solid #111; padding: 24px; margin-bottom: 12px; background: #fff; }
  .qa-label { font-size: 10px; font-weight: 700; color: #1a6b3a; letter-spacing: .2em; text-transform: uppercase; margin-bottom: 12px; }
  .qa-q {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 18px; font-weight: 700; color: #111;
    line-height: 1.45; margin-bottom: 18px; word-break: keep-all;
  }
  .qa-open-q  { color: #1a6b3a; font-size: 26px; line-height: 0; vertical-align: -5px; font-family: Georgia, serif; }
  .qa-close-q { color: #1a6b3a; font-size: 26px; line-height: 0; vertical-align: -5px; font-family: Georgia, serif; }
  .qa-a-label { font-size: 10px; font-weight: 700; color: #555; margin-bottom: 10px; letter-spacing: .12em; }
  .qa-paragraph { font-size: 13px; color: #333; line-height: 1.9; margin-bottom: 10px; }
  .qa-paragraph:last-of-type { margin-bottom: 0; }
  .qa-cta { margin-top: 18px; padding-top: 16px; border-top: 1px solid #e0e0e0; font-size: 13px; }

  /* 섹션 4: 5인 미만 */
  .five-card { border: 1px solid #ddd; padding: 20px; margin-bottom: 12px; }
  .five-badge {
    display: inline-block; background: #1a6b3a; color: #fff;
    font-size: 10px; font-weight: 700; padding: 3px 9px;
    letter-spacing: .06em; margin-bottom: 10px;
  }
  .five-title { font-size: 17px; font-weight: 900; color: #111; margin-bottom: 2px; word-break: keep-all; }
  .five-sub { font-size: 12px; color: #666; margin-bottom: 14px; }
  .five-points { list-style: none; margin-bottom: 16px; }
  .five-points li {
    font-size: 13px; color: #222; padding: 9px 0 9px 22px;
    border-bottom: 1px solid #e0e0e0; position: relative; line-height: 1.7;
  }
  .five-points li:last-child { border-bottom: none; }
  .five-points li::before {
    content: '✓';
    position: absolute; left: 0; color: #1a6b3a; font-weight: 900; font-size: 12px; top: 10px;
  }
  .five-tip { border-left: 2px solid #1a6b3a; padding: 10px 12px; background: #f7fbf8; font-size: 12px; color: #333; line-height: 1.8; }
  .five-tip-label { font-size: 9px; font-weight: 700; color: #1a6b3a; letter-spacing: .16em; text-transform: uppercase; margin-bottom: 4px; }

  /* 공유 바: 페이지 맨 하단 고정 없음, 절반 크기 */
  .share-bar { background: #111; padding: 7px 20px 6px; }
  .share-row { display: flex; gap: 8px; }
  .share-btn {
    flex: 1; display: flex; align-items: center; justify-content: center;
    gap: 4px; padding: 7px 0; font-size: 12px; font-weight: 700;
    border: none; cursor: pointer; text-decoration: none; transition: opacity .2s;
  }
  .share-btn:hover { opacity: .85; }
  .share-copy  { background: #333; color: #fff; }
  .share-kakao { background: #FEE500; color: #3A1D1D; }
  #nl-copy-msg { font-size: 10px; color: #7dbb9a; display: none; text-align: center; padding-top: 4px; }

  /* 푸터 */
  .nl-footer {
    padding: 18px 32px;
    border-top: 2px solid #111;
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 8px; background: #fff;
  }
  .nf-left { font-size: 11px; color: #555; line-height: 1.7; }
  .nf-brand { font-weight: 700; color: #111; }
  .nf-right a { font-size: 12px; font-weight: 700; color: #1a6b3a; text-decoration: none; }

  /* 반응형 */
  @media (max-width: 600px) {
    .nl-header, .nl-hero, .nl-section, .nl-footer { padding-left: 16px; padding-right: 16px; }
    .nl-hero-title { font-size: 26px; }
    .nl-header { flex-direction: column; align-items: flex-start; gap: 6px; }
    .nl-issue { text-align: left; }
  }
"""


# ── render 함수: 실제 한글 문자 사용, HTML 엔티티 없음 ─
def render_top3(items: list) -> str:
    out = ""
    for n in items:
        out += (
            '<div class="news-card-nl">'
            '<div class="nc-header">'
            f'<span class="nc-rank">No.{n["rank"]}</span>'
            f'<span class="nc-source">📰 {n["source"]}</span>'
            f'<span class="nc-date">{n["date"]}</span>'
            "</div>"
            '<div class="nc-body">'
            f'<div class="nc-category">{n["category"]}</div>'
            f'<h3 class="nc-title">{n["title"]}</h3>'
            f'<p class="nc-summary">{n["summary"]}</p>'
            '<div class="nc-insight">'
            '<div class="nc-insight-label">JP Insight</div>'
            f'<div class="nc-insight-text">{n["insight"]}</div>'
            "</div>"
            "</div>"
            '<div class="nc-footer">'
            f'<a class="nc-link" href="{n["url"]}" target="_blank">원문 보기 →</a>'
            "</div>"
            "</div>"
        )
    return out


def render_gov_policy(s: dict) -> str:
    buls = "".join(f"<li>{b}</li>" for b in s.get("policy_bullets", []))
    return (
        '<div class="gov-card">'
        '<div class="gov-badge">정부·노동부·국회</div>'
        f'<div class="gov-title">{s.get("title", "정부·노동부·국회 정책동향")}</div>'
        f'<div class="gov-sub">{s.get("sub_title", "")} · {s.get("source", "")} · {s.get("date", "")}</div>'
        '<hr class="section-divider">'
        f'<ul class="gov-bullets">{buls}</ul>'
        '<div class="gov-insight">'
        '<div class="gov-insight-label">실무 대응 포인트</div>'
        f'{s.get("policy_insight", "")}'
        "</div>"
        "</div>"
    )


def render_qa(qa: dict) -> str:
    paras = "".join(
        f'<p class="qa-paragraph">{p}</p>' for p in qa.get("answer_paragraphs", [])
    )
    return (
        '<div class="qa-wrap">'
        '<div class="qa-label">JP\'s Weekly Insight · 이번 주 가장 많이 받은 질문</div>'
        '<div class="qa-q">'
        '<span class="qa-open-q">“</span>'
        f'{qa.get("question", "")}'
        '<span class="qa-close-q">”</span>'
        "</div>"
        '<div class="qa-a-label">공인노무사 JP의 답변</div>'
        f"{paras}"
        '<div class="qa-cta">💬 '
        '<a href="https://open.kakao.com/o/gOaNVSwi" target="_blank" '
        'style="color:#1a6b3a;text-decoration:none;font-weight:700;">'
        "카카오톡 오픈채팅으로 무료 상담하기 →</a></div>"
        "</div>"
    )


def render_five_fewer(s: dict) -> str:
    pts = "".join(f"<li>{p}</li>" for p in s.get("key_points", []))
    return (
        '<div class="five-card">'
        '<div class="five-badge">5인 미만 사업장 필독</div>'
        f'<div class="five-title">{s.get("title", "5인 미만 핵심 이슈")}</div>'
        f'<div class="five-sub">{s.get("sub_title", "")} · {s.get("source", "")} · {s.get("date", "")}</div>'
        '<hr class="section-divider">'
        f'<ul class="five-points">{pts}</ul>'
        '<div class="five-tip">'
        '<div class="five-tip-label">즉시 실행 팁</div>'
        f'{s.get("action_tip", "")}'
        "</div>"
        "</div>"
    )


# ── 카카오 SDK: 키가 있을 때만 로드 ──────────────────
# SDK 없어도 공유 버튼은 항상 활성 (fallback: 오픈채팅방 직접 열기)
kakao_sdk_tag = (
    '<script src="https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js"'
    ' integrity="sha384-TiCUE00h649CAMonG018J2ujOgDKW/kVWlChEuu4jK2vxfAAD0eZxzCKakxg55G4"'
    ' crossorigin="anonymous"></script>'
) if KAKAO_JS_KEY else ""

kakao_init_js = (
    f'if (typeof Kakao !== "undefined" && !Kakao.isInitialized()) '
    f'{{ Kakao.init("{KAKAO_JS_KEY}"); }}'
) if KAKAO_JS_KEY else ""

# 버튼은 항상 활성: SDK 있으면 뉴스레터 공유, 없으면 오픈채팅방으로 이동
kakao_btn = '<button class="share-btn share-kakao" onclick="nlShareKakao()">💬 카카오톡</button>'

# ── 최종 HTML 조립 ────────────────────────────────────
NEWSLETTER_HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="ko">\n'
    "<head>\n"
    '<meta charset="UTF-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    f"<title>인사 노무 브리핑 {week_label} | 공인노무사JP의 뉴스레터</title>\n"
    f'<meta name="description" content="{week_label} 노동·HR·정책 핵심 이슈. 공인노무사JP의 주간 뉴스레터.">\n'
    f'<meta property="og:title" content="인사 노무 브리핑 {week_label} | 공인노무사JP">\n'
    '<meta property="og:type" content="article">\n'
    f'<meta property="og:url" content="{VERCEL_URL}">\n'
    f"{kakao_sdk_tag}\n"
    f"<style>{CSS_NL}</style>\n"
    "</head>\n"
    "<body>\n"
    '<div class="email-wrap">\n'

    # 상단 그린 바
    '<div class="top-bar"></div>\n'

    # 헤더
    '<div class="nl-header">\n'
    '  <div class="nl-brand">인사 노무 <span>브리핑</span></div>\n'
    '  <div class="nl-issue">\n'
    "    공인노무사JP의 뉴스레터<br>\n"
    f"    {DATE_LABEL} · {week_label}\n"
    "  </div>\n"
    "</div>\n"

    # 히어로
    '<div class="nl-hero">\n'
    f'  <div class="nl-hero-kicker">{week_label} · 주간 뉴스레터</div>\n'
    '  <h1 class="nl-hero-title">이번 주 꼭 알아야 할<br><em>Labor &amp; HR</em> 이슈</h1>\n'
    '  <p class="nl-hero-sub">공인노무사 JP가 선별한 핵심 뉴스 · 정책동향 · 5인 미만 이슈 · JP 인사이트</p>\n'
    "</div>\n"

    # 섹션 1
    '<div class="nl-section">\n'
    '  <div class="kicker kicker-s01">Section 01 &nbsp;·&nbsp; 이번 주 꼭 읽어야 할 뉴스 Top 3</div>\n'
    f"  {render_top3(top3)}\n"
    "</div>\n"

    # 섹션 2
    '<div class="nl-section">\n'
    '  <div class="kicker">Section 02 &nbsp;·&nbsp; 정부·노동부·국회 정책동향</div>\n'
    f"  {render_gov_policy(gov_policy)}\n"
    "</div>\n"

    # 섹션 3
    '<div class="nl-section">\n'
    "  <div class=\"kicker\">Section 03 &nbsp;&middot;&nbsp; JP's Weekly Insight</div>\n"
    f"  {render_qa(weekly_qa)}\n"
    "</div>\n"

    # 섹션 4
    '<div class="nl-section">\n'
    '  <div class="kicker">Section 04 &nbsp;·&nbsp; 5인 미만 사업장 집중 노동법 이슈</div>\n'
    f"  {render_five_fewer(five_fewer)}\n"
    "</div>\n"

    # 공유 바 (하단 고정 없음, 절반 크기)
    '<div class="share-bar">\n'
    '  <div class="share-row">\n'
    '    <button class="share-btn share-copy" onclick="nlCopyLink()">🔗 링크 복사</button>\n'
    f"    {kakao_btn}\n"
    "  </div>\n"
    '  <div id="nl-copy-msg">✅ 링크 복사됨!</div>\n'
    "</div>\n"

    # 푸터
    '<div class="nl-footer">\n'
    '  <div class="nf-left">\n'
    '    <div class="nf-brand">공인노무사JP의 뉴스레터</div>\n'
    "    본 뉴스레터는 정보 제공 목적으로 작성된 자료입니다.<br>\n"
    "    구체적인 사안은 전문가 상담을 권장합니다.<br>\n"
    "    Powered by Claude AI &middot; &copy; 2026 공인노무사 JP\n"
    "  </div>\n"
    '  <div class="nf-right">\n'
    '    <a href="https://open.kakao.com/o/gOaNVSwi" target="_blank">상담 예약 →</a>\n'
    "  </div>\n"
    "</div>\n"
    "</div><!-- /email-wrap -->\n"

    # JavaScript
    "<script>\n"
    f"{kakao_init_js}\n"
    "function nlCopyLink() {\n"
    f"  var url = '{VERCEL_URL}';\n"
    "  if (navigator.clipboard && navigator.clipboard.writeText) {\n"
    "    navigator.clipboard.writeText(url)\n"
    "      .then(function() { nlShowCopy(); })\n"
    "      .catch(function() { nlFallback(url); });\n"
    "  } else { nlFallback(url); }\n"
    "}\n"
    "function nlFallback(url) {\n"
    "  var ta = document.createElement('textarea');\n"
    "  ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';\n"
    "  document.body.appendChild(ta); ta.focus(); ta.select();\n"
    "  try { document.execCommand('copy'); nlShowCopy(); } catch(e) {}\n"
    "  document.body.removeChild(ta);\n"
    "}\n"
    "function nlShowCopy() {\n"
    "  var m = document.getElementById('nl-copy-msg');\n"
    "  m.style.display = 'block';\n"
    "  setTimeout(function() { m.style.display = 'none'; }, 2500);\n"
    "}\n"
    "function nlShareKakao() {\n"
    f"  var shareUrl  = '{VERCEL_URL}';\n"
    f"  var shareText = '[인사 노무 브리핑] {week_label} 노동·HR·정책 핵심 브리핑';\n"
    "\n"
    "  // ① Kakao SDK 정상 초기화 → 카드형 공유\n"
    "  if (typeof Kakao !== 'undefined' && Kakao.isInitialized()) {\n"
    "    try {\n"
    "      Kakao.Share.sendDefault({\n"
    "        objectType: 'feed',\n"
    "        content: {\n"
    f"          title: '[인사 노무 브리핑] {week_label} — 공인노무사JP',\n"
    f"          description: '{week_label} 노동·HR·정책 핵심 브리핑',\n"
    f"          link: {{ mobileWebUrl: '{VERCEL_URL}', webUrl: '{VERCEL_URL}' }},\n"
    "        },\n"
    f"        buttons: [{{ title: '뉴스레터 보기', link: {{ mobileWebUrl: '{VERCEL_URL}', webUrl: '{VERCEL_URL}' }} }}],\n"
    "      });\n"
    "      return;\n"
    "    } catch(e) { console.warn('Kakao.Share 실패:', e); }\n"
    "  }\n"
    "\n"
    "  // ② 모바일 네이티브 공유시트 — KakaoTalk 포함\n"
    "  if (navigator.share) {\n"
    "    navigator.share({ title: '[인사 노무 브리핑]', text: shareText, url: shareUrl })\n"
    "      .catch(function(e) { console.log('share cancelled:', e); });\n"
    "    return;\n"
    "  }\n"
    "\n"
    "  // ③ 최후 fallback: 오픈채팅방 직접 열기\n"
    f"  window.open('{KAKAO_CHAT_URL}', '_blank');\n"
    "}\n"
    "</script>\n"
    "</body>\n"
    "</html>"
)

# ── 파일 저장 (UTF-8, BOM 없음) ──────────────────────
with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(NEWSLETTER_HTML)
print(f"✅ 날짜별 저장: {OUTPUT}")

with open(LATEST, "w", encoding="utf-8") as f:
    f.write(NEWSLETTER_HTML)
print(f"✅ 최신 파일 갱신: {LATEST}")


# ── Maily API 발송 ────────────────────────────────────
def send_via_maily(subject: str, html_content: str) -> None:
    if not MAILY_API_KEY:
        print("⚠ MAILY_API_KEY 없음 — Maily 발송 건너뜀")
        return
    if not MAILY_PROJECT_ID:
        print("⚠ MAILY_PROJECT_ID 없음 — Maily 발송 건너뜀")
        return
    api_url = "https://api.maily.so/api/v1/posts"
    ml_hdrs = {"x-api-key": MAILY_API_KEY, "Content-Type": "application/json"}
    payload = {
        "projectId":   MAILY_PROJECT_ID,
        "subject":     subject,
        "title":       subject,
        "content":     html_content,
        "previewText": f"{week_label} 노동·HR·정책 핵심 이슈 | 공인노무사JP의 뉴스레터",
        "sendAt":      None,
    }
    try:
        resp = requests.post(api_url, headers=ml_hdrs, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            result = resp.json()
            print(f"✅ Maily 발송 성공! post_id={result.get('id', '?')}")
        else:
            print(f"❌ Maily 발송 실패: HTTP {resp.status_code}\n{resp.text[:300]}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Maily API 네트워크 오류: {e}")


send_via_maily(
    subject=f"[인사 노무 브리핑] {week_label} — 노동·HR·정책 핵심 브리핑",
    html_content=NEWSLETTER_HTML,
)


# ── PNG 생성 (Playwright) ────────────────────────────
def generate_png(html_rel_path: str, png_path: str) -> bool:
    """
    로컬 HTTP 서버 → Playwright Chromium으로 full-page PNG 생성.
    CDN 폰트(Pretendard, Playfair Display)까지 정상 렌더링됨.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠ playwright 미설치 — PNG 생성 건너뜀")
        print("  로컬 실행 시: pip install playwright && playwright install chromium")
        return False

    # 빈 포트 자동 탐색
    with socket.socket() as _s:
        _s.bind(("", 0))
        port = _s.getsockname()[1]

    # 로컬 HTTP 서버 (repo 루트 기준 서빙 — CDN 폰트 로드 가능)
    class _SilentHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler_factory = lambda *a, **kw: _SilentHandler(*a, directory=REPO_ROOT, **kw)

    try:
        with socketserver.TCPServer(("127.0.0.1", port), handler_factory) as httpd:
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    page = browser.new_page(viewport={"width": 600, "height": 900})
                    url = f"http://127.0.0.1:{port}/{html_rel_path}"
                    page.goto(url, wait_until="networkidle", timeout=30_000)
                    page.wait_for_timeout(2_000)   # 웹폰트 렌더링 여유
                    page.screenshot(path=png_path, full_page=True)
                    browser.close()
            finally:
                httpd.shutdown()

        print(f"✅ PNG 저장: {png_path}")
        return True

    except Exception as e:
        print(f"⚠ PNG 생성 실패: {e}")
        return False


print("PNG 생성 중...")
ok = generate_png(OUTPUT, PNG_OUTPUT)
if ok:
    shutil.copy2(PNG_OUTPUT, PNG_LATEST)
    print(f"✅ PNG 최신 파일 갱신: {PNG_LATEST}")

# ── 텔레그램용 첫 페이지 프리뷰 PNG 생성 ─────────────
PNG_PREVIEW = f"newsletter/preview_{DATE_STR}.png"

def generate_preview_png(html_rel_path: str, preview_path: str) -> bool:
    """첫 페이지(viewport)만 캡처한 텔레그램 발송용 프리뷰 PNG."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    with socket.socket() as _s:
        _s.bind(("", 0))
        port = _s.getsockname()[1]

    class _SilentHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler_factory = lambda *a, **kw: _SilentHandler(*a, directory=REPO_ROOT, **kw)

    try:
        with socketserver.TCPServer(("127.0.0.1", port), handler_factory) as httpd:
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    # 1200px 높이 = 뉴스레터 첫 화면(헤더+섹션1 일부)
                    page = browser.new_page(viewport={"width": 600, "height": 1200})
                    page.goto(f"http://127.0.0.1:{port}/{html_rel_path}",
                              wait_until="networkidle", timeout=30_000)
                    page.wait_for_timeout(2_000)
                    # full_page=False → viewport 크기만 캡처 (첫 페이지)
                    page.screenshot(path=preview_path, full_page=False)
                    browser.close()
            finally:
                httpd.shutdown()
        print(f"✅ 프리뷰 PNG 저장: {preview_path}")
        return True
    except Exception as e:
        print(f"⚠ 프리뷰 PNG 생성 실패: {e}")
        return False


# ── 텔레그램 발송 ─────────────────────────────────────
def send_telegram_png(png_path: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("⚠ TELEGRAM_BOT_TOKEN 없음 — 텔레그램 발송 건너뜀")
        return
    if not TELEGRAM_CHAT_ID:
        print("⚠ TELEGRAM_CHAT_ID 없음 — 텔레그램 발송 건너뜀")
        return
    if not os.path.exists(png_path):
        print("⚠ PNG 파일 없음 — 텔레그램 발송 건너뜀")
        return

    caption = (
        f"📋 인사 노무 뉴스레터 — {WEEK_LABEL}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"이번 주 인사·노무·정책 핵심 뉴스를 정리했습니다.\n\n"
        f"🔗 전체 보기: {VERCEL_URL}\n"
        f"💬 무료 상담: {KAKAO_CHAT_URL}"
    )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        with open(png_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]},
                files={"photo": f},
                timeout=30,
            )
        if resp.status_code == 200:
            print("✅ 텔레그램 발송 성공!")
        else:
            print(f"❌ 텔레그램 발송 실패: HTTP {resp.status_code}\n{resp.text[:300]}")
    except Exception as e:
        print(f"❌ 텔레그램 API 오류: {e}")


if ok:
    print("텔레그램 프리뷰 PNG 생성 중...")
    preview_ok = generate_preview_png(OUTPUT, PNG_PREVIEW)
    send_telegram_png(PNG_PREVIEW if preview_ok else PNG_OUTPUT)

print(f"🎉 완료! 웹 URL: {VERCEL_URL}")
if ok:
    png_vercel = VERCEL_URL.replace(".html", ".png")
    print(f"🖼  PNG URL: {png_vercel}")
