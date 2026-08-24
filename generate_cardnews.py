"""
JP Labor News - 텔레그램 일간 카드뉴스 생성
매주 월~금 오전 7시 자동 실행
- Naver API 7일 이내 뉴스 수집
- 고용노동부·국회 노동 이슈 + 인사노무 주제
- Claude API로 5건 카드뉴스 생성
- 텔레그램 자동 발송
"""
import os, re, json, requests, urllib.parse
import socket, shutil, threading, http.server, socketserver
from datetime import datetime, timezone, timedelta
import anthropic

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
# 카카오톡 공유 JS 키 (선택 — 없으면 카카오 공유 버튼 미노출)
KAKAO_JS_KEY        = os.environ.get("KAKAO_JS_KEY", "")

KST      = timezone(timedelta(hours=9))
TODAY    = datetime.now(KST)
DATE_STR    = TODAY.strftime("%Y%m%d")
DATE_LABEL  = TODAY.strftime("%Y. %m. %d.")
DATE_SHORT  = f"{TODAY.month}/{TODAY.day}"
WEEKDAY     = ["월","화","수","목","금","토","일"][TODAY.weekday()]

FOLDER    = DATE_STR
NEWS_FILE = f"labornews_{DATE_STR}.html"
SEND_FILE = f"send_{DATE_STR}.html"
PNG_FILE  = f"labornews_{DATE_STR}.png"
VERCEL_URL = f"https://eu-labornews.vercel.app/{FOLDER}/{NEWS_FILE}"
REPO_ROOT  = os.path.dirname(os.path.abspath(__file__))

# OG 이미지: 쿼리스트링으로 매일 새 이미지로 인식
OG_IMAGE = f"https://eu-labornews.vercel.app/thumbnail_telegram.png?v={DATE_STR}"

os.makedirs(FOLDER, exist_ok=True)
print(f"[{DATE_LABEL}] 텔레그램 카드뉴스 생성 시작...")

