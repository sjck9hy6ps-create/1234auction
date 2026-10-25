"""
🗺️ 주간 시장 요약 (2026-10-25, 사용자: 사이클 국면·지역별 시세 흐름·경매 낙찰 현황을 주간 파이프라인에 붙여 달라)
지역(시도)별 한 줄: ① 아파트 시세 3·6·12개월 변화와 사이클 국면·거래량 변화(analyze-cycle이 만든 값)
                   ② 최근 4주 낙찰 현황(낙찰 건수·낙찰가율 중앙값·입찰자 수 중앙/몰림 비율) vs 그 전 4주
경고(참고용, 계산 규칙은 자동으로 바꾸지 않음): 시세 3·6개월 모두 하락 / 사이클 하락기 / 거래량 급감 / 낙찰가율 급등(경쟁 과열)
결과: leader_follower_cache 'signal|__market_snapshot__' (최근 26주 이력) → 주간 리포트 🛠 파이프라인 탭
⚠️ 광주·전남은 데이터에서 '전남광주' 하나로 합쳐져 있어 이름을 맞춰 조회함. 낙찰사례 저장소에는 결과 없는 입찰 전 기록이 섞여 있어 '매각가 있고 입찰일이 오늘 이전'인 건만 씀.
"""
import os, json, importlib.util
from datetime import datetime, timezone, timedelta
import numpy as np
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_s); _s.loader.exec_module(cyc)
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
SIDOS = ["서울", "경기", "인천", "부산", "대구", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남광주", "경북", "경남", "제주"]
MAP = [("전남광주", "전남광주"), ("광주", "전남광주"), ("전라남", "전남광주"), ("전남", "전남광주"), ("서울", "서울"), ("경기", "경기"), ("인천", "인천"), ("부산", "부산"), ("대구", "대구"),
       ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("강원", "강원"), ("충청북", "충북"), ("충북", "충북"), ("충청남", "충남"), ("충남", "충남"), ("전북", "전북"), ("전라북", "전북"),
       ("경상북", "경북"), ("경북", "경북"), ("경상남", "경남"), ("경남", "경남"), ("제주", "제주")]


def sido_of(addr):
    t = str(addr or "").strip()
    for k, v in MAP:
        if t.startswith(k): return v
    return None


def cycle_part(sido):
    r = requests.get(f"{SITE}/api/data-coverage", params={"mode": "marketCycle", "region": f"{sido} 중구"}, timeout=60)
    if not r.ok: return None
    s = (r.json().get("sido") or {})
    ix = s.get("index") or []
    ph = s.get("phase") or {}
    if len(ix) < 13: return None
    ch = lambda m: round((ix[-1][1] / ix[-1 - m][1] - 1) * 100, 1)
    return {"asOf": ix[-1][0], "m3": ch(3), "m6": ch(6), "m12": ch(12), "phase": ph.get("phase"), "fromPeakPct": ph.get("fromLastPeakPct"), "volVsPrior12m": ph.get("volume6mVsPrior12mPct")}


def stats(items):
    if len(items) < 8: return None
    rate = [c["finalBidPrice"] / c["appraisalPrice"] for c in items if c.get("appraisalPrice")]
    bid = [c["bidders"] for c in items if c.get("bidders")]
    out = {"n": len(items), "rate": round(float(np.median(rate)) * 100, 1) if rate else None}
    if bid: out.update({"biddersMed": float(np.median(bid)), "crowdPct": round(float(np.mean(np.array(bid) >= 8)) * 100, 1)})
    return out


def main():
    now = datetime.now(timezone.utc)
    today = (now + timedelta(hours=9)).date()
    cases = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json()
    items = []
    for c in cases:
        try:
            fb, ap, sd = float(c.get("finalBidPrice") or 0), float(c.get("appraisalPrice") or 0), str(c.get("saleDate") or "")
        except Exception:
            continue
        if fb <= 0 or ap <= 0 or not sd[:4].isdigit() or sd > today.isoformat(): continue
        if not any(k in str(c.get("propertyType") or "") for k in ("아파트", "다세대", "연립")): continue
        sg = sido_of(c.get("addrJibun"))
        if not sg: continue
        items.append({"sido": sg, "finalBidPrice": fb, "appraisalPrice": ap, "bidders": c.get("bidders"), "date": datetime.fromisoformat(sd).date(), "apt": "아파트" in str(c.get("propertyType"))})
    print(f"  낙찰사례(결과 있음, 오늘 이전) {len(items):,}건")
    d28, d56 = today - timedelta(days=28), today - timedelta(days=56)
    rows = {}
    for sg in SIDOS + ["전체"]:
        mine = [i for i in items if sg == "전체" or i["sido"] == sg]
        cur = stats([i for i in mine if i["date"] > d28]); prev = stats([i for i in mine if d56 < i["date"] <= d28])
        cp = cycle_part(sg) if sg != "전체" else None
        row = {"sido": sg, "cycle": cp, "now": cur, "prev": prev, "warn": []}
        if cp:
            if cp["m3"] < 0 and cp["m6"] < 0: row["warn"].append("시세 3·6개월 모두 하락")
            if cp["phase"] == "하락기": row["warn"].append("사이클 하락기")
            if cp["volVsPrior12m"] is not None and cp["volVsPrior12m"] <= -15: row["warn"].append(f"거래량 급감({cp['volVsPrior12m']}%)")
        if cur and prev and cur["rate"] and prev["rate"] and cur["rate"] - prev["rate"] >= 5: row["warn"].append(f"낙찰가율 급등(+{round(cur['rate'] - prev['rate'], 1)}%p)")
        rows[sg] = row
        print(f"  {sg}: 시세 {cp and (cp['m3'], cp['m6'], cp['m12'])} 국면 {cp and cp['phase']} | 최근4주 {cur} | 경고 {row['warn']}")
    prevp = {}
    try:
        rr = requests.get(f"{cyc.SUPABASE_URL}/rest/v1/leader_follower_cache?select=payload&id=eq.signal%7C__market_snapshot__", headers=cyc.HEADERS, timeout=60)
        if rr.ok and rr.json(): prevp = rr.json()[0].get("payload") or {}
    except Exception as e:
        print("  지난 기록 읽기 실패:", e)
    wk = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    hist = [h for h in (prevp.get("history") or []) if h.get("week") != wk]
    hist.append({"week": wk, "rows": {k: {"m3": (v["cycle"] or {}).get("m3"), "rate": (v["now"] or {}).get("rate"), "n": (v["now"] or {}).get("n"), "bidders": (v["now"] or {}).get("biddersMed")} for k, v in rows.items()}})
    P = {"generatedAt": now.isoformat(), "week": wk, "rows": rows, "history": hist[-26:], "note": "낙찰가율=낙찰가÷감정가 중앙값(최근 4주, 8건 미만 지역은 비움). 경고는 참고용이며 계산 규칙은 자동으로 바뀌지 않음."}
    cyc.upsert_rows([{"id": "signal|__market_snapshot__", "payload": cyc.clean_json(P), "fetched_at": P["generatedAt"]}])
    print("  ✅ 시장 요약 저장:", wk, "경고 있는 지역", [k for k, v in rows.items() if v["warn"]])


if __name__ == "__main__":
    main()
