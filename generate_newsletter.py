"""
JP Labor Letter - 주간 뉴스레터 생성 및 Maily 발송
매주 일요일 UTC 22:00 (= 월요일 KST 07:00) 자동 실행

5섹션 구성:
  1. 이번 주 꼭 읽어야 할 뉴스 Top 3 + JP 인사이트
  2. 5인 미만 사업장 집중 노동법 이슈
  3. 건설/자재 시장 동향 + 노동 이슈 (유진기업 컨텍스트)
  4. JP's Weekly Insight — "이번 주 가장 많이 받은 질문"
  5. 무료 상담 CTA → laborjp.tistory.com

발행: Maily API (https://maily.so)
저장: newsletter/ 폴더 (날짜별 HTML)
"""
import os, re, json, requests, urllib.parse
from datetime import datetime, timezone, timedelta
import anthropic

# ── 환경 변수 ──────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
MAILY_API_KEY       = os.environ.get("MAILY_API_KEY", "")
MAILY_PROJECT_ID    = os.environ.get("MAILY_PROJECT_ID", "")
KAKAO_JS_KEY        = os.environ.get("KAKAO_JS_KEY", "")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── 날짜 설정 ──────────────────────────────────────────
KST         = timezone(timedelta(hours=9))
TODAY       = datetime.now(KST)
DATE_STR    = TODAY.strftime("%Y%m%d")
DATE_LABEL  = TODAY.strftime("%Y. %m. %d.")
WEEKDAY     = ["월","화","수","목","금","토","일"][TODAY.weekday()]
WEEK_NUM    = (TODAY.day - 1) // 7 + 1
WEEK_KO     = ["첫","둘","셋","넷","다섯"][min(WEEK_NUM - 1, 4)]
WEEK_LABEL  = f"{TODAY.year}년 {TODAY.month}월 {WEEK_KO}째주"

os.makedirs("newsletter", exist_ok=True)
OUTPUT = f"newsletter/newsletter_{DATE_STR}.html"
LATEST = "newsletter/latest.html"
VERCEL_URL = f"https://eu-labornews.vercel.app/newsletter/newsletter_{DATE_STR}.html"

print(f"[{DATE_LABEL}] JP Labor Letter 뉴스레터 생성 시작...")

# ── Naver 뉴스 수집 ──────────────────────────────────
KEYWORDS = [
    # 섹션 1: 노동·HR 핵심 이슈
    "노란봉투법","노조법 개정","원청 사용자성",
    "삼성전자 노사","SK 현대차 임금","최저임금",
    "부당해고 노동위원회","임금체불","산업재해 중대재해",
    "고용노동부 정책","노동법 개정안","직장내 괴롭힘",
    # 섹션 2: 5인 미만 사업장
    "5인미만 사업장 노동법","주휴수당 알바",
    "퇴직금 소상공인","근로계약서 작성",
    "직원 해고 절차","가짜 프리랜서 3.3",
    # 섹션 3: 건설/자재 시장
    "건설경기 전망","건자재 시장","시멘트 출하",
    "레미콘 건설업","건설수주 착공","건설업 노무",
    "유진기업 레미콘","골재 건설자재",
]

headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
seven_days_ago = TODAY - timedelta(days=7)
collected, seen = [], set()

for kw in KEYWORDS:
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers, params={"query": kw, "sort": "date", "display": 5}, timeout=10
        )
        for item in resp.json().get("items", []):
            try:
                pub_dt = datetime.strptime(item.get("pubDate",""), "%a, %d %b %Y %H:%M:%S %z").astimezone(KST)
                if pub_dt >= seven_days_ago:
                    title = re.sub(r"<[^>]+>", "", item.get("title",""))
                    key = title[:20]
                    if key not in seen:
                        seen.add(key)
                        collected.append({
                            "title": title,
                            "link": item.get("originallink") or item.get("link",""),
                            "description": re.sub(r"<[^>]+>", "", item.get("description","")),
                            "pubDate": pub_dt.strftime("%Y.%m.%d"),
                            "keyword": kw,
                        })
            except Exception:
                continue
    except Exception as e:
        print(f"키워드 '{kw}' 오류: {e}")