# ── Naver 뉴스 수집 ──────────────────────────────────
KEYWORDS = [
    # ① 노동법·노사관계
    "노란봉투법", "노조법 개정", "원청 사용자성 교섭",
    "단체교섭 결렬", "노사분규 파업", "노동조합 쟁의",
    "부당노동행위",
    # ② 대기업 노사
    "삼성전자 노사 파업", "현대차 기아 노동", "SK 하이닉스 노조",
    "LG 롯데 노사", "셀트리온 노조", "대기업 임금교섭",
    # ③ 중견·중소·스타트업 노사
    "중소기업 임금 체불", "중견기업 노사 갈등",
    "스타트업 인력 구조조정", "중소기업 인사 노무",
    # ④ 건설업 노동
    "건설현장 산재 안전", "건설 노조 파업",
    "건설 일용직 임금", "건설업 외국인 근로자",
    "건설업 고용보험",
    # ⑤ 제조·물류·유통 노동
    "제조업 노사 임금", "물류 배송 택배 노동",
    "유통 마트 노동조합", "반도체 노동 안전",
    "자동차 부품 노사",
    # ⑥ IT·금융·서비스업 노동
    "IT 게임 스타트업 노동", "금융권 노조 교섭",
    "병원 의료 노동자", "항공 승무원 노사",
    "호텔 서비스업 노동",
    # ⑦ 임금·근로시간
    "최저임금 인상", "통상임금 퇴직금", "임금체불 단속",
    "주52시간 유연근무", "포괄임금제 판결", "연장근로 수당",
    "성과급 연봉 보상",
    # ⑧ 해고·징계·판결
    "부당해고 노동위원회", "정리해고 구조조정",
    "해고 판결 복직", "징계 해고 판결",
    "노동 판결 대법원",
    # ⑨ 산재·안전·중대재해
    "산업재해 중대재해", "중대재해처벌법 판결",
    "사망사고 산업안전", "직업병 산재 인정",
    # ⑩ 특수고용·플랫폼·비정규직
    "플랫폼 노동자 보호", "특수고용 산재",
    "배달기사 근로자성", "기간제 파견 노동",
    "비정규직 정규직 전환",
    # ⑪ 외국인·이주노동
    "외국인 근로자 고용허가", "이주노동자 권리",
    # ⑫ 직장내 괴롭힘·차별·고령·청년
    "직장내괴롭힘 징계", "직장 성희롱 처벌",
    "정년연장 계속고용", "청년 취업 일자리",
    "육아휴직 출산 보육",
    # ⑬ 고용노동부·정책·국회
    "고용노동부 정책 고시", "고용노동부 지침 행정해석",
    "고용노동부 단속 과태료", "국회 환경노동위원회",
    "노동법 개정안 입법", "정부 노동정책 발표",
    "고용보험 실업급여",
    # ⑭ HR·조직문화·인재
    "HR 인사관리 채용", "리더십 조직문화",
    "원격근무 재택 하이브리드", "MZ 세대 직장문화",
    "인사평가 성과관리",
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
아래 수집된 뉴스에서 7건을 선별하여 텔레그램 카드뉴스를 작성하세요.

수집된 뉴스:
{news_text}

【카드 7장 구성 — 2+4+1 구조】
━━ [노동법 2장] ━━
오늘 노동·HR 이슈 전체를 검토해 파급력 기준 상위 2건을 선정하세요.
아래 범주 중에서 자유롭게 선택하되, 1번과 2번은 반드시 다른 범주:
  · 노사관계: 노란봉투법·노조법 개정·원청 사용자성·단체교섭·파업·쟁의·부당노동행위
  · 임금·근로시간: 최저임금·통상임금·연장근로·포괄임금제·임금체불·성과급·퇴직금·주52시간
  · 산재·중대재해: 중대재해처벌법 판결·기소, 산업재해 사망사고, 직업병 인정, 안전보건
  · 해고·판결: 부당해고·정리해고·해고복직 판결, 노동위 판정, 대법원 노동 판결

1번 — 노동법 핵심 ① (위 4개 범주 중 오늘 가장 파급력 큰 이슈)
2번 — 노동법 핵심 ② (1번과 다른 범주에서 오늘의 두 번째 핵심 이슈)
  → 대기업(삼성·SK·현대차·LG) 기사는 1·2번 합쳐서 최대 1건으로 제한

━━ [업종별 4장] ━━
3번 — 건설·토목 업종
  · 건설현장 산재·안전, 건설 노조, 건설 일용직·임금체불, 토목·플랜트 노동
  · 건설업 외국인 근로자, 건설사 경영위기·구조조정 이슈
  · 해당 뉴스 없으면 → 조선·중공업 노사 이슈로 대체

4번 — 제조·물류·운수 업종
  · 제조업(자동차·반도체·철강·화학) 노사·임금·구조조정
  · 물류·택배·배달 노동, 트럭운전·버스·운수업 노사
  · 해당 뉴스 없으면 → 플랫폼·배달기사·특수고용 이슈로 대체

5번 — IT·게임·스타트업·금융 업종
  · IT·게임·스타트업 인사(구조조정·성과급·무급휴직·원격근무·MZ직장문화)
  · 금융·보험·증권·핀테크 노조·임금·경영
  · 해당 뉴스 없으면 → 미디어·방송·콘텐츠 업종 노사로 대체

6번 — 유통·의료·서비스·항공 업종
  · 대형마트·편의점·이커머스 노동, 병원·의원·요양 종사자 노사
  · 항공·승무원·여행 업종, 호텔·외식 노동
  · 해당 뉴스 없으면 → 외국인 근로자·이주노동 이슈로 대체

━━ [정책·HR 1장] ━━
7번 — 정책·HR·사회 트렌드 (택 1)
  · 고용노동부 정책·지침·행정해석·단속·과태료, 국회 노동법 개정안
  · 정년연장·계속고용, 청년·여성·육아휴직·저출생 대책
  · 직장내 괴롭힘·성희롱 처리, 4대보험·실업급여 제도 개편
  · HR 트렌드·인사평가·조직문화, 원격근무·하이브리드 워크
  · 오늘 가장 새롭고 현장 실무에 바로 쓸 수 있는 것

※ 각 카드는 서로 다른 기사·주제 사용 (중복 금지)
※ 노란봉투법·노조법 개정·원청 사용자성은 7장 전체에서 단 1건만 허용 — 같은 주제의 후속 보도·파생 기사도 동일하게 간주하여 중복 금지
※ 대기업(삼성·SK·현대차·LG) 기사는 1~2번 합쳐서 최대 1건, 3~6번에서 최대 1건으로 제한 — 나머지는 중소·중견·다업종
※ 돌봄·요양·복지서비스·음식점·소매업·농업·종교 뉴스는 절대 포함하지 말 것
※ 5인 미만 사업장 단독 이슈는 제외 (뉴스레터에서 별도 다룸)

【언론사 우선순위】
1순위: 조선일보, 중앙일보, 동아일보, 연합뉴스, YTN, MBC, KBS, SBS
2순위: 한겨레, 경향신문, 한국경제, 매일경제, 서울경제, 헤럴드경제
3순위: 기타 언론사 (매일노동뉴스, 뉴스1, 파이낸셜뉴스, 지역·전문지)
※ 동일 주제라면 상위 언론사 기사 우선

【작성 기준】
- 텔레그램용이므로 핵심만 간결하게 불릿 3개
- 실무 시사점은 1~2문장으로 짧고 임팩트 있게
- rank 순서는 반드시 위 순서대로 1~7

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
      "insight": "실무 시사점 1~2문장"
    }}
  ],
  "hashtags": ["오늘기사내용에서추출한태그1", "태그2", "태그3", "태그4", "태그5", "태그6", "태그7", "태그8", "태그9", "태그10"],
  "blog_title": "노란봉투법·건설노조·최저임금"
}}

