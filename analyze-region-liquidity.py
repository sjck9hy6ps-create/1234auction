"""
══════════════════════════════════════════════════
🏁 지방 시군구 "팔리는 곳" 후보 순위 (2026-10)
══════════════════════════════════════════════════
사용자 요청(2026-10-05): "틈새시장의 큰 틀 - 실제로 낙찰 가능성이 있고 낙찰 후 매도까지 잘되는 지역. 이 지역들이 어디인지 알기 위해".
경쟁 강도(낙찰사례 필요)는 analyze-bidcases.py의 competition_stats가 계산함. 여기서는 낙찰사례 없이 전국 실거래만으로
"낙찰 후 팔 수 있는 곳"을 먼저 골라냄 - 거래가 꾸준한가(분기별 거래 흔들림·꾸준한 단지 비율), 거래량, 가격대, 버틸 수 있는가(전세가율),
최근 가격 흐름(급락 제외). 그리고 낙찰사례가 이미 있는 곳/없는 곳을 표시해 어떤 지역 CSV를 더 올리면 좋을지 알려줌.
결과: leader_follower_cache 'signal|__region_liquidity__'
"""
import os
import json
import importlib.util
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
avm = cyc.avm
SITE_URL = os.environ.get("SITE_URL", "https://1234auction.vercel.app")

METRO = "and=(region.not.like.서울*,region.not.like.경기*,region.not.like.인천*)"


def sido_norm(s):
    s = str(s or "")
    for k, v in (("전남광주", "전남광주"), ("광주", "전남광주"), ("전남", "전남광주"), ("전라남", "전남광주"), ("전북", "전북"), ("전라북", "전북"),
                 ("경남", "경남"), ("경상남", "경남"), ("경북", "경북"), ("경상북", "경북"), ("충남", "충남"), ("충청남", "충남"), ("충북", "충북"), ("충청북", "충북")):
        if s.startswith(k):
            return v
    return s[:2]


def region_key(r):
    t = str(r or "").split()
    if len(t) < 2:
        return None
    city = t[1]
    if len(t) >= 3 and city.endswith("시") and t[2].endswith("구"):
        city = city[:-1]  # "전주시 완산구"(낙찰사례) ↔ "전주 완산구"(실거래)
    return sido_norm(t[0]) + " " + city