print(f"7일 이내 뉴스 {len(collected)}건 수집")
news_pool = collected[:30]

news_text = "\n\n".join([
    f"[{i+1}] {n['title']}\n날짜:{n['pubDate']} | 링크:{n['link']}\n키워드:{n['keyword']}\n요약:{n['description']}"
    for i, n in enumerate(news_pool)
]) if news_pool else "수집된 뉴스 없음"

# ── Claude API 뉴스레터 콘텐츠 생성 ──────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROMPT = f"""당신은 공인노무사 JP입니다. 오늘은 {DATE_LABEL} {WEEKDAY}요일, {WEEK_LABEL}입니다.
아래 수집된 뉴스를 바탕으로 주간 뉴스레터 콘텐츠를 JSON으로 생성하세요.

수집된 뉴스:
{news_text}

【생성 규칙】
1. 반드시 수집된 뉴스 목록에서만 선별할 것 (임의 생성 금지)
2. 없는 섹션은 공인노무사 JP 실무 인사이트로 대체 (url → https://laborjp.tistory.com)
3. 건설 섹션이 없으면 건설업 노무·임금 실무 이슈로 대체
4. JP's Weekly Insight Q&A는 수집 뉴스 기반으로 실제 받을 법한 질문 1개 작성
5. 모든 제목은 질문형 또는 실용적 표현 권장

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
  "section2_five_fewer": {{
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
  }},
  "section3_construction": {{
    "title": "건설·자재 시장 동향",
    "sub_title": "유진기업·건설업 실무 포인트",
    "source": "언론사명 또는 공인노무사 JP",
    "date": "2026.05.12",
    "url": "https://실제URL 또는 https://laborjp.tistory.com",
    "market_bullets": [
      "시장 동향 1",
      "시장 동향 2",
      "시장 동향 3"
    ],
    "labor_insight": "건설업 노무·인사 실무 시사점 2~3문장"
  }},
  "section4_weekly_insight": {{
    "question": "이번 주 가장 많이 받은 질문을 한 문장으로",
    "answer_paragraphs": [
      "답변 단락 1 — 법적 근거 포함",
      "답변 단락 2 — 실무 적용 방법",
      "답변 단락 3 — 주의사항 또는 예외"
    ],
    "cta_line": "더 궁금한 점은 무료 상담으로 확인하세요."
  }}
}}"""

print("Claude API 호출 중...")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=6000,
    system="You are a Korean labor law expert (공인노무사 JP). Always respond with valid JSON only. No text outside JSON. Escape all special characters properly.",
    messages=[{"role": "user", "content": PROMPT}]
)
raw = response.content[0].text.strip()

def safe_parse(text):
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s, e = text.find('{'), text.rfind('}')
    if s != -1 and e != -1:
        try:
            return json.loads(text[s:e+1])
        except Exception:
            pass
    print("⚠ JSON 파싱 실패 — 기본 템플릿 사용")
    return {
        "week_label": WEEK_LABEL,
        "section1_top3": [{"rank":i+1,"source":"공인노무사 JP","date":TODAY.strftime("%Y.%m.%d"),"url":"https://laborjp.tistory.com","category":"노동법 실무","title":f"이번 주 노동·HR 이슈 {i+1}","summary":"뉴스 수집 중 오류. 다음 주 브리핑을 확인해 주세요.","insight":"구체적 사안은 공인노무사 JP에게 문의하세요."} for i in range(3)],
        "section2_five_fewer":{"title":"5인 미만 사업장 핵심 이슈","sub_title":"이번 주 점검 포인트","source":"공인노무사 JP","date":TODAY.strftime("%Y.%m.%d"),"url":"https://laborjp.tistory.com","key_points":["근로계약서 필수 작성","주휴수당 지급 의무 확인","퇴직금 산정 기준 체크","임금체불 예방 조치"],"action_tip":"궁금한 사항은 laborjp.tistory.com에서 무료 상담을 신청하세요."},
        "section3_construction":{"title":"건설·자재 시장 동향","sub_title":"이번 주 핵심 포인트","source":"공인노무사 JP","date":TODAY.strftime("%Y.%m.%d"),"url":"https://laborjp.tistory.com","market_bullets":["건설업 고용 동향 모니터링 중","자재가격 변동 확인 필요","건설업 노무비 관리 점검"],"labor_insight":"건설업 관련 노무 이슈는 laborjp.tistory.com에서 확인하세요."},
        "section4_weekly_insight":{"question":"퇴직금을 분할해서 매월 지급해도 되나요?","answer_paragraphs":["근로기준법상 퇴직금은 퇴직 시 일시에 지급이 원칙입니다.","다만 근로자 동의 시 분할 지급 약정이 가능하며, 서면 동의가 필요합니다.","분할 지급 약정 없이 월급에 포함해 지급하면 퇴직금 선급이 무효화될 수 있습니다."],"cta_line":"더 궁금한 점은 무료 상담으로 확인하세요."}
    }

data = safe_parse(raw)
week_label = data.get("week_label", WEEK_LABEL)
top3 = data.get("section1_top3", [])
five_fewer = data.get("section2_five_fewer", {})
construction = data.get("section3_construction", {})
weekly_qa = data.get("section4_weekly_insight", {})
print("뉴스레터 콘텐츠 생성 완료")

# ── HTML 생성 ─────────────────────────────────────────
# 이메일 + 웹 브라우저 모두 대응하는 반응형 HTML
CSS_NL = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #f4f4f6;
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
    font-size: 16px; line-height: 1.75; color: #1a1a2e;
  }
  .email-wrap { max-width: 640px; margin: 0 auto; background: #ffffff; }

  /* 헤더 */
  .nl-header {
    background: #0a0f1e; padding: 24px 32px;
    border-bottom: 3px solid #c9a84c;
  }
  .nl-logo { font-size: 20px; font-weight: 900; color: #c9a84c; }
  .nl-tagline { font-size: 12px; color: #7a8299; margin-top: 3px; }
  .nl-date { font-size: 13px; color: #c8ccd8; margin-top: 6px; }

  /* 히어로 */
  .nl-hero {
    background: linear-gradient(135deg, #111827 0%, #0d1628 100%);
    padding: 36px 32px; text-align: center; border-bottom: 1px solid #1f3260;
  }
  .nl-hero-eyebrow {
    font-size: 12px; letter-spacing: .18em; color: #c9a84c;
    text-transform: uppercase; margin-bottom: 14px; font-weight: 700;
  }
  .nl-hero-title {
    font-size: 28px; font-weight: 900; color: #f5f0e8;
    line-height: 1.2; margin-bottom: 12px; word-break: keep-all;
  }
  .nl-hero-title em { color: #c9a84c; font-style: normal; }
  .nl-hero-sub { font-size: 14px; color: #7a8299; line-height: 1.8; }

  /* 섹션 공통 */
  .nl-section { padding: 32px 32px 8px; border-bottom: 1px solid #e8e8f0; }
  .nl-section:last-of-type { border-bottom: none; }
  .sec-label {
    display: inline-flex; align-items: center; gap: 8px;
    font-size: 11px; font-weight: 700; letter-spacing: .14em;
    color: #c9a84c; text-transform: uppercase; margin-bottom: 20px;
    padding-bottom: 10px; border-bottom: 1px solid #e8e8f0; width: 100%;
  }
  .sec-label::before { content: ''; width: 18px; height: 2px; background: #c9a84c; }

  /* 섹션 1: Top 3 뉴스 카드 */
  .news-card-nl {
    border: 1px solid #e0e0ea; border-radius: 6px;
    margin-bottom: 20px; overflow: hidden;
  }
  .news-card-nl:last-child { margin-bottom: 8px; }
  .nc-header {
    display: flex; align-items: center; justify-content: space-between;
    background: #f8f8fc; padding: 10px 16px;
    border-bottom: 1px solid #e0e0ea;
  }
  .nc-rank {
    font-size: 12px; font-weight: 700; color: #c9a84c;
    background: rgba(201,168,76,.1); border: 1px solid rgba(201,168,76,.3);
    width: 24px; height: 24px; border-radius: 3px;
    display: flex; align-items: center; justify-content: center;
  }
  .nc-source { font-size: 12px; color: #888; }
  .nc-date { font-size: 12px; color: #aaa; }
  .nc-body { padding: 16px; }
  .nc-category {
    font-size: 11px; font-weight: 700; color: #c9a84c;
    letter-spacing: .08em; margin-bottom: 6px;
  }
  .nc-title {
    font-size: 17px; font-weight: 800; color: #1a1a2e;
    line-height: 1.4; margin-bottom: 10px; word-break: keep-all;
  }
  .nc-summary { font-size: 14px; color: #4a4a6a; line-height: 1.8; margin-bottom: 12px; }
  .nc-insight {
    background: rgba(201,168,76,.06); border-left: 3px solid #c9a84c;
    padding: 12px 14px; border-radius: 0 4px 4px 0;
  }
  .nc-insight-label {
    font-size: 10px; font-weight: 700; color: #c9a84c;
    letter-spacing: .15em; text-transform: uppercase; margin-bottom: 5px;
  }
  .nc-insight-text { font-size: 13px; color: #333355; line-height: 1.8; }
  .nc-footer {
    padding: 10px 16px; background: #f8f8fc;
    border-top: 1px solid #e0e0ea; text-align: right;
  }
  .nc-link {
    font-size: 13px; font-weight: 700; color: #c9a84c;
    text-decoration: none;
  }
  .nc-link::after { content: ' →'; }

  /* 섹션 2: 5인 미만 */
  .five-card {
    background: linear-gradient(135deg, #fff8e1, #fffde7);
    border: 1px solid #f0c040; border-radius: 6px;
    padding: 24px; margin-bottom: 12px;
  }
  .five-badge {
    display: inline-block; background: #e65100; color: #fff;
    font-size: 11px; font-weight: 700; padding: 3px 10px;
    border-radius: 3px; margin-bottom: 12px; letter-spacing: .05em;
  }
  .five-title { font-size: 18px; font-weight: 900; color: #1a1a2e; margin-bottom: 4px; }
  .five-sub { font-size: 13px; color: #666; margin-bottom: 16px; }
  .five-points { list-style: none; margin-bottom: 16px; }
  .five-points li {
    font-size: 14px; color: #2a2a4a; padding: 8px 0 8px 20px;
    border-bottom: 1px solid rgba(240,192,64,.3); position: relative;
    line-height: 1.7;
  }
  .five-points li:last-child { border-bottom: none; }
  .five-points li::before {
    content: '✓'; position: absolute; left: 0;
    color: #e65100; font-weight: 900; font-size: 13px;
  }
  .five-tip {
    background: rgba(230,81,0,.06); border: 1px solid rgba(230,81,0,.2);
    border-left: 3px solid #e65100; padding: 12px 14px; border-radius: 0 4px 4px 0;
    font-size: 13px; color: #3a1a00; line-height: 1.8;
  }
  .five-tip-label {
    font-size: 10px; font-weight: 700; color: #e65100;
    letter-spacing: .14em; text-transform: uppercase; margin-bottom: 5px;
  }

  /* 섹션 3: 건설·자재 */
  .const-card {
    background: linear-gradient(135deg, #e8f5e9, #f1f8e9);
    border: 1px solid #81c784; border-radius: 6px;
    padding: 24px; margin-bottom: 12px;
  }
  .const-badge {
    display: inline-block; background: #2e7d32; color: #fff;
    font-size: 11px; font-weight: 700; padding: 3px 10px;
    border-radius: 3px; margin-bottom: 12px;
  }
  .const-title { font-size: 18px; font-weight: 900; color: #1a1a2e; margin-bottom: 4px; }
  .const-sub { font-size: 13px; color: #666; margin-bottom: 16px; }
  .const-bullets { list-style: none; margin-bottom: 16px; }
  .const-bullets li {
    font-size: 14px; color: #1a3a1a; padding: 7px 0 7px 20px;
    border-bottom: 1px solid rgba(129,199,132,.3); position: relative;
    line-height: 1.7;
  }
  .const-bullets li:last-child { border-bottom: none; }
  .const-bullets li::before {
    content: '▸'; position: absolute; left: 0;
    color: #2e7d32; font-size: 13px;
  }
  .const-insight {
    background: rgba(46,125,50,.06); border: 1px solid rgba(46,125,50,.2);
    border-left: 3px solid #2e7d32; padding: 12px 14px; border-radius: 0 4px 4px 0;
    font-size: 13px; color: #1a3a1a; line-height: 1.8;
  }
  .const-insight-label {
    font-size: 10px; font-weight: 700; color: #2e7d32;
    letter-spacing: .14em; text-transform: uppercase; margin-bottom: 5px;
  }

  /* 섹션 4: JP's Weekly Insight */
  .qa-wrap {
    background: #0a0f1e; border-radius: 6px;
    padding: 24px; margin-bottom: 12px;
  }
  .qa-label {
    font-size: 11px; font-weight: 700; color: #c9a84c;
    letter-spacing: .18em; text-transform: uppercase; margin-bottom: 14px;
  }
  .qa-q {
    font-size: 17px; font-weight: 800; color: #f5f0e8;
    line-height: 1.45; margin-bottom: 18px; word-break: keep-all;
  }
  .qa-q::before { content: '"'; color: #c9a84c; font-size: 22px; margin-right: 4px; }
  .qa-q::after  { content: '"'; color: #c9a84c; font-size: 22px; margin-left: 4px; }
  .qa-a-label { font-size: 11px; font-weight: 700; color: #c9a84c; margin-bottom: 10px; letter-spacing: .1em; }
  .qa-paragraph { font-size: 14px; color: #c8ccd8; line-height: 1.9; margin-bottom: 10px; }
  .qa-paragraph:last-of-type { margin-bottom: 0; }
  .qa-cta {
    margin-top: 16px; padding-top: 16px;
    border-top: 1px solid #1f3260;
    font-size: 13px; color: #c9a84c; font-weight: 700;
  }

  /* 섹션 5: CTA */
  .cta-section {
    background: linear-gradient(135deg, #0a0f1e, #111827);
    padding: 36px 32px; text-align: center;
  }
  .cta-logo { font-size: 16px; font-weight: 700; color: #c9a84c; margin-bottom: 8px; }
  .cta-headline { font-size: 22px; font-weight: 900; color: #f5f0e8; margin-bottom: 8px; line-height: 1.3; }
  .cta-sub { font-size: 13px; color: #7a8299; margin-bottom: 24px; line-height: 1.8; }
  .cta-btn {
    display: inline-block; background: #c9a84c; color: #0a0f1e;
    font-size: 15px; font-weight: 900; padding: 16px 36px;
    border-radius: 4px; text-decoration: none; letter-spacing: .03em;
  }
  .cta-btn:hover { background: #e2c278; }
  .cta-note { font-size: 11px; color: #4a5569; margin-top: 14px; }

  /* 공유 바 */
  .share-bar {
    background: #111827; border-top: 1px solid #1f3260;
    padding: 14px 32px; display: flex; align-items: center;
    gap: 10px; flex-wrap: wrap;
    position: sticky; bottom: 0; z-index: 90;
  }
  .share-label { font-size: 12px; color: #7a8299; }
  .share-btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 9px 16px; font-size: 13px; font-weight: 700;
    border: none; border-radius: 4px; cursor: pointer;
    text-decoration: none; transition: opacity .2s;
  }
  .share-btn:hover { opacity: .82; }
  .share-copy     { background: #1f3260; color: #f5f0e8; }
  .share-kakao    { background: #FEE500; color: #3A1D1D; }
  .share-telegram { background: #0088cc; color: #fff; }
  #nl-copy-msg { font-size: 12px; color: #c9a84c; display: none; white-space: nowrap; }

  /* 푸터 */
  .nl-footer {
    background: #111827; padding: 24px 32px;
    border-top: 1px solid #1f3260; text-align: center;
  }
  .nf-logo { font-size: 14px; font-weight: 700; color: #c9a84c; margin-bottom: 4px; }
  .nf-url { font-size: 11px; color: rgba(201,168,76,.4); margin-bottom: 10px; }
  .nf-disc { font-size: 11px; color: #4a5569; line-height: 1.8; }

  /* 반응형 */
  @media (max-width: 600px) {
    .nl-section, .nl-hero, .nl-header, .cta-section, .nl-footer { padding-left: 18px; padding-right: 18px; }
    .nl-hero-title { font-size: 22px; }
    .cta-headline { font-size: 18px; }
  }
"""

