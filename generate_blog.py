"""
JP Labor & HR Blog - 자동 블로그 카드뉴스 생성 스크립트
매일 오전 8시 GitHub Actions에서 자동 실행
- Naver API로 7일 이내 최신 뉴스만 수집
- Claude API로 요약 + 실무 시사점 생성
- 워터마크 포함 HTML 카드뉴스 자동 생성
"""

import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta

# ── 설정 ──────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]

KST     = timezone(timedelta(hours=9))
TODAY   = datetime.now(KST)
DATE_STR   = TODAY.strftime("%Y%m%d")
DATE_LABEL = TODAY.strftime("%Y. %m. %d.")
DATE_KO    = TODAY.strftime("%Y년 %m월 %d일")
WEEKDAY    = ["월","화","수","목","금","토","일"][TODAY.weekday()]
WEEK_NUM   = (TODAY.day - 1) // 7 + 1
WEEK_KO    = ["첫","둘","셋","넷","다섯"][WEEK_NUM - 1]

FOLDER    = f"blog"
FILE_NAME = f"blog_{DATE_STR}.html"
OUTPUT    = f"{FOLDER}/{FILE_NAME}"

os.makedirs(FOLDER, exist_ok=True)
print(f"[{DATE_LABEL}] 블로그 카드뉴스 생성 시작...")

# ── Naver 뉴스 수집 (7일 이내만) ──────────────────────
KEYWORDS = [
    "임금체불",
    "부당해고",
    "최저임금",
    "중대재해",
    "노동조합 파업",
    "고용노동부",
    "근로기준법",
    "5인미만 사업장",
    "HR 채용 트렌드",
    "직장내괴롭힘",
]

headers = {
    "X-Naver-Client-Id": NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}

seven_days_ago = TODAY - timedelta(days=7)
collected = []

for keyword in KEYWORDS:
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params={"query": keyword, "sort": "date", "display": 5},
            timeout=10,
        )
        items = resp.json().get("items", [])
        for item in items:
            pub_str = item.get("pubDate", "")
            try:
                pub_dt = datetime.strptime(pub_str, "%a, %d %b %Y %H:%M:%S %z")
                pub_kst = pub_dt.astimezone(KST)
                # 7일 이내 기사만
                if pub_kst >= seven_days_ago:
                    collected.append({
                        "title": re.sub(r"<[^>]+>", "", item.get("title", "")),
                        "link": item.get("originallink") or item.get("link", ""),
                        "description": re.sub(r"<[^>]+>", "", item.get("description", "")),
                        "pubDate": pub_kst.strftime("%Y.%m.%d"),
                        "keyword": keyword,
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"키워드 '{keyword}' 수집 오류: {e}")

# 중복 제거 (제목 기준)
seen, unique = set(), []
for item in collected:
    key = item["title"][:20]
    if key not in seen:
        seen.add(key)
        unique.append(item)

print(f"7일 이내 뉴스 {len(unique)}건 수집 완료")

# 8건으로 제한
news_pool = unique[:20]

# ── Claude API로 뉴스 선별 + 카드뉴스 데이터 생성 ─────
import anthropic
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

news_text = "\n\n".join([
    f"[{i+1}] {n['title']}\n날짜: {n['pubDate']}\n링크: {n['link']}\n요약: {n['description']}"
    for i, n in enumerate(news_pool)
]) if news_pool else "수집된 뉴스 없음"

PROMPT = f"""
오늘은 {DATE_LABEL} {WEEKDAY}요일입니다.

당신은 공인노무사이자 HR 전문가입니다.
아래 수집된 뉴스 목록에서 경영자·사장님·HR 담당자에게 가장 중요한 뉴스 8건을 선별하고,
각각에 대해 실무 시사점을 작성해 주세요.

수집된 뉴스:
{news_text}

※ 뉴스가 8건 미만이면 공인노무사 JP의 실무 인사이트로 나머지를 채워주세요.
  인사이트 형식: 뉴스가 아닌 "JP의 노무 인사이트" 카드로, 실무에서 자주 묻는 질문이나 주의사항을 다룹니다.

다음 섹션 구조로 8건을 배분해 주세요:
① 노사 핫이슈 (2건): 파업, 노조, 원청 교섭
② 판례·단속 (2건): 부당해고, 직장갑질, 산재, 임금체불 단속
③ 사장님 체크포인트 (2건): 인건비, 고용지원금, 정책 변화
④ 5인 미만 사업장 필독 (1건): 소상공인·자영업자 노동법
⑤ HR 동향 (1건): 채용, 임금, AI, 조직문화 트렌드

JSON만 응답하세요. 다른 텍스트 절대 포함 금지.

{{
  "period": "{DATE_KO} ({WEEKDAY}요일)",
  "week_label": "{TODAY.year}년 {TODAY.month}월 {WEEK_KO}째주",
  "news": [
    {{
      "rank": 1,
      "section": "노사 핫이슈",
      "section_num": 1,
      "source": "언론사명",
      "date": "2026.05.11",
      "url": "https://실제기사URL",
      "risk_level": "high",
      "risk_label": "🔴 긴급",
      "category": "카테고리",
      "title": "카드 제목",
      "keyword": "강조키워드",
      "bullets": ["핵심 내용 1", "핵심 내용 2", "핵심 내용 3"],
      "insight": "실무 시사점",
      "is_insight_card": false
    }}
  ]
}}

risk_level: high(빨강), med(주황), info(파랑) 중 선택
is_insight_card: 뉴스가 아닌 JP 인사이트 카드이면 true
"""

print("Claude API 호출 중...")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4000,
    messages=[{"role": "user", "content": PROMPT}]
)

