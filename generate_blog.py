"""
JP Labor & HR Blog - 주간 블로그 카드뉴스 생성
매주 월요일 오전 7시 자동 실행
- Naver API 7일 이내 뉴스 수집
- Claude API 깊이있는 카드뉴스 생성
- 5인 미만 사업장 섹션 필수 포함
- labor_hr_briefing_v2 형식 HTML 생성
"""
import os, re, json, requests
from datetime import datetime, timezone, timedelta
import anthropic

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]

KST      = timezone(timedelta(hours=9))
TODAY    = datetime.now(KST)
DATE_STR    = TODAY.strftime("%Y%m%d")
DATE_LABEL  = TODAY.strftime("%Y. %m. %d.")
WEEKDAY     = ["월","화","수","목","금","토","일"][TODAY.weekday()]
WEEK_NUM    = (TODAY.day - 1) // 7 + 1
WEEK_KO     = ["첫","둘","셋","넷","다섯"][WEEK_NUM - 1]
WEEK_LABEL  = f"{TODAY.year}년 {TODAY.month}월 {WEEK_KO}째주"

os.makedirs("blog", exist_ok=True)
OUTPUT = f"blog/blog_{DATE_STR}.html"
print(f"[{DATE_LABEL}] 블로그 카드뉴스 생성 시작...")

# ── Naver 뉴스 수집 ──────────────────────────────────
KEYWORDS = [
    "5인미만 사업장 노동법","주휴수당 알바","퇴직금 소상공인",
    "가짜 프리랜서 3.3 단속","고용지원금 중소기업","근로계약서 작성",
    "직원 해고 절차","손해배상 직원 퇴사",
    "임금체불 단속","부당해고 판결","중대재해 처벌",
    "고용노동부 정책","최저임금","직장내괴롭힘",
    "AI 일자리 대체","인공지능 채용 HR","챗GPT 노동시장",
    "플랫폼 노동자","디지털 전환 고용",
    "산업재해","육아휴직 중소기업","외국인 근로자",
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
news_pool = collected[:25]

# ── Claude API 카드뉴스 생성 ─────────────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

news_text = "\n\n".join([
    f"[{i+1}] {n['title']}\n날짜:{n['pubDate']} | 링크:{n['link']}\n요약:{n['description']}"
    for i, n in enumerate(news_pool)
]) if news_pool else "수집된 뉴스 없음"

PROMPT = f"""당신은 공인노무사이자 HR 전문가입니다. 오늘은 {DATE_LABEL} {WEEKDAY}요일입니다.
아래 수집된 뉴스에서 중소·영세 사업장 사장님과 자영업자에게 실질적으로 도움이 되는 뉴스를 선별하여 블로그용 카드뉴스 8건을 작성하세요.

⚠ 핵심 원칙 (반드시 준수):
- 반드시 위 수집된 뉴스 목록에서만 선별할 것
- 수집된 뉴스 외 임의로 뉴스를 생성하는 것 절대 금지
- 부족한 섹션은 공인노무사 JP의 실무 인사이트로 대체 (is_insight_card: true)
- 인사이트 카드에는 뉴스 URL 대신 반드시 https://laborjp.tistory.com 사용
- 제목은 반드시 질문형 또는 사장님 관점의 실용적 표현으로 작성

수집된 뉴스:
{news_text}

【고정 섹션 4개 - 반드시 포함】
섹션1 "노사 핫이슈": 2건 (사장님에게 직접 영향 주는 정책·단속·판례)
섹션2 "판례·단속": 1건 (소상공인·자영업자 노동법 핵심 이슈)
섹션3 "사장님 체크포인트": 1건 (사장님이 받을 수 있는 지원금·보조금·정책)
섹션4 "5인 미만 사업장 필독 ⭐": 1건 (5인 미만 사업장 필수 노동법)

【유동 섹션 - Claude 자유 선정】
섹션5 "HR 동향": 나머지 3건 (AI·디지털·사회이슈·기타 유용 주제)

【작성 기준】
- 블로그용이므로 불릿 포인트 5개 이상 상세하게
- 실무 시사점은 구체적이고 즉시 실행 가능한 내용으로
- 전문 용어보다 사장님이 이해하기 쉬운 언어 사용

JSON만 응답. 다른 텍스트 절대 금지:
{{
  "week_label": "{WEEK_LABEL}",
  "news": [
    {{
      "rank": 1,
      "section_num": 1,
      "section": "노사 핫이슈",
      "source": "언론사명",
      "date": "2026.05.11",
      "url": "https://실제기사URL",
      "risk_level": "high",
      "risk_label": "🔴 긴급",
      "category": "카테고리명",
      "title": "카드 제목",
      "keyword": "강조할핵심키워드",
      "bullets": [
        "상세 내용 1 — 구체적 수치나 법조항 포함",
        "상세 내용 2",
        "상세 내용 3",
        "상세 내용 4",
        "상세 내용 5"
      ],
      "insight": "HR 실무자를 위한 구체적이고 실행 가능한 시사점. 2~3문장 이상.",
      "is_insight_card": false
    }}
  ]
}}
risk_level: high(🔴), med(⚠), info(ℹ) 중 선택
총 8건, section_num 1~5 분배 필수"""

print("Claude API 호출 중...")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=8000,
    system="You are a Korean labor law expert. Always respond with valid JSON only. Never include any text outside the JSON object. Never use single quotes inside JSON strings. Escape all special characters properly.",
    messages=[{"role": "user", "content": PROMPT}]
)
raw = response.content[0].text.strip()