【해시태그 작성 규칙】
- 반드시 오늘 선별된 7개 기사 내용에서만 추출 (임의 생성 금지)
- 10개 정확히 생성
- 기사 주제·인물·법령·사건명·업종 위주 (예: 건설노조파업, 최저임금, 중대재해처벌법)
- 브랜딩·홍보성 태그 절대 금지
- 띄어쓰기 없이 붙여쓰기, # 기호 제외

【blog_title 작성 규칙】
- 오늘 상위 3개 뉴스(rank 1~3)의 핵심 이슈를 '키워드 나열식'으로
- 형식: "키워드1·키워드2·키워드3" (가운뎃점 · 으로 연결, 정확히 3개)
- 각 키워드는 2~6자의 구체적 표현
- 날짜·"카드뉴스" 문구는 넣지 말 것 (코드에서 자동으로 붙임)
- 가운뎃점(·) 외 다른 기호·따옴표 금지

risk_level: high(🔴), med(⚠), info(ℹ)
총 7건, rank 1~7 순서 고정"""

print("Claude API 호출 중...")
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=5500,
    messages=[{"role": "user", "content": PROMPT}]
)
raw = response.content[0].text.strip()
raw = re.sub(r"```json|```", "", raw).strip()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    data = json.loads(match.group()) if match else {"news":[]}

news_list = data.get("news", [])
hashtags  = data.get("hashtags", [])
if not isinstance(hashtags, list):
    hashtags = []
hashtags = [str(t).lstrip("#").strip() for t in hashtags if t][:10]
HASHTAG_STR = " ".join(f"#{t}" for t in hashtags)
print(f"해시태그 {len(hashtags)}개: {HASHTAG_STR}")
BLOG_TITLE_Q = str(data.get("blog_title", "")).strip()

# ── 필드 정규화: Claude가 일부 필드를 누락해도 죽지 않도록 기본값 채움 ──
_RISK_LABEL_DEFAULT = {"high": "🔴 핵심 이슈", "med": "⚠ 주의", "info": "ℹ 참고"}
_clean_list = []
for i, n in enumerate(news_list):
    if not isinstance(n, dict):
        continue
    rl = n.get("risk_level") or "info"
    if rl not in ("high", "med", "info"):
        rl = "info"
    n["risk_level"] = rl
    n["risk_label"] = n.get("risk_label") or _RISK_LABEL_DEFAULT[rl]
    n["rank"]       = n.get("rank", i + 1)
    n["source"]     = n.get("source", "")
    n["date"]       = n.get("date", DATE_LABEL)
    n["title"]      = n.get("title", "")
    n["category"]   = n.get("category", "")
    n["insight"]    = n.get("insight", "")
    n["url"]        = n.get("url", VERCEL_URL)
    bullets = n.get("bullets", [])
    n["bullets"]    = bullets if isinstance(bullets, list) else [str(bullets)]
    _clean_list.append(n)
news_list = _clean_list

print(f"카드뉴스 {len(news_list)}건 생성 완료")

# ── HTML 생성 ────────────────────────────────────────
RISK_CLS = {"high":"risk-high","med":"risk-med","info":"risk-info"}
TAG_CLS  = {"high":"tag-high","med":"tag-med","info":"tag-info"}

# 텔레그램 공유 URL (제목 포함)
SHARE_TITLE = urllib.parse.quote(f"[JP Labor Letter] {DATE_LABEL} 노동·HR 핵심 브리핑 — 공인노무사 JP")
TG_SHARE_URL = f"https://t.me/share/url?url={urllib.parse.quote(VERCEL_URL)}&text={SHARE_TITLE}"

# 카카오 오픈채팅방 URL (상담 연결 fallback)
KAKAO_CHAT_URL = "https://open.kakao.com/o/gOaNVSwi"

# SDK는 키가 있을 때만 로드, 초기화도 키가 있을 때만
KAKAO_SDK_TAG = (
    '<script src="https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js"'
    ' integrity="sha384-TiCUE00h649CAMonG018J2ujOgDKW/kVWlChEuu4jK2vxfAAD0eZxzCKakxg55G4"'
    ' crossorigin="anonymous"></script>'
) if KAKAO_JS_KEY else ""

KAKAO_INIT_JS = (
    f'  if (typeof Kakao !== "undefined" && !Kakao.isInitialized()) {{'
    f' Kakao.init("{KAKAO_JS_KEY}"); }}'
) if KAKAO_JS_KEY else ""

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
/* ── 공유 바 ── */
.share-bar{
  background:#111827;border-top:1px solid var(--navy-border);
  padding:12px 16px 10px;
  position:sticky;bottom:0;z-index:90;
}
.share-row{display:flex;gap:10px;}
.share-btn{
  flex:1;display:flex;align-items:center;justify-content:center;gap:6px;
  padding:13px 0;font-size:15px;font-weight:700;
  border:none;border-radius:6px;cursor:pointer;
  text-decoration:none;transition:opacity .2s;
}
.share-btn:hover{opacity:.82}
.share-copy{background:var(--navy-border);color:var(--cream)}
.share-kakao{background:#FEE500;color:#3A1D1D}
#copy-msg{font-size:12px;color:var(--gold);display:none;text-align:center;padding-top:6px;}
/* ── 푸터 ── */
.footer{border-top:1px solid var(--navy-border);background:#111827;padding:24px 20px;text-align:center;margin-top:0}
.footer-logo{font-size:14px;font-weight:700;color:var(--gold);margin-bottom:6px}
.footer-disc{font-size:11px;color:var(--text-muted);line-height:1.8}
/* ── 섹션 구분 헤더 (2+4+1) ── */
.section-break{margin:24px 16px 0;padding:10px 16px;display:flex;align-items:center;gap:12px;border-radius:4px}
.section-break-law{background:rgba(201,168,76,.08);border:1px solid rgba(201,168,76,.25);border-left:4px solid var(--gold)}
.section-break-industry{background:rgba(93,173,226,.07);border:1px solid rgba(93,173,226,.2);border-left:4px solid #5dade2}
.section-break-policy{background:rgba(46,204,113,.07);border:1px solid rgba(46,204,113,.2);border-left:4px solid #2ecc71}
.sb-icon{font-size:18px}
.sb-body{flex:1}
.sb-title{font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
.sb-law .sb-title{color:var(--gold)}
.sb-industry .sb-title{color:#5dade2}
.sb-policy .sb-title{color:#2ecc71}
.sb-desc{font-size:11px;color:var(--text-muted);margin-top:2px}
.sb-count{font-size:11px;font-weight:700;padding:3px 8px;border-radius:10px;align-self:center}
.sb-law .sb-count{background:rgba(201,168,76,.15);color:var(--gold)}
.sb-industry .sb-count{background:rgba(93,173,226,.12);color:#5dade2}
.sb-policy .sb-count{background:rgba(46,204,113,.12);color:#2ecc71}"""