raw = response.content[0].text.strip()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    clean = re.sub(r"```json|```", "", raw).strip()
    data = json.loads(clean)

news_list   = data["news"]
week_label  = data.get("week_label", f"{TODAY.year}년 {TODAY.month}월 {WEEK_KO}째주")
print(f"카드뉴스 데이터 {len(news_list)}건 생성 완료")

# ── HTML 생성 ──────────────────────────────────────────
RISK_CLASS = {"high": "r-h", "med": "r-m", "info": "r-i"}
TAG_CLASS  = {"high": "tag-h", "med": "tag-m", "info": "tag-i"}

SECTIONS = {1: "① 노사 핫이슈", 2: "② 판례 · 단속", 3: "③ 사장님 체크포인트", 4: "④ 5인 미만 사업장 필독", 5: "⑤ HR 동향"}

CSS = """
:root{--navy:#0a0f1e;--navy-mid:#111827;--navy-card:#141d2e;--navy-border:#1f3260;--gold:#c9a84c;--gold-dim:#9b7d36;--gold-light:#e2c278;--cream:#f5f0e8;--cream-dim:#ccc4b0;--text-body:#c8ccd8;--text-muted:#7a8299;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--navy);color:var(--text-body);font-family:'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;font-size:16px;line-height:1.75;}
.blog-header{background:var(--navy-mid);border-bottom:2px solid var(--gold);padding:16px 40px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;}
.blog-logo{font-size:20px;font-weight:700;color:var(--gold);}
.blog-author{font-size:13px;color:var(--text-muted);margin-top:3px;}
.wm-badge{display:inline-flex;align-items:center;gap:5px;background:rgba(201,168,76,0.12);border:1px solid rgba(201,168,76,0.35);border-radius:3px;padding:4px 10px;font-size:11px;font-weight:700;color:var(--gold);}
.blog-date{font-size:15px;font-weight:700;color:#fff;text-align:right;}
.blog-period{font-size:12px;color:var(--text-muted);text-align:right;margin-top:3px;}
.hero{background:linear-gradient(160deg,#111827 0%,#0d1628 50%,var(--navy) 100%);padding:52px 40px 44px;border-bottom:1px solid var(--navy-border);text-align:center;}
.hero-eyebrow{font-size:11px;letter-spacing:0.25em;color:var(--gold);text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;justify-content:center;gap:12px;}
.hero-eyebrow::before,.hero-eyebrow::after{content:'';width:32px;height:1px;background:var(--gold);}
.hero-title{font-size:clamp(26px,4vw,44px);font-weight:900;color:var(--cream);line-height:1.15;margin-bottom:12px;}
.hero-title em{color:var(--gold);font-style:italic;}
.hero-desc{font-size:14px;color:var(--text-muted);max-width:560px;margin:0 auto 28px;line-height:1.8;}
.headline-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:2px;max-width:900px;margin:0 auto;background:var(--navy-border);border:1px solid var(--navy-border);}
.headline-item{background:rgba(31,50,96,0.35);padding:16px 18px;display:flex;align-items:flex-start;gap:13px;}
.hl-num{font-size:11px;font-weight:700;color:var(--gold);background:rgba(201,168,76,0.12);border:1px solid rgba(201,168,76,0.3);min-width:26px;height:26px;border-radius:3px;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px;}
.hl-content{flex:1;}
.hl-source{font-size:11px;color:var(--text-muted);margin-bottom:4px;}
.hl-title{font-size:15px;font-weight:800;color:var(--cream);line-height:1.45;word-break:keep-all;}
.hl-title .kw{color:var(--gold);}
.hl-tag{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:2px;margin-top:6px;}
.tag-h{background:rgba(192,57,43,0.15);color:#e74c3c;border:1px solid rgba(192,57,43,0.3);}
.tag-m{background:rgba(243,156,18,0.12);color:#f39c12;border:1px solid rgba(243,156,18,0.3);}
.tag-i{background:rgba(52,152,219,0.12);color:#5dade2;border:1px solid rgba(52,152,219,0.3);}
.main-wrap{max-width:1100px;margin:0 auto;padding:52px 40px;}
.sec-head{display:flex;align-items:center;gap:14px;margin-bottom:24px;padding-bottom:12px;border-bottom:1px solid var(--navy-border);}
.sec-icon{background:rgba(201,168,76,0.1);border:1px solid var(--gold-dim);color:var(--gold);font-size:15px;font-weight:700;padding:5px 13px;flex-shrink:0;}
.sec-line{flex:1;height:1px;background:linear-gradient(to right,var(--navy-border),transparent);}
.card-grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;margin-bottom:48px;}
.n-card{background:var(--navy-card);border:1px solid var(--navy-border);display:flex;flex-direction:column;position:relative;overflow:hidden;transition:border-color 0.25s,transform 0.25s;}
.n-card::before{content:'';position:absolute;top:0;left:0;width:100%;height:4px;background:linear-gradient(to right,var(--gold-dim),var(--gold),var(--gold-dim));}
.n-card:hover{border-color:var(--gold-dim);transform:translateY(-2px);}
.card-wm{position:absolute;bottom:46px;right:12px;font-size:10px;font-weight:700;color:rgba(201,168,76,0.2);pointer-events:none;white-space:nowrap;}
.insight-card::before{background:linear-gradient(to right,#1f3260,#c9a84c,#1f3260);}
.n-source{display:flex;align-items:center;justify-content:space-between;background:rgba(31,50,96,0.6);border-bottom:1px solid var(--navy-border);padding:8px 16px;margin-top:4px;font-size:13px;}
.n-source-name{font-weight:700;color:var(--cream-dim);}
.n-source-date{color:var(--text-muted);}
.n-body{padding:16px 16px 0;flex:1;}
.n-risk{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:700;padding:4px 10px;margin-bottom:9px;border-radius:2px;}
.r-h{background:rgba(192,57,43,0.15);color:#e74c3c;border:1px solid rgba(192,57,43,0.3);}
.r-m{background:rgba(243,156,18,0.12);color:#f39c12;border:1px solid rgba(243,156,18,0.3);}
.r-i{background:rgba(52,152,219,0.12);color:#5dade2;border:1px solid rgba(52,152,219,0.3);}
.n-cat{font-size:12px;color:var(--gold);letter-spacing:0.06em;margin-bottom:7px;display:flex;align-items:center;gap:6px;}
.n-cat::before{content:'';width:10px;height:1px;background:var(--gold);flex-shrink:0;}
.n-title{font-size:18px;font-weight:800;color:var(--cream);line-height:1.45;margin-bottom:12px;word-break:keep-all;}
.n-title .kw{color:var(--gold);}
.n-bullets{list-style:none;display:flex;flex-direction:column;gap:8px;margin-bottom:12px;}
.n-bullets li{font-size:14px;color:var(--text-body);padding-left:14px;position:relative;line-height:1.7;word-break:keep-all;}
.n-bullets li::before{content:'·';position:absolute;left:0;color:var(--gold);font-size:18px;line-height:1.3;}
.n-bullets li strong{color:var(--cream-dim);font-weight:600;}
.n-insight{background:rgba(201,168,76,0.07);border:1px solid rgba(201,168,76,0.2);border-left:4px solid var(--gold);padding:11px 13px;}
.n-insight-label{font-size:10px;letter-spacing:0.18em;text-transform:uppercase;color:var(--gold);font-weight:700;margin-bottom:4px;}
.n-insight-text{font-size:13px;color:var(--cream-dim);line-height:1.8;word-break:keep-all;}
.n-footer{border-top:1px solid var(--navy-border);padding:10px 16px;margin-top:12px;display:flex;align-items:center;justify-content:space-between;}
.n-footer-wm{font-size:10px;color:rgba(201,168,76,0.35);font-weight:600;}
.n-link{font-size:12px;font-weight:700;color:var(--gold);text-decoration:none;display:flex;align-items:center;gap:4px;transition:color 0.2s;}
.n-link:hover{color:var(--gold-light);}
.n-link::after{content:'→';font-size:14px;}
.share-bar{max-width:1100px;margin:0 auto 44px;padding:0 40px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
.share-label{font-size:12px;color:var(--text-muted);}
.share-btn{padding:9px 18px;font-size:13px;font-weight:700;border:none;border-radius:3px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;transition:opacity 0.2s;}
.share-btn:hover{opacity:0.85;}
.share-kakao{background:#FEE500;color:#3A1D1D;}
.share-copy{background:var(--navy-border);color:var(--cream);}
#copy-msg{font-size:12px;color:var(--gold);display:none;}
.blog-footer{background:var(--navy-mid);border-top:2px solid var(--gold-dim);padding:32px 40px;}
.blog-footer-inner{max-width:1100px;margin:0 auto;display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:20px;}
.footer-logo{font-size:16px;font-weight:700;color:var(--gold);margin-bottom:4px;}
.footer-name{font-size:13px;color:var(--text-muted);margin-bottom:6px;}
.footer-url{font-size:12px;color:rgba(201,168,76,0.45);font-weight:600;}
.footer-copy{font-size:11px;color:rgba(201,168,76,0.3);margin-top:6px;font-weight:700;}
.footer-disc{font-size:11px;color:var(--navy-border);max-width:480px;line-height:1.9;}
@media(max-width:780px){.blog-header,.hero,.main-wrap,.share-bar,.blog-footer{padding-left:20px;padding-right:20px;}.card-grid-2{grid-template-columns:1fr;}.headline-grid{grid-template-columns:1fr;}.hero{padding-top:36px;padding-bottom:32px;}}
"""