# ── JSON 안전 파싱 ────────────────────────────────────
def safe_parse_json(text):
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find('{')
    end   = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    cleaned = re.sub(r'[\x00-\x1f\x7f]', ' ', text[start:end+1]) if start != -1 else text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    print("⚠ JSON 파싱 실패 — 기본 템플릿 사용")
    return {
        "week_label": WEEK_LABEL,
        "news": [{
            "rank": i+1,
            "section_num": [1,1,2,3,4,5,5,5][i],
            "section": ["노사 핫이슈","노사 핫이슈","판례·단속","사장님 체크포인트","5인 미만 사업장 필독 ⭐","HR 동향","HR 동향","HR 동향"][i],
            "source": "공인노무사 JP",
            "date": TODAY.strftime("%Y.%m.%d"),
            "url": "https://laborjp.tistory.com",
            "risk_level": "info",
            "risk_label": "ℹ 참고",
            "category": "노동법 실무",
            "title": f"이번 주 노동·HR 이슈 {i+1}",
            "keyword": "노동법",
            "bullets": ["뉴스 수집 중 오류가 발생했습니다.", "다음 주 브리핑을 확인해 주세요.", "문의: laborjp.tistory.com"],
            "insight": "구체적인 사안은 공인노무사 JP에게 문의하세요.",
            "is_insight_card": True
        } for i in range(8)]
    }

data       = safe_parse_json(raw)
news_list  = data["news"]
week_label = data.get("week_label", WEEK_LABEL)
print(f"카드뉴스 {len(news_list)}건 생성 완료")

# ── HTML 생성 (labor_hr_briefing_v2 형식) ────────────
RISK_CLS = {"high":"r-h","med":"r-m","info":"r-i"}
TAG_CLS  = {"high":"tag-h","med":"tag-m","info":"tag-i"}

# 섹션번호 → 주제 번호 표시 문자열
SEC_TOPIC = {
    1: ("①", "노사 핫이슈"),
    2: ("②", "판례·단속"),
    3: ("③", "사장님 체크포인트"),
    4: ("④", "5인 미만 사업장 필독 ⭐"),
    5: ("⑤", "HR 동향"),
}