def render_top3(items):
    html = ""
    for n in items:
        html += f"""<div class="news-card-nl">
  <div class="nc-header">
    <div class="nc-rank">{n['rank']}</div>
    <span class="nc-source">📰 {n['source']}</span>
    <span class="nc-date">{n['date']}</span>
  </div>
  <div class="nc-body">
    <div class="nc-category">{n['category']}</div>
    <h3 class="nc-title">{n['title']}</h3>
    <p class="nc-summary">{n['summary']}</p>
    <div class="nc-insight">
      <div class="nc-insight-label">JP 인사이트</div>
      <div class="nc-insight-text">{n['insight']}</div>
    </div>
  </div>
  <div class="nc-footer">
    <a class="nc-link" href="{n['url']}" target="_blank">원문 보기</a>
  </div>
</div>"""
    return html


def render_five_fewer(s):
    pts = "".join(f"<li>{p}</li>" for p in s.get("key_points", []))
    return f"""<div class="five-card">
  <div class="five-badge">⭐ 5인 미만 사업장 필독</div>
  <div class="five-title">{s.get('title','5인 미만 핵심 이슈')}</div>
  <div class="five-sub">{s.get('sub_title','')} · {s.get('source','')} · {s.get('date','')}</div>
  <ul class="five-points">{pts}</ul>
  <div class="five-tip">
    <div class="five-tip-label">즉시 실행 팁</div>
    {s.get('action_tip','')}
  </div>
</div>"""