def make_card(n):
    bullets_html = "".join(f"<li>{b}</li>" for b in n["bullets"])
    risk_cls = RISK_CLASS.get(n["risk_level"], "r-i")
    kw = n.get("keyword", "")
    title_html = n["title"].replace(kw, f'<span class="kw">{kw}</span>') if kw and kw in n["title"] else n["title"]
    card_cls = "n-card insight-card" if n.get("is_insight_card") else "n-card"
    source_label = "💡 공인노무사 JP 인사이트" if n.get("is_insight_card") else f"📰 {n['source']}"
    link_html = f'<a class="n-link" href="{n["url"]}" target="_blank">자세히 보기</a>' if not n.get("is_insight_card") else '<span style="font-size:12px;color:var(--gold);">JP 실무 노트</span>'
    return f"""
<div class="{card_cls}">
  <div class="card-wm">© 공인노무사 JP</div>
  <div class="n-source"><span class="n-source-name">{source_label}</span><span class="n-source-date">{n['date']}</span></div>
  <div class="n-body">
    <div class="n-risk {risk_cls}">{n['risk_label']}</div>
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
    {link_html}
  </div>
</div>"""

# 섹션별 그룹핑
from collections import defaultdict
sections = defaultdict(list)
for n in news_list:
    sections[n["section_num"]].append(n)