CSS = """:root{
  --navy:#0a0f1e;--navy-mid:#111827;--navy-card:#141d2e;
  --navy-border:#1f3260;--gold:#c9a84c;--gold-dim:#9b7d36;
  --gold-light:#e2c278;--cream:#f5f0e8;--cream-dim:#ccc4b0;
  --text-body:#c8ccd8;--text-muted:#7a8299
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--navy);color:var(--text-body);font-family:'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;font-size:16px;line-height:1.75}

/* ── 헤더 ── */
.blog-header{background:var(--navy-mid);border-bottom:2px solid var(--gold);padding:16px 40px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.blog-logo{font-size:20px;font-weight:700;color:var(--gold)}
.blog-author{font-size:13px;color:var(--text-muted);margin-top:3px}
.wm-badge{display:inline-flex;align-items:center;gap:5px;background:rgba(201,168,76,.12);border:1px solid rgba(201,168,76,.35);border-radius:3px;padding:4px 10px;font-size:11px;font-weight:700;color:var(--gold)}
.blog-date{font-size:15px;font-weight:700;color:#fff;text-align:right}
.blog-period{font-size:12px;color:var(--text-muted);text-align:right;margin-top:3px}

/* ── 히어로 ── */
.hero{background:linear-gradient(160deg,#111827 0%,#0d1628 50%,var(--navy) 100%);padding:52px 40px 44px;border-bottom:1px solid var(--navy-border);text-align:center}
.hero-eyebrow{font-size:22px;letter-spacing:.15em;color:var(--gold);margin-bottom:14px;display:flex;align-items:center;justify-content:center;gap:12px;font-weight:700}
.hero-eyebrow::before,.hero-eyebrow::after{content:'';width:32px;height:1px;background:var(--gold)}
.hero-title{font-size:clamp(32px,5vw,54px);font-weight:900;color:var(--cream);line-height:1.15;margin-bottom:12px}
.hero-title em{color:var(--gold);font-style:italic}
.hero-desc{font-size:16px;color:var(--cream-dim);max-width:560px;margin:0 auto 28px;line-height:1.8}

/* ── 1페이지 헤드라인 그리드 ── */
.headline-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:2px;max-width:960px;margin:0 auto;background:var(--navy-border);border:1px solid var(--navy-border)}
.headline-item{background:rgba(31,50,96,.35);padding:20px 22px;text-decoration:none;display:block;transition:background .2s}
.headline-item:hover{background:rgba(31,50,96,.65)}
.hl-inner{display:flex;align-items:center;gap:13px;width:100%}
.hl-num{font-size:15px;font-weight:700;color:var(--gold);background:rgba(201,168,76,.12);border:1px solid rgba(201,168,76,.3);min-width:34px;height:34px;border-radius:3px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.hl-content{flex:1}
.hl-source{font-size:14px;color:var(--gold-light);margin-bottom:6px;font-weight:600}
.hl-title{font-size:19px;font-weight:800;color:var(--cream);line-height:1.5;word-break:keep-all;text-wrap:balance}
.hl-title .kw{color:var(--gold)}
.hl-tag{display:inline-block;font-size:12px;font-weight:700;padding:3px 10px;border-radius:2px;margin-top:8px}
.tag-h{background:rgba(192,57,43,.15);color:#e74c3c;border:1px solid rgba(192,57,43,.3)}
.tag-m{background:rgba(243,156,18,.12);color:#f39c12;border:1px solid rgba(243,156,18,.3)}
.tag-i{background:rgba(52,152,219,.12);color:#5dade2;border:1px solid rgba(52,152,219,.3)}

/* ── 메인 ── */
.main-wrap{max-width:1100px;margin:0 auto;padding:52px 40px}

/* 섹션탭 숨김 */
.sec-head{display:none}

/* 카드 1열 (주제 1개 = 1페이지) */
.card-grid-2{display:grid;grid-template-columns:1fr;gap:18px;margin-bottom:48px}

/* ── 뉴스 카드 ── */
.n-card{background:var(--navy-card);border:1px solid var(--navy-border);display:flex;flex-direction:column;position:relative;overflow:hidden;transition:border-color .25s,transform .25s}
.n-card::before{content:'';position:absolute;top:0;left:0;width:100%;height:4px;background:linear-gradient(to right,var(--gold-dim),var(--gold),var(--gold-dim))}
.n-card:hover{border-color:var(--gold-dim);transform:translateY(-2px)}
.card-wm{position:absolute;bottom:46px;right:12px;font-size:10px;font-weight:700;color:rgba(201,168,76,.2);pointer-events:none;white-space:nowrap}
.n-source{display:flex;align-items:center;justify-content:space-between;background:rgba(31,50,96,.6);border-bottom:1px solid var(--navy-border);padding:8px 16px;margin-top:4px;font-size:13px}
.n-source-name{font-weight:700;color:var(--cream-dim)}
.n-source-date{color:var(--text-muted)}
.n-body{padding:16px 16px 0;flex:1}

/* 긴급 뱃지 숨김 → 주제번호 배지로 대체 */
.n-risk{display:none}
.n-topic-num{display:inline-block;font-size:12px;font-weight:700;color:var(--gold);margin-bottom:9px}

.n-cat{font-size:14px;color:var(--gold);letter-spacing:.06em;margin-bottom:7px;display:flex;align-items:center;gap:6px}
.n-cat::before{content:'';width:10px;height:1px;background:var(--gold);flex-shrink:0}
.n-title{font-size:18px;font-weight:800;color:var(--cream);line-height:1.45;margin-bottom:12px;word-break:keep-all}
.n-title .kw{color:var(--gold)}

.n-bullets{list-style:none;display:flex;flex-direction:column;gap:8px;margin-bottom:12px}
.n-bullets li{font-size:14px;color:var(--text-body);padding-left:14px;position:relative;line-height:1.7;word-break:keep-all}
.n-bullets li::before{content:'·';position:absolute;left:0;color:var(--gold);font-size:18px;line-height:1.3}
.n-bullets li strong{color:var(--cream-dim);font-weight:600}

.n-insight{background:rgba(201,168,76,.07);border:1px solid rgba(201,168,76,.2);border-left:4px solid var(--gold);padding:16px 18px}
.n-insight-label{font-size:16px;letter-spacing:.18em;color:var(--gold);font-weight:700;margin-bottom:8px}
.n-insight-text{font-size:13px;color:var(--cream-dim);line-height:1.9;word-break:keep-all;font-weight:500}

/* 해시태그 숨김 */
.n-insight-tags{display:none}

.n-footer{border-top:1px solid var(--navy-border);padding:10px 16px;margin-top:12px;display:flex;align-items:center;justify-content:space-between}
.n-footer-wm{font-size:10px;color:rgba(201,168,76,.35);font-weight:600}
.n-link{font-size:16px;font-weight:bold;color:var(--gold);text-decoration:none;display:flex;align-items:center;gap:4px;transition:color .2s}
.n-link:hover{color:var(--gold-light)}
.n-link::after{content:'→';font-size:16px}

/* ── 공유·푸터 ── */
.share-bar{max-width:1100px;margin:0 auto 44px;padding:0 40px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.share-label{font-size:12px;color:var(--text-muted)}
.share-btn{padding:9px 18px;font-size:13px;font-weight:700;border:none;border-radius:3px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;transition:opacity .2s}
.share-btn:hover{opacity:.85}
.share-kakao{background:#FEE500;color:#3A1D1D}
.share-copy{background:var(--navy-border);color:var(--cream)}
#copy-msg{font-size:12px;color:var(--gold);display:none}
.blog-footer{background:var(--navy-mid);border-top:2px solid var(--gold-dim);padding:32px 40px}
.blog-footer-inner{max-width:1100px;margin:0 auto;display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:20px}
.footer-logo{font-size:16px;font-weight:700;color:var(--gold);margin-bottom:4px}
.footer-name{font-size:13px;color:var(--text-muted);margin-bottom:6px}
.footer-url{font-size:12px;color:rgba(201,168,76,.45);font-weight:600}
.footer-copy{font-size:11px;color:rgba(201,168,76,.3);margin-top:6px;font-weight:700}
.footer-disc{font-size:11px;color:var(--navy-border);max-width:480px;line-height:1.9}

@media(max-width:780px){
  .blog-header,.hero,.main-wrap,.share-bar,.blog-footer{padding-left:20px;padding-right:20px}
  .card-grid-2{grid-template-columns:1fr}
  .headline-grid{grid-template-columns:1fr}
  .hero{padding-top:36px;padding-bottom:32px}
}"""


