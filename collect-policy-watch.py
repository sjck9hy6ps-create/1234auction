"""📰 세제·대출·규제지역 새 소식 자동 수집(2026-11-21, 사용자: 세제 개편안·대출 규제를 금리 탭에 정기적으로 자동 갱신)
원칙: 사실만 - 제목·날짜·출처·링크를 그대로 모으고 내용을 요약·해석하지 않음. 금리 탭에는 '확인 전 새 소식'으로 따로 보여 주고, 내용을 읽어 확인한 것만 data/policy-events.json(출처·확인 상태 표기)에 올림.
출처: ① 금융위원회 보도자료 목록(공식, 제목에 대출·DSR·LTV·가계부채 등) ② 구글 뉴스 검색 RSS(언론 보도 제목, 세제·대출·규제지역 키워드). 결과는 signal|__policy_watch__에 누적(최대 80건)하고 collect-macro가 macro.watch로 합쳐 화면에 보냄."""
import os, re, json, html, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import requests
UA = {"User-Agent": "Mozilla/5.0"}
KEEP = 80
TYPES = [("세제", r"세제개편|양도소득세|양도세|종합부동산세|종부세|취득세|보유세|장기보유특별공제|장기거주|다주택자 중과"),
         ("대출규제", r"주택담보대출|주담대|가계부채|가계대출|DSR|LTV|스트레스 DSR|대출 규제|대출규제|만기연장|총량관리"),
         ("규제지역", r"조정대상지역|투기과열지구|토지거래허가|규제지역")]
ACT = r"발표|시행|확정|개편|강화|완화|신설|폐지|지정|해제|추진|입법예고|통과|의결|개정|방안|대책|유예|연장|논의|검토|예고|재검토|전망"   # 기사 제목에 정책 행위가 있어야 담음(잡음 줄이기)
QUERIES = ["세제개편안 양도세 종부세", "주택담보대출 DSR LTV 규제", "가계부채 관리방안", "조정대상지역 투기과열지구 토지거래허가구역 지정", "다주택자 양도세 중과 취득세 개편"]

def kind_of(title):
    for k, rx in TYPES:
        if re.search(rx, title): return k
    return None

def fsc():
    out = []
    try:
        h = requests.get("https://www.fsc.go.kr/no010101", headers=UA, timeout=40).text
        for m in re.finditer(r'<a[^>]+href="(/no010101/(\d+)[^"]*)"[^>]*>(.*?)</a>', h, re.S):
            t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(3)))).strip()
            if len(t) < 8 or not kind_of(t): continue
            seg = h[m.end(): m.end() + 800]; d = re.search(r"(20\d\d)[.\-](\d\d)[.\-](\d\d)", seg)
            out.append({"date": f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else None, "type": kind_of(t), "title": t, "source": "금융위원회 보도자료", "url": "https://www.fsc.go.kr/no010101/" + m.group(2), "kind": "official", "enforce": bool(re.search(r"시행", t) and not re.search(r"시행령|입법예고|시행 예정|시행될|시행 앞두|시행 전", t))})
    except Exception as e: print("금융위 목록 실패:", str(e)[:100])
    return out