sections_html = ""
for sec_num in sorted(sections.keys()):
    sec_label = SECTIONS.get(sec_num, f"섹션 {sec_num}")
    cards_html = "".join(make_card(n) for n in sections[sec_num])
    sections_html += f"""
<div class="sec-head"><div class="sec-icon">{sec_label}</div><div class="sec-line"></div></div>
<div class="card-grid-2">{cards_html}</div>"""

# 헤드라인
headlines_html = ""
for n in news_list:
    tag_cls = TAG_CLASS.get(n["risk_level"], "tag-i")
    kw = n.get("keyword", "")
    title_hl = n["title"].replace(kw, f'<span class="kw">{kw}</span>') if kw and kw in n["title"] else n["title"]
    source_hl = "💡 JP 인사이트" if n.get("is_insight_card") else f"📰 {n['source']} · {n['date']}"
    headlines_html += f"""
<div class="headline-item">
  <div class="hl-num">{n['rank']}</div>
  <div class="hl-content">
    <div class="hl-source">{source_hl}</div>
    <div class="hl-title">{title_hl}</div>
    <span class="hl-tag {tag_cls}">{n['risk_label']}</span>
  </div>
</div>"""

HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>노동·HR 주간 브리핑 {week_label} | 공인노무사 JP</title>
<meta name="description" content="{week_label} 주요 노동·인사·HR 이슈. 경영자·사장님·HR 담당자 필독 브리핑.">
<meta name="keywords" content="노동법,인사노무,HR,공인노무사JP,노동뉴스,임금체불,부당해고,5인미만">
<meta name="author" content="공인노무사 JP">
<meta property="og:title" content="노동·HR 주간 브리핑 {week_label} | 공인노무사 JP">
<meta property="og:type" content="article">
<style>{CSS}</style>
</head>
<body>
<header class="blog-header">
  <div><div class="blog-logo">Today's Labor &amp; HR News</div><div class="blog-author">공인노무사 JP | Labor &amp; HR Weekly Brief</div></div>
  <div><div class="wm-badge">© 공인노무사 JP</div><div class="blog-date" style="margin-top:6px;">{DATE_LABEL}</div><div class="blog-period">{week_label}</div></div>
</header>
<section class="hero">
  <div class="hero-eyebrow">{week_label} · 노동·인사·HR 핵심 브리핑</div>
  <h1 class="hero-title">이번 주 <em>Labor &amp; HR</em> 이슈 8선</h1>
  <p class="hero-desc">사장님·HR 담당자가 반드시 알아야 할 이번 주 핵심 뉴스를<br>선별하고 실무 시사점을 정리했습니다.</p>
  <div class="headline-grid">{headlines_html}</div>
</section>
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
function copyLink(){{navigator.clipboard.writeText(window.location.href).then(()=>{{const m=document.getElementById('copy-msg');m.style.display='inline';setTimeout(()=>{{m.style.display='none';}},2500);}});}}
function shareKakao(){{const url=encodeURIComponent(window.location.href);const text=encodeURIComponent('[노동·HR 주간 브리핑] {week_label} — 공인노무사 JP');window.open('https://sharer.kakao.com/talk/friends/picker/link?url='+url+'&text='+text,'_blank');}}
</script>
</body>
</html>"""

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"✅ 완료: {OUTPUT}")
