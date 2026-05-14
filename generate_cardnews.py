"""
JP Labor News - 텔레그램 일간 카드뉴스 생성
매주 월~금 오전 7시 자동 실행
- Naver API 7일 이내 뉴스 수집
- 인사·노무·임금·산재·건설·건자재 주제
- Claude API로 5건 카드뉴스 생성
- 텔레그램 자동 발송
"""
import os, re, json, requests, urllib.parse
from datetime import datetime, timezone, timedelta
import anthropic
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
KST      = timezone(timedelta(hours=9))
TODAY    = datetime.now(KST)
DATE_STR    = TODAY.strftime("%Y%m%d")
DATE_LABEL  = TODAY.strftime("%Y. %m. %d.")
WEEKDAY     = ["월","화","수","목","금","토","일"][TODAY.weekday()]
FOLDER   = DATE_STR
NEWS_FILE = f"labornews_{DATE_STR}.html"
SEND_FILE = f"send_{DATE_STR}.html"
VERCEL_URL = f"https://eu-labornews.vercel.app/{FOLDER}/{NEWS_FILE}"
THUMBNAIL_URL = "https://eu-labornews.vercel.app/thumbnail_telegram.png"
# ✅ 변경 1: SVG → PNG (텔레그램은 SVG 미지원)
OG_IMAGE   = "https://eu-labornews.vercel.app/thumbnail_telegram.png"
os.makedirs(FOLDER, exist_ok=True)
print(f"[{DATE_LABEL}] 텔레그램 카드뉴스 생성 시작...")
# ── Naver 뉴스 수집 ──────────────────────────────────
KEYWORDS = [
    "노란봉투법","노조법 개정","원청 사용자성 교섭",
    "삼성전자 노사 파업","SK 현대차 노동","대기업 단체교섭 임금",
    "인사노무 노동법","임금체불 단속","산업재해 중대재해",
    "노동부 고용노동부","최저임금","부당해고 노동위원회",
    "건설경기 전망","건자재 시장","시멘트 출하",
    "레미콘 건설업","건설수주 착공","건설업 노무",
    "레미콘 시멘트 가격","골재 건설자재",
    "HR 인사관리 채용","리더십 조직문화",
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
news_pool = collected[:20]
# ── Claude API 카드뉴스 생성 ─────────────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
news_text = "\n\n".join([
    f"[{i+1}] {n['title']}\n날짜:{n['pubDate']} | 링크:{n['link']}\n요약:{n['description']}"
    for i, n in enumerate(news_pool)
]) if news_pool else "수집된 뉴스 없음"
PROMPT = f"""당신은 공인노무사이자 HR 전문가입니다. 오늘은 {DATE_LABEL} {WEEKDAY}요일입니다.
아래 수집된 뉴스에서 5건을 선별하여 텔레그램 카드뉴스를 작성하세요.
수집된 뉴스:
{news_text}
【필수 순서 - 반드시 준수】
1번: 노란봉투법·노조법 개정·원청 사용자성 관련 뉴스 ⭐ 반드시 1순위
2번: 삼성·SK·현대차·LG 등 주요 대기업 노사·임금·파업 관련 뉴스 ⭐ 반드시 2순위 (삼성·SK·현대 기사 없으면 다른 주요 대기업으로 대체)
3번: 인사·노무·임금·산재·노동부 관련 핵심 이슈
4번: 건설경기·건자재·시멘트·레미콘·골재·건설수주 관련 뉴스 ⭐ 반드시 포함 (유진기업 핵심 업무)
5번: HR·인사관리·리더십 동향 (단, 돌봄·요양·서비스업 주제는 제외)
※ 1번(노란봉투법)과 2번(대기업) 뉴스가 없으면 공인노무사 JP 실무 인사이트로 대체
※ 4번 건설·건자재 뉴스가 없으면 건설업 노무·임금 관련 이슈로 대체
※ 돌봄·요양·복지서비스·음식점·소매업 관련 뉴스는 절대 포함하지 말 것
※ 5인 미만 사업장 관련 내용은 제외
【언론사 우선순위 - 반드시 준수】
1순위: 조선일보, 중앙일보, 동아일보, 연합뉴스, YTN, MBC, KBS, SBS
2순위: 한겨레, 경향신문, 한국경제, 매일경제, 서울경제, 헤럴드경제
3순위: 기타 언론사 (매일노동뉴스, 부산일보, 경남신문 등 지역·전문지)
※ 동일 주제라면 반드시 상위 언론사 기사를 선택할 것
※ 지역 언론사·전문지 기사는 메이저 언론사 기사가 없을 때만 사용
【작성 기준】
- 텔레그램용이므로 핵심만 간결하게 불릿 3개
- 실무 시사점은 1~2문장으로 짧고 임팩트 있게
- rank 순서는 반드시 위 순서대로 1~5
JSON만 응답. 다른 텍스트 절대 금지:
{{
  "news": [
    {{
      "rank": 1,
      "source": "언론사명",
      "date": "2026.05.12",
      "url": "https://실제기사URL",
      "risk_level": "high",
      "risk_label": "🔴 핵심 이슈",
      "category": "노란봉투법",
      "title": "카드 제목",
      "keyword": "강조키워드",
      "bullets": ["핵심 내용 1", "핵심 내용 2", "핵심 내용 3"],
      "insight": "실무 시사점 1~2문장",
      "is_construction": false
    }}
  ]
}}
risk_level: high(🔴), med(⚠), info(ℹ)
is_construction: 건설/건자재 관련이면 true
총 5건, rank 1~5 순서 고정"""
print("Claude API 호출 중...")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4000,
    messages=[{"role": "user", "content": PROMPT}]
)
raw = response.content[0].text.strip()
raw = re.sub(r"```json|```", "", raw).strip()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    data = json.loads(match.group()) if match else {"news":[]}
news_list = data["news"]
print(f"카드뉴스 {len(news_list)}건 생성 완료")
# ── HTML 생성 ────────────────────────────────────────
RISK_CLS = {"high":"risk-high","med":"risk-med","info":"risk-info"}
TAG_CLS  = {"high":"tag-high","med":"tag-med","info":"tag-info"}
CSS = """:root{--navy:#0a0f1e;--navy-card:#141d2e;--navy-border:#1f3260;--gold:#c9a84c;--gold-dim:#9b7d36;--cream:#f5f0e8;--cream-dim:#ccc4b0;--text-body:#c8ccd8;--text-muted:#7a8299;--base:17px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--navy);color:var(--text-body);font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:var(--base);line-height:1.7;max-width:640px;margin:0 auto}
.header{background:#111827;border-bottom:2px solid var(--gold);padding:16px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.header-logo{font-size:var(--base);font-weight:700;color:var(--gold)}
.header-date{font-size:var(--base);font-weight:700;color:#fff}
.hero{background:linear-gradient(180deg,#111827 0%,var(--navy) 100%);padding:28px 20px 24px;border-bottom:1px solid var(--navy-border)}
.hero-label{font-size:12px;letter-spacing:.2em;color:var(--gold);text-transform:uppercase;margin-bottom:10px;text-align:center}
.hero-title{font-size:26px;font-weight:900;color:var(--cream);line-height:1.2;margin-bottom:6px;text-align:center}
.hero-title span{color:var(--gold)}
.hero-sub{font-size:13px;color:var(--text-muted);line-height:1.7;text-align:center;margin-bottom:20px}
.headline-list{background:rgba(31,50,96,.3);border:1px solid var(--navy-border);border-radius:4px;overflow:hidden}
.headline-item{display:flex;align-items:flex-start;gap:12px;padding:13px 16px;border-bottom:1px solid var(--navy-border);text-decoration:none;transition:background 0.2s}
.headline-item:hover{background:rgba(31,50,96,.5)}
.headline-item:last-child{border-bottom:none}
.headline-num{font-size:11px;font-weight:700;color:var(--gold);background:rgba(201,168,76,.12);border:1px solid rgba(201,168,76,.25);min-width:22px;height:22px;border-radius:2px;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px}
.headline-content{flex:1}
.headline-source{font-size:11px;color:var(--text-muted);margin-bottom:3px}
.headline-title{font-size:15px;font-weight:700;color:var(--cream);line-height:1.45;word-break:keep-all}
.headline-tag{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:2px;margin-top:5px}
.tag-high{background:rgba(192,57,43,.15);color:#e74c3c;border:1px solid rgba(192,57,43,.3)}
.tag-med{background:rgba(243,156,18,.12);color:#f39c12;border:1px solid rgba(243,156,18,.3)}
.tag-info{background:rgba(52,152,219,.12);color:#5dade2;border:1px solid rgba(52,152,219,.3)}
.tag-construction{background:rgba(46,125,50,.15);color:#66bb6a;border:1px solid rgba(46,125,50,.3)}
.news-card{background:var(--navy-card);border:1px solid var(--navy-border);margin:16px 16px 0;border-radius:4px;overflow:hidden;position:relative}
.news-card::before{content:'';position:absolute;top:0;left:0;width:100%;height:4px;background:linear-gradient(to right,var(--gold-dim),var(--gold),var(--gold-dim))}
.source-bar{display:flex;align-items:center;justify-content:space-between;background:rgba(31,50,96,.7);border-bottom:1px solid var(--navy-border);padding:8px 16px;margin-top:4px}
.source-name{font-size:var(--base);font-weight:700;color:var(--cream-dim)}
.source-date{font-size:var(--base);color:var(--text-muted)}
.card-inner{padding:18px 16px 0}
.risk-tag{display:inline-flex;align-items:center;gap:5px;font-size:var(--base);font-weight:700;padding:5px 11px;margin-bottom:10px;border-radius:2px}
.risk-high{background:rgba(192,57,43,.15);color:#e74c3c;border:1px solid rgba(192,57,43,.3)}
.risk-med{background:rgba(243,156,18,.12);color:#f39c12;border:1px solid rgba(243,156,18,.3)}
.risk-info{background:rgba(52,152,219,.12);color:#5dade2;border:1px solid rgba(52,152,219,.3)}
.card-category{font-size:var(--base);color:var(--gold);margin-bottom:8px;display:flex;align-items:center;gap:6px}
.card-category::before{content:'';width:10px;height:1px;background:var(--gold);display:inline-block;flex-shrink:0}
.card-title{font-size:20px;font-weight:700;color:var(--cream);line-height:1.45;margin-bottom:16px;word-break:keep-all}
.bullet-list{list-style:none;display:flex;flex-direction:column;gap:10px;margin-bottom:14px}
.bullet-list li{font-size:15px;color:var(--text-body);padding-left:16px;position:relative;line-height:1.7;word-break:keep-all}
.bullet-list li::before{content:'·';position:absolute;left:0;color:var(--gold);font-size:22px;line-height:1.2}
.insight{background:rgba(201,168,76,.07);border:1px solid rgba(201,168,76,.2);border-left:4px solid var(--gold);padding:13px 14px}
.insight-label{font-size:11px;letter-spacing:.15em;text-transform:uppercase;color:var(--gold);font-weight:700;margin-bottom:5px}
.insight-text{font-size:14px;color:var(--cream-dim);line-height:1.8;word-break:keep-all}
.read-more{border-top:1px solid var(--navy-border);padding:12px 16px;margin-top:14px;display:flex;justify-content:space-between;align-items:center}
.read-more a{font-size:13px;font-weight:700;color:var(--gold);text-decoration:none;display:flex;align-items:center;gap:6px}
.read-more a::after{content:'→';font-size:15px}
.wm-small{font-size:10px;color:rgba(201,168,76,.3);font-weight:600}
.footer{border-top:1px solid var(--navy-border);background:#111827;padding:24px 20px;text-align:center;margin-top:16px}
.footer-logo{font-size:14px;font-weight:700;color:var(--gold);margin-bottom:6px}
.footer-disc{font-size:11px;color:var(--text-muted);line-height:1.8}"""
headlines_html = ""
for n in news_list:
    tc = TAG_CLS.get(n["risk_level"],"tag-info")
    if n.get("is_construction"):
        tc = "tag-construction"
    headlines_html += f"""<a class="headline-item" href="#news{n['rank']}">
  <div class="headline-num">{n['rank']}</div>
  <div class="headline-content">
    <div class="headline-source">📰 {n['source']} · {n['date']}</div>
    <div class="headline-title">{n['title']}</div>
    <span class="headline-tag {tc}">{n['risk_label']}</span>
  </div>
</a>"""
cards_html = ""
for n in news_list:
    bullets = "".join(f"<li>{b}</li>" for b in n["bullets"])
    rc = RISK_CLS.get(n["risk_level"],"risk-info")
    construction_badge = ' <span style="font-size:10px;background:rgba(46,125,50,.15);color:#66bb6a;border:1px solid rgba(46,125,50,.3);padding:2px 6px;border-radius:2px">🏗 건설·건자재</span>' if n.get("is_construction") else ""
    cards_html += f"""<div class="news-card" id="news{n['rank']}">
  <div class="source-bar"><span class="source-name">📰 {n['source']}{construction_badge}</span><span class="source-date">{n['date']}</span></div>
  <div class="card-inner">
    <div class="risk-tag {rc}">{n['risk_label']}</div>
    <div class="card-category">{n['category']}</div>
    <h2 class="card-title">{n['title']}</h2>
    <ul class="bullet-list">{bullets}</ul>
    <div class="insight"><div class="insight-label">실무 시사점</div><div class="insight-text">{n['insight']}</div></div>
  </div>
  <div class="read-more"><span class="wm-small">© JP Labor News</span><a href="{n['url']}" target="_blank">자세히 보기</a></div>
</div>"""
NEWS_HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Today's Labor News — {DATE_LABEL} | 공인노무사 JP</title>
<meta name="description" content="오늘의 인사노무 핵심 브리핑. 노동법·노사·HR 이슈 5건.">
<meta property="og:title" content="Today's Labor News — {DATE_LABEL} | 공인노무사 JP">
<meta property="og:description" content="노란봉투법·대기업 노사·임금체불·건설경기 등 오늘의 핵심 이슈 5건">
<meta property="og:type" content="article">
<meta property="og:url" content="{VERCEL_URL}">
<meta property="og:image" content="{OG_IMAGE}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="JP Labor News">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{OG_IMAGE}">
<style>{CSS}</style>
</head>
<body>
<header class="header"><div class="header-logo">Today's Labor News</div><div class="header-date">{DATE_LABEL}</div></header>
<section class="hero">
  <div class="hero-label">인사노무 핵심 브리핑</div>
  <h1 class="hero-title">오늘의 <span>Labor</span> 이슈</h1>
  <p class="hero-sub">꼭 알아야 할 핵심 이슈</p>
  <div class="headline-list">{headlines_html}</div>