def make_card(n):
    """카드 HTML 생성 — labor_hr_briefing_v2 형식"""
    bullets_html = "".join(f"<li>{b}</li>" for b in n["bullets"])
    kw = n.get("keyword", "")
    title_html = (
        n["title"].replace(kw, f'<span class="kw">{kw}</span>')
        if kw and kw in n["title"] else n["title"]
    )
    # 언론사명 표시
    src = "💡 공인노무사 JP" if n.get("is_insight_card") else f"📰 {n['source']}"
    # 자세히 보기 → 실제 기사 원문 URL (인사이트 카드는 tistory)
    card_url = "https://laborjp.tistory.com" if n.get("is_insight_card") else n["url"]
    # 주제 번호 표시
    circle, sec_name = SEC_TOPIC.get(n["section_num"], ("•", n["section"]))
    topic_num = f"{circle} {sec_name}"

    return f"""<div class="n-card" id="card{n['rank']}">
  <div class="card-wm">© 공인노무사 JP</div>
  <div class="n-source">
    <span class="n-source-name">{src}</span>
    <span class="n-source-date">{n['date']}</span>
  </div>
  <div class="n-body">
    <div class="n-topic-num">{topic_num}</div>
    <div class="n-cat">{n['category']}</div>
    <h2 class="n-title">{title_html}</h2>
    <ul class="n-bullets">{bullets_html}</ul>
    <div class="n-insight">
      <div class="n-insight-label">실무 시사점</div>
      <div class="n-insight-text">{n['insight']}</div>
    </div>
  </div>
  <div class="n-footer">
    <span class="n-footer-wm">laborjp.tistory.com</span>
    <a class="n-link" href="{card_url}" target="_blank">자세히 보기</a>
  </div>
</div>"""