def main():
    now = datetime.now(timezone.utc)
    nowi = int(now.strftime("%Y%m%d"))
    start = int((now - timedelta(days=365 * 3 + 30)).strftime("%Y%m%d"))
    print("📦 지방 아파트 매매 불러오는 중...", start)
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,deal_date,dealing_type,cdeal_type",
                            extra_filter=f"&deal_date=gte.{start}&{METRO}")
    tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""]
    tr = tr[tr["dealing_type"] != "직거래"]
    for c in ("price", "size", "deal_date"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr = tr[(tr["price"] > 0) & (tr["size"] > 10)].copy()
    tr["rg"] = tr["region"].map(region_key)
    tr["cx"] = tr["dong"].astype(str) + "|" + tr["danji"].astype(str)
    tr["ppm"] = tr["price"] / tr["size"]
    tr["d"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce")
    tr = tr.dropna(subset=["d", "rg"])
    tr["age_d"] = (pd.Timestamp(now.date()) - tr["d"]).dt.days
    tr["q"] = (tr["age_d"] // 91).astype(int)  # 0 = 최근 분기
    print(f"  매매 {len(tr):,}건, 시군구 {tr['rg'].nunique()}곳")

    print("📦 지방 아파트 전세(최근 1년) 불러오는 중...")
    s1 = int((now - timedelta(days=365)).strftime("%Y%m%d"))
    rt = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deposit,monthly_rent,size,deal_date",
                            extra_filter=f"&deal_date=gte.{s1}&monthly_rent=eq.0&{METRO}")
    for c in ("deposit", "size"):
        rt[c] = pd.to_numeric(rt[c], errors="coerce")
    rt = rt.dropna(subset=["deposit", "size"])
    rt = rt[(rt["deposit"] > 0) & (rt["size"] > 10)].copy()
    rt["rg"] = rt["region"].map(region_key)
    rt["cx"] = rt["dong"].astype(str) + "|" + rt["danji"].astype(str)
    rt["dpm"] = rt["deposit"] / rt["size"]
    print(f"  전세 {len(rt):,}건")

    # 낙찰사례가 있는 지역 + 경쟁 강도(있으면)
    cases = requests.get(f"{SITE_URL}/api/auction?kind=bidCases", timeout=120).json()
    cov = {}
    for c in cases:
        if "아파트" not in str(c.get("propertyType") or ""):
            continue
        k = region_key(c.get("addrJibun"))
        if k:
            cov[k] = cov.get(k, 0) + 1
    comp = {}
    comp_base = {}
    try:
        url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/leader_follower_cache"
        hdr = {"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"]}
        r = requests.get(url, headers=hdr, params={"select": "payload", "id": "eq.signal|__competition__"}, timeout=60).json()
        comp = (r[0]["payload"] or {}).get("byRegion", {}) if r else {}
        comp_base = (r[0]["payload"] or {}).get("base", {}) if r else {}
    except Exception as e:
        print("  경쟁 강도 못 불러옴:", e)

    rows = []
    y1 = tr[tr["age_d"] < 365]
    prev = tr[(tr["age_d"] >= 365) & (tr["age_d"] < 730)]
    for rg, G in tr.groupby("rg"):
        g1 = G[G["age_d"] < 365]
        if len(g1) < 300:
            continue
        qc = G[G["q"] < 12].groupby("q").size().reindex(range(12), fill_value=0)
        cv = float(qc.std() / qc.mean()) if qc.mean() > 0 else None
        # 꾸준한 단지: 최근 1년 4분기 중 3분기 이상 거래 있던 단지 비율(최근 1년 거래가 있던 단지 중)
        cq = g1.groupby("cx")["q"].nunique()
        steady = float((cq >= 3).mean()) if len(cq) else None
        p0 = float(g1["ppm"].median())
        pp = prev[prev["rg"] == rg]["ppm"]
        trend = (p0 / float(pp.median()) - 1) if len(pp) >= 100 else None
        # 전세가율: 단지별(전세 3건+, 매매 3건+) 전세 ㎡당 ÷ 매매 ㎡당 중간값
        R1 = rt[rt["rg"] == rg]
        js = []
        if len(R1):
            dm = R1.groupby("cx")["dpm"].agg(["median", "size"])
            sm = g1.groupby("cx")["ppm"].agg(["median", "size"])
            j = dm.join(sm, lsuffix="_r", rsuffix="_s", how="inner")
            j = j[(j["size_r"] >= 3) & (j["size_s"] >= 3)]
            js = (j["median_r"] / j["median_s"]).tolist()
        jeonse = float(np.median(js)) if len(js) >= 5 else None
        c = comp.get(rg) or {}
        rows.append({"region": rg, "sido": rg.split()[0], "trades1y": int(len(g1)), "quarterCv": round(cv, 3) if cv is not None else None,
                     "steadyPct": round(steady * 100) if steady is not None else None, "complexes1y": int(len(cq)),
                     "priceMed": int(g1["price"].median()), "trendPct": round(trend * 100, 1) if trend is not None else None,
                     "jeonsePct": round(jeonse * 100) if jeonse is not None else None,
                     "auctionCases": int(cov.get(rg, 0)), "compMed": c.get("compMed"), "biddersMed": c.get("biddersMed"), "soldPct": c.get("soldPct"),
                     "holdMed": c.get("holdMed"), "compN": c.get("n")})
    R = pd.DataFrame(rows)
    # 점수: 꾸준함(분기 흔들림 작을수록·꾸준한 단지 비율 높을수록) + 거래량 + 전세가율, 최근 1년 5% 넘게 하락하면 감점, 가격대(0.8~4억) 밖이면 제외 표시
    def z(s):
        s = s.astype(float)
        return (s - s.mean()) / (s.std() or 1)
    R["score"] = (z(-R["quarterCv"].fillna(R["quarterCv"].median())) + z(R["steadyPct"].fillna(R["steadyPct"].median()))
                  + 0.5 * z(np.log(R["trades1y"])) + z(R["jeonsePct"].fillna(R["jeonsePct"].median()))
                  - (R["trendPct"].fillna(0) < -5) * 1.0).round(2)
    R["priceFit"] = R["priceMed"].between(8000, 40000)
    # ── 틈새 순위(2026-10, 사용자: "잘 팔리는 곳에 더 비중을 줘") ──
    # 잘 팔리는가 70%(실거래 팔리는 곳 점수 40% + 낙찰 후 되판 비율 30%) + 경쟁이 약한가 30%(1등가÷시세가 낮을수록).
    # 틈새 조건: 낙찰사례 15건 이상(경쟁 강도 있음) · 1등가÷시세 ≤ 전체 기준 · 되판 비율 ≥ 전체 기준 · 팔리는 곳 점수 ≥ 중간.
    base_comp = comp_base.get("compMed") if comp_base else None
    base_sold = comp_base.get("soldPct") if comp_base else None
    has = R["compMed"].notna()
    R["nicheScore"] = None
    if has.sum() >= 3:
        H = R[has]
        sold = H["soldPct"].fillna(H["soldPct"].median())
        R.loc[has, "nicheScore"] = (0.4 * z(H["score"]) + 0.3 * z(sold) + 0.3 * z(-H["compMed"])).round(2)
    med_score = float(R["score"].median())
    R["niche"] = has & (R["score"] >= med_score) & (R["compMed"] <= (base_comp if base_comp else 9)) & (R["soldPct"].fillna(0) >= (base_sold or 0))
    R = R.sort_values("score", ascending=False)
    niche = R[R["niche"]].sort_values("nicheScore", ascending=False)
    print(f"\n🏁 틈새 지역(경쟁 ≤ 전체 {base_comp}, 되판 ≥ {base_sold}%, 팔리는 곳 점수 ≥ 중간): {len(niche)}곳")
    ncols = ["region", "nicheScore", "score", "compMed", "biddersMed", "soldPct", "holdMed", "jeonsePct", "trendPct", "priceMed", "auctionCases"]
    if len(niche):
        print(niche[ncols].to_string(index=False))
    print("\n(경쟁 강도가 있는 지역 전체 - 틈새 점수 순)")
    print(R[has].sort_values("nicheScore", ascending=False)[ncols + ["niche"]].to_string(index=False))
    print("\n(팔리는 곳 상위인데 낙찰사례가 15건 미만 - 더 올리면 좋은 지역)")
    print(R[~has].head(25)[["region", "score", "trades1y", "jeonsePct", "trendPct", "priceMed", "auctionCases"]].to_string(index=False))
    # ── 우선 지역 목록(2026-10, 사용자: "우선 지역을 매주 새롭게 로딩해줘") - 📘 사용법의 지역 안내를 매주 이 결과로 자동 갱신 ──
    # 우선 = 틈새 조건을 통과한 곳(niche) · 경계 = 통과는 못 했지만 틈새 점수 0.5 이상 · 피할 곳 = 낙찰사례 100건 이상인데 응찰자 7명 이상이거나 되판 비율 50% 미만
    BIG_CITY = ("부산", "대구", "대전", "울산", "인천", "광주")
    def disp(rg):
        sido, _, rest = rg.partition(" ")
        rest = rest.strip() or sido
        nm = rest[:-1] if len(rest) > 2 and rest[-1] in "시군" else rest
        if sido == "전남광주":
            return ("광주 " + rest) if rest.endswith("구") else nm
        if rest.endswith("구") and sido in BIG_CITY:
            return sido + " " + rest
        return nm
    H2 = R[has]
    pri = H2[H2["niche"]].sort_values("nicheScore", ascending=False)
    bor = H2[(~H2["niche"]) & (H2["nicheScore"].astype(float) >= 0.5) & (H2["auctionCases"] >= 100)].sort_values("nicheScore", ascending=False)
    avd = H2[(H2["auctionCases"] >= 100) & ((H2["biddersMed"].fillna(0) >= 7) | (H2["soldPct"].fillna(100) < 50))].sort_values("auctionCases", ascending=False)
    pick = lambda D: [{"region": r.region, "name": disp(r.region), "compMed": r.compMed, "biddersMed": r.biddersMed, "soldPct": r.soldPct, "holdMed": r.holdMed, "cases": int(r.auctionCases)} for r in D.itertuples()]
    priority = {"asOf": now.strftime("%Y-%m-%d"), "priority": pick(pri), "border": pick(bor), "avoid": pick(avd)}
    print("\n🏁 우선 지역:", ", ".join(x["name"] for x in priority["priority"]))
    print("   경계:", ", ".join(x["name"] for x in priority["border"]))
    print("   피할 지역:", ", ".join(x["name"] for x in priority["avoid"]))
    out = {"generatedAt": now.isoformat(), "priorityRegions": priority, "note": "지방 아파트 최근 1년 300건 이상 시군구. 점수 = 거래 꾸준함 + 거래량 + 전세가율 - 급락. 틈새 점수 = 팔리는 곳 40% + 되판 30% + 경쟁 약함 30%",
           "base": comp_base, "regions": R.to_dict("records")}
    cyc.upsert_rows([{"id": "signal|__region_liquidity__", "payload": cyc.clean_json(out), "fetched_at": now.isoformat()}])
    cols = ["region", "score", "trades1y", "steadyPct", "quarterCv", "jeonsePct", "trendPct", "priceMed", "auctionCases", "compMed", "biddersMed", "soldPct"]
    print(R[cols].head(60).to_string(index=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 지방 시군구 팔리는 곳 후보\n\n```\n" + R[cols].head(80).to_string(index=False) + "\n```\n")
    print("✅ 저장 완료")


if __name__ == "__main__":
    main()