headlines_html = ""
for n in news_list:
    tc = TAG_CLS.get(n["risk_level"],"tag-info")
    headlines_html += f"""<a class="headline-item" href="#news{n['rank']}">
  <div class="headline-num">{n['rank']}</div>
  <div class="headline-content">
    <div class="headline-source">📰 {n['source']} · {n['date']}</div>
    <div class="headline-title">{n['title']}</div>
    <span class="headline-tag {tc}">{n['risk_label']}</span>
  </div>
</a>"""

_SECTION_BREAKS = {
    1: ("section-break-law",      "sb-law",      "⚖️", "노동법 핵심",    "노사관계·임금·산재·해고 중 오늘 가장 중요한 2건", "2건"),
    3: ("section-break-industry", "sb-industry", "🏭", "업종별 이슈",    "건설·제조물류·IT금융·유통의료 4개 업종", "4건"),
    7: ("section-break-policy",   "sb-policy",   "📋", "정책·HR·트렌드", "고용노동부 정책·HR 실무·사회 트렌드", "1건"),
}

cards_html = ""
for n in news_list:
    rank = n["rank"]
    # 섹션 구분 헤더 삽입
    if rank in _SECTION_BREAKS:
        sb_cls, sb_inner, sb_icon, sb_title, sb_desc, sb_count = _SECTION_BREAKS[rank]
        cards_html += f"""<div class="section-break {sb_cls} {sb_inner}">
  <span class="sb-icon">{sb_icon}</span>
  <div class="sb-body">
    <div class="sb-title">{sb_title}</div>
    <div class="sb-desc">{sb_desc}</div>
  </div>
  <span class="sb-count">{sb_count}</span>
</div>"""
    bullets = "".join(f"<li>{b}</li>" for b in n["bullets"])
    rc = RISK_CLS.get(n["risk_level"],"risk-info")
    cards_html += f"""<div class="news-card" id="news{rank}">
  <div class="source-bar"><span class="source-name">📰 {n['source']}</span><span class="source-date">{n['date']}</span></div>
  <div class="card-inner">
    <div class="risk-tag {rc}">{n['risk_label']}</div>
    <div class="card-category">{n['category']}</div>
    <h2 class="card-title">{n['title']}</h2>
    <ul class="bullet-list">{bullets}</ul>
    <div class="insight"><div class="insight-label">실무 시사점</div><div class="insight-text">{n['insight']}</div></div>
  </div>
  <div class="read-more"><span class="wm-small">© JP Labor News</span><a href="{n['url']}" target="_blank">자세히 보기</a></div>
</div>"""