def render_construction(s):
    buls = "".join(f"<li>{b}</li>" for b in s.get("market_bullets", []))
    return f"""<div class="const-card">
  <div class="const-badge">🏗 건설·자재 시장</div>
  <div class="const-title">{s.get('title','건설·자재 동향')}</div>
  <div class="const-sub">{s.get('sub_title','')} · {s.get('source','')} · {s.get('date','')}</div>
  <ul class="const-bullets">{buls}</ul>
  <div class="const-insight">
    <div class="const-insight-label">노무 실무 포인트</div>
    {s.get('labor_insight','')}
  </div>
</div>"""


def render_qa(qa):
    paras = "".join(f'<p class="qa-paragraph">{p}</p>' for p in qa.get("answer_paragraphs", []))
    return f"""<div class="qa-wrap">
  <div class="qa-label">JP's Weekly Insight · 이번 주 가장 많이 받은 질문</div>
  <div class="qa-q">{qa.get('question','')}</div>
  <div class="qa-a-label">공인노무사 JP의 답변</div>
  {paras}
  <div class="qa-cta">💬 {qa.get('cta_line','더 궁금한 점은 무료 상담으로 확인하세요.')}</div>
</div>"""


NEWSLETTER_HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JP Labor Letter {week_label} | 공인노무사 JP</title>
<meta name="description" content="{week_label} 노동·HR·건설 핵심 이슈. 공인노무사 JP 주간 뉴스레터.">
<meta property="og:title" content="JP Labor Letter {week_label} | 공인노무사 JP">
<meta property="og:type" content="article">
<meta property="og:url" content="{VERCEL_URL}">
<style>{CSS_NL}</style>
</head>
<body>
<div class="email-wrap">