def make_headline(n):
    """1페이지 헤드라인 아이템 — 클릭 시 해당 카드 앵커로 이동"""
    tc = TAG_CLS.get(n["risk_level"], "tag-i")
    kw = n.get("keyword", "")
    th = (
        n["title"].replace(kw, f'<span class="kw">{kw}</span>')
        if kw and kw in n["title"] else n["title"]
    )
    # 언론사명 + 날짜 (인사이트 카드는 JP 명의)
    src = "💡 공인노무사 JP" if n.get("is_insight_card") else f"📰 {n['source']} · {n['date']}"
    # 뱃지 = 카테고리 소제목과 동일
    badge = n["category"]

    return f"""<a class="headline-item" href="#card{n['rank']}">
  <div class="hl-inner">
    <div class="hl-num">{n['rank']}</div>
    <div class="hl-content">
      <div class="hl-source">{src}</div>
      <div class="hl-title">{th}</div>
      <span class="hl-tag {tc}">{badge}</span>
    </div>
  </div>
</a>"""


# ── 섹션별 카드 조립 (섹션탭 없이 카드만) ──────────────
from collections import defaultdict
sec_groups = defaultdict(list)
for n in news_list:
    sec_groups[n["section_num"]].append(n)

sections_html = ""
for sn in sorted(sec_groups.keys()):
    for n in sec_groups[sn]:
        sections_html += f'<div class="card-grid-2">{make_card(n)}</div>'

# ── 1페이지 헤드라인 조립 ──────────────────────────────
headlines_html = "".join(make_headline(n) for n in news_list)

# ── 최종 HTML ─────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>노동·HR 주간 브리핑 {week_label} | 공인노무사 JP</title>
<meta name="description" content="{week_label} 노동·인사·HR 이슈 8건. 사장님·HR 담당자 필독.">
<meta name="keywords" content="노동법,인사노무,HR,공인노무사JP,5인미만사업장,임금체불,부당해고">
<meta name="author" content="공인노무사 JP">
<meta property="og:title" content="노동·HR 주간 브리핑 {week_label} | 공인노무사 JP">
<meta property="og:type" content="article">
<style>{CSS}</style>
</head>
<body>

<header class="blog-header">
  <div>
    <div class="blog-logo">Today's Labor &amp; HR News</div>
    <div class="blog-author">공인노무사 JP | Labor &amp; HR Weekly Brief</div>
  </div>
  <div>
    <div class="wm-badge">© 공인노무사 JP</div>
    <div class="blog-date" style="margin-top:6px">{DATE_LABEL}</div>
    <div class="blog-period">{week_label}</div>
  </div>
</header>

<!-- 1페이지: 메인 표지 -->
<section class="hero">
  <div class="hero-eyebrow">{week_label} · 노동·인사·HR 핵심 브리핑</div>
  <h1 class="hero-title">이번 주 <em>Labor &amp; HR</em> 이슈 8선</h1>
  <p class="hero-desc">사장님·HR 담당자가 반드시 알아야 할 이번 주 핵심 뉴스를<br>공인노무사 JP가 선별하고 깊이있는 실무 시사점을 정리했습니다.</p>
  <div class="headline-grid">{headlines_html}</div>
</section>

<!-- 2페이지 이후: 카드 상세 -->
<main class="main-wrap">{sections_html}</main>

<div class="share-bar">
  <span class="share-label">이 글 공유하기</span>
  <button class="share-btn share-kakao" onclick="shareKakao()">💬 카카오톡</button>
  <button class="share-btn share-copy" onclick="copyLink()">🔗 링크 복사</button>
  <span id="copy-msg">✅ 링크 복사 완료!</span>
</div>

<footer class="blog-footer">
  <div class="blog-footer-inner">
    <div>
      <div class="footer-logo">Today's Labor &amp; HR News</div>
      <div class="footer-name">공인노무사 JP | Labor &amp; HR Weekly Brief</div>
      <div class="footer-url">laborjp.tistory.com</div>
      <div class="footer-copy">© 2026 공인노무사 JP. 무단 복제·배포 금지.</div>
    </div>
    <div class="footer-disc">본 브리핑은 정보 제공 목적으로 작성된 자료입니다.<br>구체적인 사안은 전문가 상담을 권장합니다.<br>문의: laborjp.tistory.com</div>
  </div>
</footer>

<script>
function copyLink(){{navigator.clipboard.writeText(window.location.href).then(()=>{{const m=document.getElementById('copy-msg');m.style.display='inline';setTimeout(()=>{{m.style.display='none';}},2500);}})}}
function shareKakao(){{const u=encodeURIComponent(window.location.href);const t=encodeURIComponent('[노동·HR 주간 브리핑] {week_label} — 공인노무사 JP');window.open('https://sharer.kakao.com/talk/friends/picker/link?url='+u+'&text='+t,'_blank')}}
</script>
</body>
</html>"""

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"✅ 완료: {OUTPUT}")