# 카카오톡 공유 버튼 (JS 키가 있을 때만 표시)
KAKAO_BTN_HTML = f'<button class="share-btn share-kakao" onclick="shareKakao()">💬 카카오톡</button>' if KAKAO_JS_KEY else ""

NEWS_HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Today's Labor News — {DATE_LABEL} | 공인노무사 JP</title>
<meta name="description" content="오늘의 인사노무 핵심 브리핑. 노동법·노사·HR 이슈 7건.">
<meta property="og:title" content="Today's Labor News — {DATE_LABEL} | 공인노무사 JP">
<meta property="og:description" content="노동법·노사·임금·산재·건설·IT·HR 등 오늘의 핵심 이슈 7건">
<meta property="og:type" content="article">
<meta property="og:url" content="{VERCEL_URL}">
<meta property="og:image" content="{OG_IMAGE}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="JP Labor News">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{OG_IMAGE}">
{KAKAO_SDK_TAG}
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

<!-- ── 공유 바: 마지막 카드 아래, 푸터 위 ── -->
<div class="share-bar">
  <div class="share-row">
    <button class="share-btn share-copy" onclick="copyLink()">🔗 링크 복사</button>
    <button class="share-btn share-kakao" onclick="shareKakao()">💬 카카오톡</button>
  </div>
  <div id="copy-msg">✅ 링크 복사됨!</div>
</div>

<footer class="footer">
  <div class="footer-logo">JP Labor News</div>
  <div class="footer-disc">Powered by Claude AI · 자동 생성<br>본 카드뉴스는 정보 제공 목적입니다.<br>© 2026 JP Labor News</div>
</footer>