<!-- 헤더 -->
<div class="nl-header">
  <div class="nl-logo">JP Labor Letter</div>
  <div class="nl-tagline">공인노무사 JP | 주간 노동·HR·건설 브리핑</div>
  <div class="nl-date">{DATE_LABEL} {WEEKDAY}요일 · {week_label}</div>
</div>

<!-- 히어로 -->
<div class="nl-hero">
  <div class="nl-hero-eyebrow">{week_label} · 주간 뉴스레터</div>
  <h1 class="nl-hero-title">이번 주 꼭 알아야 할<br><em>Labor &amp; HR</em> 이슈</h1>
  <p class="nl-hero-sub">공인노무사 JP가 선별한 핵심 뉴스 · 5인 미만 이슈 · 건설 동향 · JP 인사이트</p>
</div>

<!-- 섹션 1: Top 3 뉴스 -->
<div class="nl-section">
  <div class="sec-label">Section 1 · 이번 주 꼭 읽어야 할 뉴스 Top 3</div>
  {render_top3(top3)}
</div>

<!-- 섹션 2: 5인 미만 사업장 -->
<div class="nl-section">
  <div class="sec-label">Section 2 · 5인 미만 사업장 집중 노동법 이슈</div>
  {render_five_fewer(five_fewer)}
</div>

