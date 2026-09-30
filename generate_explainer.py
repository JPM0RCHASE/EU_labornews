"""
네이버 블로그용 실무 해설글 생성기.

카드뉴스가 남긴 뉴스 JSON을 글감으로 써서, 네이버 검색 유입을 노리는
실무 롱테일 해설글을 만든다. 문체 규칙은 SKILL.md 한 곳에서만 관리한다.

모드 두 가지 (환경변수 TOPIC 유무로 갈림):
  TOPIC 없음  → 후보 주제 3개를 뽑아 텔레그램으로 발송
  TOPIC 있음  → 그 주제로 해설글 전문을 써서 텔레그램으로 발송
                (숫자 1~3이면 직전 후보 목록에서 선택, 그 외 문자열이면 자유 주제)
"""

import os
import re
import json
import glob
import requests
from datetime import datetime, timezone, timedelta
import anthropic

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
TOPIC              = os.environ.get("TOPIC", "").strip()

KST        = timezone(timedelta(hours=9))
TODAY      = datetime.now(KST)
DATE_STR   = TODAY.strftime("%Y%m%d")
DATE_LABEL = TODAY.strftime("%Y. %m. %d.")

REPO_ROOT       = os.path.dirname(os.path.abspath(__file__))
SKILL_FILE      = os.path.join(REPO_ROOT, ".claude/skills/labor-blog-writing/SKILL.md")
OUT_DIR         = os.path.join(REPO_ROOT, "explainer")
CANDIDATES_FILE = os.path.join(OUT_DIR, "candidates.json")

MODEL      = "claude-sonnet-4-5"
NEWS_DAYS  = 14

os.makedirs(OUT_DIR, exist_ok=True)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def load_style_guide() -> str:
    with open(SKILL_FILE, encoding="utf-8") as f:
        body = f.read()
    # YAML 프런트매터는 스킬 메타데이터라 프롬프트에 넣지 않는다.
    return re.sub(r"^---.*?---\s*", "", body, count=1, flags=re.S).strip()


def load_recent_news(days: int = NEWS_DAYS) -> list:
    """최근 날짜 폴더의 news_*.json 을 모아 글감 후보로 돌려준다."""
    items = []
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "2*/news_*.json")), reverse=True)[:days]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠ {os.path.basename(path)} 읽기 실패(건너뜀): {e}")
            continue
        for n in data.get("news", []):
            items.append({
                "date": data.get("date", ""),
                "title": n.get("title", ""),
                "insight": n.get("insight", ""),
            })
    if items:
        return items

    # news_*.json 은 카드뉴스를 돌려야 쌓인다. 그 전까지는 이미 만들어 둔
    # 카드뉴스 HTML에서 헤드라인만 뽑아 글감으로 쓴다.
    print("news_*.json 없음 — 카드뉴스 HTML에서 헤드라인을 뽑습니다.")
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "2*/labornews_*.html")), reverse=True)[:days]:
        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except Exception as e:
            print(f"⚠ {os.path.basename(path)} 읽기 실패(건너뜀): {e}")
            continue
        date = os.path.basename(os.path.dirname(path))
        for title in re.findall(r'class="card-title"[^>]*>([^<]+)<', html):
            title = title.strip()
            if title:
                items.append({"date": date, "title": title, "insight": ""})
    return items


def parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    try:
        from json_repair import repair_json
        repaired = repair_json(match.group() if match else text, return_objects=True)
        if isinstance(repaired, dict):
            print("✅ json-repair로 복구 성공")
            return repaired
    except Exception as e:
        print(f"⚠ json-repair 실패: {e}\n원시 응답(400자):\n{text[:400]}")
    return {}