<script>
{KAKAO_INIT_JS}
function copyLink() {{
  var url = '{VERCEL_URL}';
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(url).then(function() {{ showCopyMsg(); }}).catch(function() {{ fallbackCopy(url); }});
  }} else {{
    fallbackCopy(url);
  }}
}}
function fallbackCopy(url) {{
  var ta = document.createElement('textarea');
  ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.focus(); ta.select();
  try {{ document.execCommand('copy'); showCopyMsg(); }} catch(e) {{}}
  document.body.removeChild(ta);
}}
function showCopyMsg() {{
  var m = document.getElementById('copy-msg');
  m.style.display = 'inline';
  setTimeout(function() {{ m.style.display = 'none'; }}, 2500);
}}
function shareKakao() {{
  var shareUrl  = '{VERCEL_URL}';
  var shareText = '[JP Labor Letter] 오늘의 인사노무 핵심 브리핑 · {DATE_LABEL}';

  // ① 모바일 네이티브 공유시트 (Android/iOS) — KakaoTalk 포함, 가장 안정적
  //    공유된 링크는 OG 태그가 있어 카카오톡에서 미리보기 카드로 표시됨
  if (navigator.share) {{
    navigator.share({{ title: '[JP Labor Letter]', text: shareText, url: shareUrl }})
      .catch(function(e) {{ console.log('native share cancelled:', e); }});
    return;
  }}

  // ② Kakao SDK 카드형 공유 (PC + 카카오 개발자센터에 도메인 등록 시)
  if (typeof Kakao !== 'undefined' && Kakao.isInitialized()) {{
    try {{
      Kakao.Share.sendDefault({{
        objectType: 'feed',
        content: {{
          title: '[JP Labor Letter] — 공인노무사 JP',
          description: '오늘의 인사노무 핵심 브리핑 · {DATE_LABEL}',
          imageUrl: '{OG_IMAGE}',
          link: {{ mobileWebUrl: shareUrl, webUrl: shareUrl }},
        }},
        buttons: [{{ title: '카드뉴스 보기', link: {{ mobileWebUrl: shareUrl, webUrl: shareUrl }} }}],
      }});
      return;
    }} catch(e) {{
      console.warn('Kakao.Share 실패:', e);
    }}
  }}

  // ③ 최후 fallback: 링크 복사 (어디서든 동작 보장)
  copyLink();
  alert('공유 링크가 복사되었습니다. 카카오톡에 붙여넣어 보내주세요.');
}}
</script>
</body>
</html>"""

# send 페이지 (수동 발송용)
tg_lines = [f"📋 오늘의 인사노무 브리핑 — {DATE_LABEL} ({WEEKDAY})\n"]
for n in news_list:
    emoji = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣"][n["rank"]-1] if 1 <= n["rank"] <= 7 else "•"
    tg_lines.append(f"{emoji} {n['title']}")
tg_lines.append(f"\n🔗 전체 카드뉴스:\n{VERCEL_URL}")
tg_text = "\n".join(tg_lines)

tg_photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
tg_api_url = f"{tg_photo_url}?chat_id={urllib.parse.quote(str(TELEGRAM_CHAT_ID))}&photo={urllib.parse.quote(OG_IMAGE)}&caption={urllib.parse.quote(tg_text[:1024])}"

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


def generate_png(html_rel_path: str, png_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠ playwright 미설치 — PNG 생성 건너뜀")
        return False
    with socket.socket() as _s:
        _s.bind(("", 0))
        port = _s.getsockname()[1]

    class _SilentHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass

    handler_factory = lambda *a, **kw: _SilentHandler(*a, directory=REPO_ROOT, **kw)
    try:
        with socketserver.TCPServer(("127.0.0.1", port), handler_factory) as httpd:
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    page = browser.new_page(viewport={"width": 600, "height": 900}, device_scale_factor=2)
                    page.goto(f"http://127.0.0.1:{port}/{html_rel_path}", wait_until="networkidle", timeout=30_000)
                    page.wait_for_timeout(2_000)
                    page.screenshot(path=png_path, full_page=True)
                    browser.close()
            finally:
                httpd.shutdown()
        print(f"✅ PNG 저장: {png_path}")
        return True
    except Exception as e:
        print(f"⚠ PNG 생성 실패: {e}")
        return False


# ── 데일리 요약 썸네일 생성 (1200×630) ─────────────────────────────────
THUMBNAIL_FILE = f"thumbnail_{DATE_STR}.png"

def generate_daily_thumbnail(items, date_label, png_path):
    # 2+4+1 구조로 섹션별 대표 제목 추출
    law_items      = [n for n in items if n.get("rank") in (1, 2)][:2]
    industry_items = [n for n in items if n.get("rank") in (3, 4, 5, 6)][:4]
    policy_item    = [n for n in items if n.get("rank") == 7][:1]

    def _row(icon, title, color):
        return (f'<div class="row">'
                f'<span class="ri" style="color:{color}">{icon}</span>'
                f'<span class="rt">{title}</span>'
                f'</div>')

    rows_html = ""
    for n in law_items:
        rows_html += _row("⚖", n["title"], "#c9a84c")
    for n in industry_items:
        rows_html += _row("🏭", n["title"], "#5dade2")
    for n in policy_item:
        rows_html += _row("📋", n["title"], "#2ecc71")

    counts_html = (
        f'<span class="badge badge-law">⚖ 노동법 2</span>'
        f'<span class="badge badge-ind">🏭 업종 4</span>'
        f'<span class="badge badge-pol">📋 정책 1</span>'
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@900&display=swap">
<style>
*{{margin:0;padding:0;box-sizing:border-box;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
body{{width:1200px;height:630px;overflow:hidden;
  background:#0d1b2a;
  font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;
  display:flex}}
.left{{width:400px;height:630px;
  background:linear-gradient(150deg,#0d1b2a 0%,#0f2540 100%);
  padding:48px 38px;display:flex;flex-direction:column;justify-content:space-between;
  border-right:1px solid #1e3a55}}
.label{{font-size:13px;color:#c9a84c;letter-spacing:.2em;font-weight:700;text-transform:uppercase;margin-bottom:18px}}
.main{{font-family:'Playfair Display',serif;font-size:54px;font-weight:900;color:#f0ebe0;line-height:1.05;margin-bottom:14px}}
.main span{{color:#c9a84c}}
.sub{{font-size:17px;color:#9fb0c4;line-height:1.5;margin-bottom:24px}}
.badges{{display:flex;flex-direction:column;gap:8px;margin-bottom:20px}}
.badge{{font-size:13px;font-weight:700;padding:5px 12px;border-radius:4px;display:inline-block;width:fit-content}}
.badge-law{{background:rgba(201,168,76,.15);color:#c9a84c;border:1px solid rgba(201,168,76,.3)}}
.badge-ind{{background:rgba(93,173,226,.12);color:#5dade2;border:1px solid rgba(93,173,226,.25)}}
.badge-pol{{background:rgba(46,204,113,.10);color:#2ecc71;border:1px solid rgba(46,204,113,.2)}}
.date{{font-size:28px;color:#c9a84c;font-weight:800;margin-bottom:4px}}
.brand{{font-size:15px;color:#5a7290}}
.right{{flex:1;height:630px;background:#0e1e2e;
  padding:40px 40px;display:flex;flex-direction:column;justify-content:center}}
.hl-label{{font-size:13px;color:#c9a84c;letter-spacing:.16em;text-transform:uppercase;
  font-weight:700;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #1a3248}}
.row{{display:flex;gap:12px;align-items:flex-start;
  padding:10px 0;border-bottom:1px solid #162a3c}}
.row:last-child{{border-bottom:none}}
.ri{{font-size:18px;min-width:24px;line-height:1.5;flex-shrink:0}}
.rt{{font-size:20px;color:#dde7f3;line-height:1.45;font-weight:600;word-break:keep-all}}
.footer{{margin-top:18px;padding-top:12px;border-top:1px solid #1a3248;
  font-size:13px;color:#3d5570}}
</style></head><body>
<div class="left">
  <div>
    <div class="label">Labor · HR · Daily Brief</div>
    <div class="main">Today's<br><span>Labor</span><br>News</div>
    <div class="sub">오늘의 인사노무 핵심 브리핑</div>
    <div class="badges">{counts_html}</div>
  </div>
  <div>
    <div class="date">{date_label}</div>
    <div class="brand">JP Labor News</div>
  </div>
</div>
<div class="right">
  <div class="hl-label">Today's 7 Headlines — 2+4+1</div>
  {rows_html}
  <div class="footer">eu-labornews.vercel.app</div>
</div>
</body></html>"""

    tmp = os.path.join(REPO_ROOT, FOLDER, f"_thumb_tmp_{DATE_STR}.html")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1200, "height": 630},
                device_scale_factor=3
            )
            page.goto(f"file://{os.path.abspath(tmp)}", wait_until="networkidle")
            try:
                page.evaluate(
                    "async () => { if (document.fonts && document.fonts.ready) "
                    "{ await document.fonts.ready; } }"
                )
            except Exception:
                pass
            page.wait_for_timeout(1200)
            page.screenshot(
                path=png_path,
                clip={"x": 0, "y": 0, "width": 1200, "height": 630}
            )
            browser.close()
        os.remove(tmp)
        print(f"✅ 데일리 썸네일 저장: {png_path}")
        return True
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"⚠ 데일리 썸네일 생성 실패: {e}")
        return False