<!-- 섹션 3: 건설·자재 시장 -->
<div class="nl-section">
  <div class="sec-label">Section 3 · 건설/자재 시장 동향 + 노동 이슈</div>
  {render_construction(construction)}
</div>

<!-- 섹션 4: JP's Weekly Insight -->
<div class="nl-section">
  <div class="sec-label">Section 4 · JP's Weekly Insight</div>
  {render_qa(weekly_qa)}
</div>

<!-- 섹션 5: CTA -->
<div class="cta-section">
  <div class="cta-logo">공인노무사 JP</div>
  <h2 class="cta-headline">노동법 궁금증,<br>무료로 해결하세요</h2>
  <p class="cta-sub">근로계약서 · 임금체불 · 해고 · 퇴직금 · 5인 미만 이슈<br>공인노무사 JP가 직접 답변합니다</p>
  <a class="cta-btn" href="https://laborjp.tistory.com" target="_blank">무료 상담 신청하기</a>
  <p class="cta-note">laborjp.tistory.com</p>
</div>

<!-- 공유 바: CTA 아래, 푸터 위 / 모바일 하단 sticky -->
{'<script src="https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js" integrity="sha384-TiCUE00h649CAMonG018J2ujOgDKW/kVWlChEuu4jK2vxfAAD0eZxzCKakxg55G4" crossorigin="anonymous"></script>' if KAKAO_JS_KEY else ''}
<div class="share-bar">
  <span class="share-label">공유하기</span>
  <button class="share-btn share-copy" onclick="nlCopyLink()">🔗 링크 복사</button>
  <span id="nl-copy-msg">✅ 링크 복사됨!</span>
  {'<button class="share-btn share-kakao" onclick="nlShareKakao()">💬 카카오톡</button>' if KAKAO_JS_KEY else ''}
  <a class="share-btn share-telegram" href="https://t.me/share/url?url={urllib.parse.quote(VERCEL_URL)}&text={urllib.parse.quote(f'[JP Labor Letter] {week_label} 노동·HR 핵심 브리핑 — 공인노무사 JP')}" target="_blank" rel="noopener">✈️ 텔레그램</a>