def ask_claude(prompt: str, system: str, max_tokens: int) -> str:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def tg_send(text: str) -> None:
    """텔레그램은 한 메시지 4096자 제한이라 문단 경계로 잘라 보낸다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks, rest = [], text
    while len(rest) > 4000:
        cut = rest.rfind("\n\n", 0, 4000)
        if cut <= 0:
            cut = 4000
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip()
    chunks.append(rest)

    for i, chunk in enumerate(chunks, 1):
        label = f"({i}/{len(chunks)})\n\n" if len(chunks) > 1 else ""
        try:
            r = requests.post(url, timeout=30, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": label + chunk,
                "disable_web_page_preview": True,
            })
            ok = r.json().get("ok")
        except Exception as e:
            ok = False
            r = e
        print(f"{'✅' if ok else '❌'} 텔레그램 {i}/{len(chunks)}" + ("" if ok else f" — {r}"))


def tg_photo(path: str, caption: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(path, "rb") as f:
            r = requests.post(url, timeout=60,
                              data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                              files={"photo": (os.path.basename(path), f, "image/png")})
        ok = r.json().get("ok")
    except Exception as e:
        ok, r = False, e
    print(f"{'✅' if ok else '❌'} 썸네일 발송" + ("" if ok else f" — {r}"))


def make_thumbnail(title: str, keyword: str, png_path: str) -> bool:
    """네이버 블로그 대표이미지(1200x630). 해설글은 한 편짜리라 제목이 주인공이다."""
    size = 68 if len(title) <= 20 else 58 if len(title) <= 30 else 50 if len(title) <= 40 else 42
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
*{{margin:0;padding:0;box-sizing:border-box;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
body{{width:1200px;height:630px;overflow:hidden;
  background:linear-gradient(145deg,#0d1b2a 0%,#12294a 100%);
  font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;
  padding:74px 86px;display:flex;flex-direction:column}}
.bar{{width:64px;height:5px;background:#c9a84c;margin-bottom:30px}}
.label{{font-size:19px;color:#c9a84c;letter-spacing:.22em;font-weight:700}}
.title{{flex:1;display:flex;align-items:center;
  font-size:{size}px;font-weight:800;color:#f0ebe0;line-height:1.3;
  word-break:keep-all;letter-spacing:-.02em}}
.foot{{display:flex;align-items:center;justify-content:space-between;
  border-top:1px solid #23415f;padding-top:24px}}
.brand{{font-size:25px;font-weight:700;color:#c9a84c}}
.kw{{font-size:19px;color:#7d94ad}}
</style></head><body>
<div>
  <div class="bar"></div>
  <div class="label">인사노무 실무 해설</div>
</div>
<div class="title">{title}</div>
<div class="foot">
  <div class="brand">공인노무사 JP</div>
  <div class="kw">{keyword}</div>
</div>
</body></html>"""

    tmp = os.path.join(OUT_DIR, "_thumb_tmp.html")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=3)
            page.goto(f"file://{os.path.abspath(tmp)}", wait_until="networkidle")
            try:
                page.evaluate("async () => { if (document.fonts) await document.fonts.ready; }")
            except Exception:
                pass
            page.wait_for_timeout(1200)
            page.screenshot(path=png_path, clip={"x": 0, "y": 0, "width": 1200, "height": 630})
            browser.close()
        print(f"✅ 썸네일 저장: {png_path}")
        return True
    except Exception as e:
        print(f"⚠ 썸네일 생성 실패(본문은 계속 발송): {e}")
        return False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fail(msg: str) -> None:
    """워크플로가 초록불인데 텔레그램만 조용한 상황을 막는다."""
    print(f"⚠ {msg}")
    tg_send(f"⚠️ 해설글 생성 실패\n\n{msg}")
    raise SystemExit(1)


# ── 후보 모드 ────────────────────────────────────────────────────────
def run_candidates(style: str) -> None:
    news = load_recent_news()
    if not news:
        fail("글감이 될 카드뉴스 기록이 없습니다. 카드뉴스 워크플로를 한 번 먼저 실행해 주세요.")
    print(f"글감 {len(news)}건으로 후보 선정 중...")

    news_text = "\n".join(f"- [{n['date']}] {n['title']} / {n['insight']}" for n in news)
    prompt = f"""아래는 최근 수집한 노동·인사노무 뉴스 목록입니다.

{news_text}

이 중에서 **네이버 검색 유입을 노리는 실무 해설글 주제** 3개를 뽑아주세요.

주제 선정 기준 (중요도 순):
1. 인사담당자나 근로자가 **실제로 검색창에 칠 법한 질문**이어야 한다.
   좋은 예: "5인미만 사업장 연차", "권고사직 실업급여", "부당해고 구제신청 기간"
2. **언론사가 다루지 않는 실무 각도**여야 한다. 시사 이슈 자체(노란봉투법 통과, OO기업 파업)는
   언론사가 검색 상위를 독점하므로 그대로 쓰면 안 된다. 뉴스는 힌트로만 쓰고,
   그 뉴스가 촉발하는 **실무 질문**으로 바꿔라.
3. **통념이 틀린 지점**이 있어야 한다. "당연히 된다/안 된다"고 믿는데 실제로는 다른 지점.
4. 한 번 쓰면 몇 달간 검색 유입이 유지되는 **상시 주제**여야 한다. 그날만 유효한 속보는 제외.

아래 JSON만 출력하세요. 다른 말은 쓰지 마세요.

{{
  "candidates": [
    {{
      "topic": "해설글이 답할 실무 질문 한 문장",
      "title": "통념 반박형 제목안 (25자 내외)",
      "keyword": "노리는 검색 키워드",
      "reader": "사용자" 또는 "근로자",
      "why": "이 주제를 고른 이유 한 문장"
    }}
  ]
}}"""

    data = parse_json(ask_claude(prompt, style, 2000))
    candidates = data.get("candidates", [])
    if not candidates:
        fail("Claude가 후보를 뽑지 못했습니다. 다시 실행해 주세요.")

    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": DATE_STR, "candidates": candidates}, f, ensure_ascii=False, indent=2)
    print(f"✅ 후보 {len(candidates)}건 저장: {CANDIDATES_FILE}")

    lines = [f"📌 [{DATE_LABEL}] 해설글 주제 후보", ""]
    for i, c in enumerate(candidates, 1):
        lines += [
            f"{i}. {c.get('title','')}",
            f"   주제: {c.get('topic','')}",
            f"   키워드: {c.get('keyword','')} / 시점: {c.get('reader','')}",
            f"   이유: {c.get('why','')}",
            "",
        ]
    lines.append("👉 Actions에서 Explainer 워크플로를 다시 실행하고 topic 칸에 번호(1~3)를 넣으면 글을 씁니다.")
    tg_send("\n".join(lines))