def news():
    out = []
    for q in QUERIES:
        try:
            x = requests.get("https://news.google.com/rss/search?q=" + quote(q + " when:14d") + "&hl=ko&gl=KR&ceid=KR:ko", headers=UA, timeout=40).text
        except Exception as e: print("뉴스 실패:", q, str(e)[:80]); continue
        for it in re.findall(r"<item>(.*?)</item>", x, re.S):
            g = lambda t: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<%s[^>]*>(.*?)</%s>" % (t, t), it, re.S) or [None, ""])[1])).strip()
            t = g("title"); src = g("source"); t = re.sub(r"\s*-\s*" + re.escape(src) + r"$", "", t) if src else t
            k = kind_of(t)
            if not k or not re.search(ACT, t): continue
            try: d = datetime.strptime(g("pubDate")[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
            except Exception: d = None
            out.append({"enforce": bool(re.search(r"시행", t) and not re.search(r"시행령|입법예고|시행 예정|시행될|시행 앞두|시행 전", t)), "date": d, "type": k, "title": t, "source": (src or "언론") + " 보도", "url": g("link") if g("link").startswith("http") else "", "kind": "news"})
        time.sleep(1)
    return out

def norm(t): return re.sub(r"[\s\W_]+", "", t)[:40]

def run(prev):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d"); seen = {norm(e["title"]): e for e in (prev or [])}; added = 0; new_items = []
    for e in fsc() + news():
        k = norm(e["title"])
        if k in seen: continue
        e["firstSeen"] = today; seen[k] = e; added += 1; new_items.append(e)
    items = sorted(seen.values(), key=lambda e: (e.get("date") or e.get("firstSeen") or ""), reverse=True)[:KEEP]
    print(f"정책 새 소식 수집: 새로 {added}건 · 누적 {len(items)}건", flush=True)
    run.new_items = new_items
    return items

def notify_kakao(new_items, supa=None):
    """새 소식이 있으면 카카오톡 '나에게 보내기'로 한 통(200자 이내) - 시행 건은 맨 앞. 열쇠(KAKAO_REST_API_KEY·KAKAO_REFRESH_TOKEN)가 없으면 조용히 건너뜀.
    리프레시 토큰이 새로 발급되면 signal|__kakao_token__에 저장해 다음 실행이 이어 씀(카카오 토큰은 약 60일)."""
    key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not key or not new_items: return "skip"
    rt = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip(); su, sk = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    H = {"apikey": sk or "", "Authorization": "Bearer " + (sk or "")}
    try:
        if su and sk:
            r0 = requests.get(su + "/rest/v1/leader_follower_cache?id=eq.signal%7C%7C__kakao_token__&select=payload", headers=H, timeout=40)
            if r0.status_code < 300 and r0.json(): rt = (r0.json()[0].get("payload") or {}).get("refresh_token") or rt
        if not rt: return "no-token"
        data = {"grant_type": "refresh_token", "client_id": key, "refresh_token": rt}
        if os.environ.get("KAKAO_CLIENT_SECRET"): data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"].strip()
        tk = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=40).json()
        if "access_token" not in tk: print("카카오 토큰 갱신 실패:", str(tk)[:120]); return "token-fail"
        if tk.get("refresh_token") and su and sk:
            requests.post(su + "/rest/v1/leader_follower_cache?on_conflict=id", headers={**H, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}, data=json.dumps([{"id": "signal|__kakao_token__", "payload": {"refresh_token": tk["refresh_token"]}, "fetched_at": datetime.now(timezone.utc).isoformat()}]), timeout=40)
        items = sorted(new_items, key=lambda e: (not e.get("enforce"), e.get("date") or ""), reverse=False)
        head = ("[시행] " if any(e.get("enforce") for e in items) else "") + f"세제·대출·규제 새 소식 {len(items)}건"
        body = head + "\n" + "\n".join(("▶" if e.get("enforce") else "·") + e["title"][:52] for e in items[:3])
        text = body[:195]
        tmpl = {"object_type": "text", "text": text, "link": {"web_url": "https://1234auction.vercel.app", "mobile_web_url": "https://1234auction.vercel.app"}, "button_title": "앱 열기"}
        r = requests.post("https://kapi.kakao.com/v2/api/talk/memo/default/send", headers={"Authorization": "Bearer " + tk["access_token"]}, data={"template_object": json.dumps(tmpl, ensure_ascii=False)}, timeout=40)
        print("카카오 전송:", r.status_code, r.text[:80]); return "ok" if r.status_code < 300 else "send-fail"
    except Exception as e:
        print("카카오 전송 오류(무시):", str(e)[:100]); return "error"

if __name__ == "__main__":
    for e in run([])[:15]: print(e["date"], e["type"], e["source"], "|", e["title"][:70])