</div>
<script>
{'if (typeof Kakao !== "undefined" && !Kakao.isInitialized()) { Kakao.init("' + KAKAO_JS_KEY + '"); }' if KAKAO_JS_KEY else ''}
function nlCopyLink() {{
  var url = '{VERCEL_URL}';
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(url).then(function() {{ nlShowCopy(); }}).catch(function() {{ nlFallback(url); }});
  }} else {{ nlFallback(url); }}
}}
function nlFallback(url) {{
  var ta = document.createElement('textarea');
  ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.focus(); ta.select();
  try {{ document.execCommand('copy'); nlShowCopy(); }} catch(e) {{}}
  document.body.removeChild(ta);
}}
function nlShowCopy() {{
  var m = document.getElementById('nl-copy-msg');
  m.style.display = 'inline';
  setTimeout(function() {{ m.style.display = 'none'; }}, 2500);
}}
function nlShareKakao() {{
  if (typeof Kakao === 'undefined' || !Kakao.isInitialized()) {{ return; }}
  Kakao.Share.sendDefault({{
    objectType: 'feed',
    content: {{
      title: '[JP Labor Letter] — 공인노무사 JP',
      description: '{week_label} 노동·HR·건설 핵심 브리핑',
      link: {{ mobileWebUrl: '{VERCEL_URL}', webUrl: '{VERCEL_URL}' }},
    }},
    buttons: [{{ title: '뉴스레터 보기', link: {{ mobileWebUrl: '{VERCEL_URL}', webUrl: '{VERCEL_URL}' }} }}],
  }});
}}
</script>