# ── 집필 모드 ────────────────────────────────────────────────────────
def resolve_topic(raw: str) -> dict:
    """숫자면 직전 후보에서 고르고, 아니면 자유 주제로 취급한다."""
    if not raw.isdigit():
        return {"topic": raw, "title": "", "keyword": raw, "reader": ""}
    try:
        with open(CANDIDATES_FILE, encoding="utf-8") as f:
            candidates = json.load(f).get("candidates", [])
    except FileNotFoundError:
        fail("후보 파일이 없습니다. topic을 비우고 먼저 실행해 후보를 받으세요.")
    idx = int(raw) - 1
    if not 0 <= idx < len(candidates):
        fail(f"후보 번호는 1~{len(candidates)} 사이여야 합니다.")
    return candidates[idx]


def run_write(style: str) -> None:
    picked = resolve_topic(TOPIC)
    print(f"집필 주제: {picked.get('topic','')}")

    prompt = f"""아래 주제로 네이버 블로그에 올릴 실무 해설글을 쓰세요.

주제: {picked.get('topic','')}
제목안: {picked.get('title','') or '(직접 정하세요)'}
노리는 검색 키워드: {picked.get('keyword','')}
독자 시점: {picked.get('reader','') or '(주제에 맞게 정하세요)'}

시스템 프롬프트로 준 문체 규칙을 **그대로** 지키세요. 특히:
- 본문 1,500자 이상
- 외부 링크 금지, 이모지 금지
- 소제목은 번호 + 결론형 서술문
- 조문 번호가 확실하지 않으면 인용하지 말 것 (틀린 조문은 치명적)
- 용어 교정이나 실무자가 놓치기 쉬운 예외를 최소 1개

아래 JSON만 출력하세요. 다른 말은 쓰지 마세요.
body 는 줄바꿈을 \\n 으로 넣은 순수 텍스트입니다. 마크다운 기호를 쓰지 마세요.

{{
  "title": "최종 제목",
  "body": "본문 전문",
  "hashtags": ["해시태그", "10개내외"],
  "check": "발행 전 사람이 반드시 확인해야 할 사항 (인용한 조문·판례 등)"
}}"""

    data = parse_json(ask_claude(prompt, style, 8000))
    title, body = data.get("title", ""), data.get("body", "")
    if not body:
        fail("본문 생성에 실패했습니다. 다시 실행해 주세요.")

    tags = " ".join(f"#{t.lstrip('#')}" for t in data.get("hashtags", []))
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "_", title)[:40] or "explainer"
    path = os.path.join(OUT_DIR, f"{DATE_STR}_{slug}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"[제목]\n{title}\n\n[본문]\n{body}\n\n[해시태그]\n{tags}\n")
    print(f"✅ 저장: {path} (본문 {len(body)}자)")

    png = os.path.join(OUT_DIR, f"{DATE_STR}_{slug}.png")
    if make_thumbnail(title, picked.get("keyword", ""), png):
        tg_photo(png, "🖼 블로그 대표이미지로 삽입하세요")

    tg_send(f"📝 네이버 블로그 복붙용 ({len(body)}자)\n\n[제목]\n{title}\n\n[본문]\n{body}\n\n{tags}")
    if data.get("check"):
        tg_send(f"⚠️ 발행 전 확인\n\n{data['check']}\n\n인용된 조문·판례는 반드시 직접 검증하세요.")


if __name__ == "__main__":
    style_guide = load_style_guide()
    if TOPIC:
        run_write(style_guide)
    else:
        run_candidates(style_guide)
    print("🎉 완료")