print("데일리 썸네일 생성 중...")
generate_daily_thumbnail(news_list, DATE_LABEL, f"{FOLDER}/{THUMBNAIL_FILE}")

# ── 네이버 블로그 복붙용 본문 자동 생성 (가시성·매력도 최적화) ──────────────
# 1) 제목: Claude가 만든 키워드 나열 + " ｜ M/D 인사노무 카드뉴스"
_kw_pool = []
for n in news_list[:3]:
    k = str(n.get("category") or n.get("keyword") or "").strip()
    if k and k not in _kw_pool:
        _kw_pool.append(k)
if BLOG_TITLE_Q:
    _title_kw = BLOG_TITLE_Q
else:
    _title_kw = "·".join(_kw_pool[:3]) if _kw_pool else "노동·HR 이슈"
BLOG_TITLE = f"{_title_kw} ｜ {DATE_SHORT} 인사노무 카드뉴스"

# 2) 후킹 첫 줄
_hook_kw = " · ".join(_kw_pool[:3]) if _kw_pool else "오늘의 노동·HR 핵심"
BLOG_HOOK = f"오늘 노동 뉴스 핵심만 3분 정리 📌 {_hook_kw}"

# 3) 본문: 뉴스 5건 제목 + 한 줄 요약(실무 시사점)
_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
_body_lines = [BLOG_HOOK, ""]
for n in news_list:
    rank = n["rank"]
    emoji = _emojis[rank - 1] if 1 <= rank <= 7 else "•"
    _summary = (n.get("insight") or "").strip()
    if len(_summary) > 70:
        _summary = _summary[:68].rstrip() + "…"
    _body_lines.append(f"{emoji} {n['title']}")
    if _summary:
        _body_lines.append(f"   → {_summary}")
    _body_lines.append("")