</section>
{cards_html}
<div style="height:24px"></div>
<footer class="footer">
  <div class="footer-logo">JP Labor News</div>
  <div class="footer-disc">Powered by Claude AI · 자동 생성<br>본 카드뉴스는 정보 제공 목적입니다.<br>© 2026 JP Labor News</div>
</footer>
</body>
</html>"""
# send 페이지 (수동 발송용 — 유지)
tg_lines = [f"📋 오늘의 인사노무 브리핑 — {DATE_LABEL} ({WEEKDAY})\n"]
for n in news_list:
    emoji = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"][n["rank"]-1]
    tg_lines.append(f"{emoji} {n['title']}")
tg_lines.append(f"\n🔗 전체 카드뉴스:\n{VERCEL_URL}")
tg_text = "\n".join(tg_lines)
tg_photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
tg_api_url = f"{tg_photo_url}?chat_id={urllib.parse.quote(str(TELEGRAM_CHAT_ID))}&photo={urllib.parse.quote(THUMBNAIL_URL)}&caption={urllib.parse.quote(tg_text[:1024])}"
items_html = "".join(
    f'<div class="news-item"><span class="news-num">{n["rank"]}</span>{n["title"]}</div>'
    for n in news_list
)
SEND_HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>텔레그램 발송</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0f1e;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}.card{{background:#141d2e;border:1px solid #1f3260;border-radius:8px;padding:32px 28px;max-width:400px;width:100%;text-align:center}}.icon{{font-size:48px;margin-bottom:16px}}.title{{font-size:20px;font-weight:700;color:#f5f0e8;margin-bottom:6px}}.date{{font-size:13px;color:#7a8299;margin-bottom:24px}}.news-list{{background:rgba(31,50,96,.4);border:1px solid #1f3260;border-radius:4px;padding:16px;margin-bottom:24px;text-align:left}}.news-list-title{{font-size:11px;letter-spacing:.15em;color:#c9a84c;text-transform:uppercase;margin-bottom:12px;font-weight:700}}.news-item{{font-size:13px;color:#c8ccd8;padding:7px 0;border-bottom:1px solid rgba(31,50,96,.6);line-height:1.5;display:flex;gap:8px}}.news-item:last-child{{border-bottom:none}}.news-num{{color:#c9a84c;font-weight:700;flex-shrink:0}}.btn{{display:block;width:100%;padding:16px;background:#0088cc;color:#fff;font-size:16px;font-weight:700;border:none;border-radius:6px;cursor:pointer;text-decoration:none;margin-bottom:12px}}.btn-view{{display:block;width:100%;padding:14px;background:transparent;color:#c9a84c;font-size:14px;font-weight:700;border:1px solid #c9a84c;border-radius:6px;text-decoration:none}}.notice{{font-size:11px;color:#7a8299;margin-top:16px;line-height:1.7}}</style>
</head>
<body><div class="card">
  <div class="icon">📨</div>
  <div class="title">오늘의 카드뉴스 발송</div>
  <div class="date">{DATE_LABEL} {WEEKDAY}요일</div>
  <div class="news-list"><div class="news-list-title">오늘의 헤드라인</div>{items_html}</div>
  <a class="btn" href="{tg_api_url}" target="_blank">📲 텔레그램으로 발송하기</a>
  <a class="btn-view" href="{VERCEL_URL}" target="_blank">전체 카드뉴스 보기</a>
  <div class="notice">버튼을 클릭하면 텔레그램으로<br>헤드라인과 카드뉴스 링크가 전송됩니다.</div>
</div></body>
</html>"""
# 파일 저장
with open(f"{FOLDER}/{NEWS_FILE}", "w", encoding="utf-8") as f:
    f.write(NEWS_HTML)
with open(f"{FOLDER}/{SEND_FILE}", "w", encoding="utf-8") as f:
    f.write(SEND_HTML)
# ✅ 변경 2: sendPhoto + 캡션에 링크만 (썸네일 직접 전송)
resp = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
    data={
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": THUMBNAIL_URL,   # 썸네일 직접 전송
        "caption": VERCEL_URL,    # 캡션에 링크만
        "parse_mode": "HTML",
    },
    timeout=10
)
if resp.json().get("ok"):
    print("✅ 텔레그램 발송 성공!")
else:
    print(f"❌ 텔레그램 발송 실패: {resp.text}")
print(f"✅ 완료: {FOLDER}/{NEWS_FILE}")