<!-- 푸터 -->
<div class="nl-footer">
  <div class="nf-logo">JP Labor Letter</div>
  <div class="nf-url">laborjp.tistory.com</div>
  <div class="nf-disc">
    본 뉴스레터는 정보 제공 목적으로 작성된 자료입니다.<br>
    구체적인 사안은 전문가 상담을 권장합니다.<br>
    Powered by Claude AI · © 2026 공인노무사 JP. 무단 복제·배포 금지.
  </div>
</div>

</div><!-- /email-wrap -->
</body>
</html>"""

# ── 파일 저장 ─────────────────────────────────────────
with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(NEWSLETTER_HTML)
print(f"✅ 날짜별 저장: {OUTPUT}")

with open(LATEST, "w", encoding="utf-8") as f:
    f.write(NEWSLETTER_HTML)
print(f"✅ 최신 파일 갱신: {LATEST}")

# ── Maily API 발송 ─────────────────────────────────────
# Maily (maily.so) REST API를 통해 뉴스레터 발송
# 환경변수 MAILY_API_KEY, MAILY_PROJECT_ID 설정 필요
def send_via_maily(subject: str, html_content: str) -> None:
    if not MAILY_API_KEY:
        print("⚠ MAILY_API_KEY 없음 — Maily 발송 건너뜀 (로컬 저장만 완료)")
        return
    if not MAILY_PROJECT_ID:
        print("⚠ MAILY_PROJECT_ID 없음 — Maily 발송 건너뜀")
        return

    # Maily API 엔드포인트: https://maily.so/api 참고
    api_url = "https://api.maily.so/api/v1/posts"
    headers = {
        "x-api-key": MAILY_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "projectId": MAILY_PROJECT_ID,
        "subject": subject,
        "title": subject,
        "content": html_content,     # HTML 본문
        "previewText": f"{week_label} 노동·HR·건설 핵심 이슈 | 공인노무사 JP",
        "sendAt": None,              # None → 즉시 발송. ISO 8601 문자열로 예약 발송 가능
    }
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            result = resp.json()
            print(f"✅ Maily 뉴스레터 발송 성공! post_id={result.get('id','?')}")
        else:
            print(f"❌ Maily 발송 실패: HTTP {resp.status_code}\n{resp.text[:300]}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Maily API 네트워크 오류: {e}")

send_via_maily(
    subject=f"[JP Labor Letter] {week_label} — 노동·HR·건설 핵심 브리핑",
    html_content=NEWSLETTER_HTML,
)

# ── 텔레그램 채널 발송 ─────────────────────────────────
if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    tg_caption = "\n".join([
        f"📰 *JP Labor Letter* — {week_label}",
        "",
        "이번 주 Top 3:",
    ] + [
        f"{['1️⃣','2️⃣','3️⃣'][n['rank']-1]} {n['title']}"
        for n in top3
    ] + [
        "",
        f"🔗 전체 뉴스레터 보기\n{VERCEL_URL}",
        "",
        "📌 *JP Labor News* 채널 구독 → @jplabornews",
    ])[:1024]

    tg_resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": tg_caption, "parse_mode": "Markdown"},
        timeout=10
    )
    if tg_resp.json().get("ok"):
        print("✅ 텔레그램 뉴스레터 발송 성공!")
    else:
        print(f"❌ 텔레그램 발송 실패: {tg_resp.text}")
else:
    print("⚠ TELEGRAM 환경변수 없음 — 텔레그램 발송 건너뜀")

print(f"🎉 완료! 웹 URL: {VERCEL_URL}")