_body_lines += ["▶ 카드뉴스 전체 보기", VERCEL_URL, "", HASHTAG_STR]
BLOG_BODY = "\n".join(_body_lines)

# ── 텔레그램 발송 ───────────────────────────────────────────────────────
_tg_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def tg_post(method, **kwargs):
    try:
        r = requests.post(f"{_tg_base}/{method}", timeout=30, **kwargs)
        ok = r.json().get("ok")
        return ok, r.text
    except Exception as e:
        return False, str(e)

# 1) 기존 유지 — 다크 네이비+별하늘 OG 이미지 + 링크 + 해시태그
ok, msg = tg_post(
    "sendPhoto",
    data={"chat_id": TELEGRAM_CHAT_ID, "photo": OG_IMAGE,
          "caption": f"{VERCEL_URL}\n\n{HASHTAG_STR}"},
)
print("✅ 텔레그램 OG 이미지 발송!" if ok else f"❌ OG 이미지 발송 실패: {msg}")

# 2) 데일리 요약 썸네일 (1200×630) — 블로그 대표이미지용
_thumb_path = f"{FOLDER}/{THUMBNAIL_FILE}"
if os.path.exists(_thumb_path):
    with open(_thumb_path, "rb") as _f:
        ok, msg = tg_post(
            "sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"🖼 {DATE_LABEL} 오늘의 헤드라인 (블로그 대표이미지)"},
            files={"photo": (THUMBNAIL_FILE, _f, "image/png")},
        )
    print("✅ 텔레그램 데일리 썸네일 발송!" if ok else f"❌ 데일리 썸네일 발송 실패: {msg}")
else:
    print("⚠ 데일리 썸네일 파일 없음 — 건너뜀")

# 3) 신규 — 네이버 블로그 복붙용 본문 (제목 + 후킹 + 5줄 + 링크 + 해시태그)
_blog_msg = f"📝 네이버 블로그 복붙용\n\n[제목]\n{BLOG_TITLE}\n\n[본문]\n{BLOG_BODY}"
ok, msg = tg_post("sendMessage",
    data={"chat_id": TELEGRAM_CHAT_ID, "text": _blog_msg[:4096],
          "disable_web_page_preview": True})
print("✅ 텔레그램 블로그 본문 발송!" if ok else f"❌ 블로그 본문 발송 실패: {msg}")

print(f"✅ 완료: {FOLDER}/{NEWS_FILE}")
