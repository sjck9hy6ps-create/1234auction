"""
══════════════════════════════════════════════════
🏗️ 입주 예정 물량 → 낙찰 후 매도 검증 (2026-10)
══════════════════════════════════════════════════
사용자 요청(2026-10-05): 경매 신뢰도를 높일 자료 - "입주 예정 물량". 보유하는 5~8개월 사이 근처에 대단지가 입주하면
매물이 쏟아져 안 팔리거나 값이 떨어질 수 있음 → 과거 낙찰사례로 실제 그랬는지 확인.
- 청약홈 APT 분양 공고(공급 위치·세대수·입주 예정 월, mode=applyhomeRaw&src=apt)로 시군구별 월별 입주 물량을 만듦
- 낙찰사례(동까지 아는 것, 2023-01 ~ 낙찰 후 12개월 지난 것)마다 "낙찰 후 12개월 안 그 시군구 입주 세대수"를 붙이고,
  그 시군구 1년 아파트 거래량으로 나눠 상대 크기로 비교(거래량 = signal|__region_liquidity__)
- 결과: 입주 물량 많고 적음에 따라 12개월 안 되판 비율(같은 동·층 확인)·보유 기간·되판 값 ÷ 낙찰가
결과 저장: leader_follower_cache 'signal|__supply__'(시군구별 월별 입주 물량 - 앱 표시용)
"""
import os
import re
import json
import importlib.util
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")


def sido_norm(s):
    s = str(s or "")
    for k, v in (("전남광주", "전남광주"), ("광주", "전남광주"), ("전남", "전남광주"), ("전라남", "전남광주"), ("전북", "전북"), ("전라북", "전북"),
                 ("경남", "경남"), ("경상남", "경남"), ("경북", "경북"), ("경상북", "경북"), ("충남", "충남"), ("충청남", "충남"), ("충북", "충북"), ("충청북", "충북")):
        if s.startswith(k):
            return v
    return s[:2]


def region_key(addr):
    t = str(addr or "").split()
    if len(t) < 2:
        return None
    city = t[1]
    if len(t) >= 3 and city.endswith("시") and t[2].endswith("구"):
        city = city[:-1]
    return sido_norm(t[0]) + " " + city


def ym_add(ym, k):
    y, m = divmod(ym // 100 * 12 + ym % 100 - 1 + k, 12)
    return y * 100 + m + 1


def main():
    now = datetime.now(timezone.utc)
    # 1) 청약홈 APT 분양 공고 전체
    items = []
    page = 1
    while True:
        r = requests.get(f"{SITE}/api/data-coverage", params={"mode": "applyhomeRaw", "src": "apt", "page": page, "perPage": 1000}, timeout=120).json()
        its = r.get("items") or []
        items += its
        print(f"  공고 {page}쪽 {len(its)}건 (전체 {r.get('totalCount')})")
        if len(its) < 1000:
            break
        page += 1
    rows = []
    for it in items:
        rg = region_key(it.get("HSSPLY_ADRES"))
        ym = str(it.get("MVN_PREARNGE_YM") or "")
        hh = pd.to_numeric(it.get("TOT_SUPLY_HSHLDCO"), errors="coerce")
        if rg and re.match(r"^\d{6}$", ym) and hh and hh > 0:
            rows.append({"region": rg, "ym": int(ym), "hh": int(hh), "name": it.get("HOUSE_NM"), "pblanc": it.get("RCRIT_PBLANC_DE")})
    S = pd.DataFrame(rows).drop_duplicates(subset=["name", "ym"])
    print(f"  입주 예정 공고 {len(S):,}건, 입주 월 {S['ym'].min()}~{S['ym'].max()}, 시군구 {S['region'].nunique()}곳")
    sup = S.groupby(["region", "ym"])["hh"].sum()

    # 2) 시군구 1년 거래량(상대 크기용)
    hdr = {"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"]}
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/leader_follower_cache"
    liq = requests.get(url, headers=hdr, params={"select": "payload", "id": "eq.signal|__region_liquidity__"}, timeout=60).json()
    trades1y = {x["region"]: x["trades1y"] for x in ((liq[0]["payload"] or {}).get("regions", []) if liq else [])}

    # 3) 낙찰사례: 동을 알고, 낙찰 후 12개월 지난 것
    cases = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json()
    cut = int((pd.Timestamp(now.date()) - pd.Timedelta(days=365)).strftime("%Y%m%d"))
    R = []
    for c in cases:
        if "아파트" not in str(c.get("propertyType") or "") or not c.get("aptDong"):
            continue
        sd = str(c.get("saleDate") or "")
        if not re.match(r"^\d{4}-\d\d-\d\d$", sd) or sd < "2023-01-01":
            continue
        si = int(sd.replace("-", ""))
        if si > cut:
            continue
        rg = region_key(c.get("addrJibun"))
        if not rg:
            continue
        ym0 = si // 100
        s12 = sum(int(sup.get((rg, ym_add(ym0, k)), 0)) for k in range(0, 13))
        s6 = sum(int(sup.get((rg, ym_add(ym0, k)), 0)) for k in range(0, 7))
        prev = sum(int(sup.get((rg, ym_add(ym0, -k)), 0)) for k in range(1, 13))
        m = c.get("resaleMatch") or {}
        sold = m.get("conf") == "dong"
        hold = None
        if sold and m.get("date"):
            d = pd.to_datetime(str(m["date"]), format="%Y%m%d", errors="coerce")
            hold = (d - pd.Timestamp(sd)).days / 30.4 if pd.notna(d) else None
        act = (c.get("finalBidPrice") or 0) / 10000
        R.append({"region": rg, "sale": si, "s12": s12, "s6": s6, "prev12": prev, "t1y": trades1y.get(rg), "sold12": bool(sold and hold is not None and hold <= 12),
                  "sold": sold, "hold": hold, "ratio": (float(m["amount"]) / act) if (sold and act) else None, "floorOnly": m.get("conf") == "floor"})
    D = pd.DataFrame(R)
    D["rel"] = D["s12"] / D["t1y"]
    print(f"  낙찰사례 {len(D):,}건(동 앎·12개월 지남), 거래량 있는 지역 {D['t1y'].notna().sum():,}건")

    def stat(G):
        sold = G[G["sold"]]
        return {"n": int(len(G)), "sold12Pct": round(float(G["sold12"].mean()) * 100, 1), "holdMed": round(float(sold["hold"].median()), 1) if len(sold) else None,
                "resaleOverBidMed": round(float(sold["ratio"].median()), 3) if len(sold) else None, "floorOnlyPct": round(float(G["floorOnly"].mean()) * 100, 1)}
    out = {"generatedAt": now.isoformat()}
    D1 = D[D["t1y"].notna()].copy()
    bins = [(-1, 0.0001, "입주 없음"), (0.0001, 0.25, "거래량의 25% 미만"), (0.25, 0.5, "25~50%"), (0.5, 1.0, "50~100%"), (1.0, 99, "100% 이상")]
    out["byRelSupply12"] = {lab: stat(D1[(D1["rel"] > lo) & (D1["rel"] <= hi)]) if lo >= 0 else stat(D1[D1["rel"] <= hi]) for lo, hi, lab in bins}
    D1["rel6"] = D1["s6"] / D1["t1y"]
    out["byRelSupply6"] = {lab: stat(D1[(D1["rel6"] > lo) & (D1["rel6"] <= hi)]) if lo >= 0 else stat(D1[D1["rel6"] <= hi]) for lo, hi, lab in bins}
    # 같은 지역 안에서(지역 효과 제거): 그 시군구의 평소보다 입주가 많을 때 vs 적을 때
    D1["regMed"] = D1.groupby("region")["rel"].transform("median")
    hi = D1[D1["rel"] > D1["regMed"] * 1.5 + 0.05]
    lo = D1[D1["rel"] <= D1["regMed"]]
    out["withinRegion"] = {"평소보다 많을 때": stat(hi), "평소 이하": stat(lo)}
    D1["yr"] = D1["sale"] // 10000
    # 2023은 되판 거래에 동 정보가 없던 시기(층만 일치 비율 높음)라 섞이면 착시 → 2024~25만 따로, 같은 지역 안 비교
    E = D1[D1["yr"] >= 2024].copy()
    E["regMed"] = E.groupby("region")["rel"].transform("median")
    out["withinRegion2425"] = {"평소보다 많을 때": stat(E[E["rel"] > E["regMed"] * 1.5 + 0.05]), "평소 이하": stat(E[E["rel"] <= E["regMed"]])}
    E["regMed6"] = E.groupby("region")["rel6"].transform("median")
    out["withinRegion2425_6m"] = {"평소보다 많을 때": stat(E[E["rel6"] > E["regMed6"] * 1.5 + 0.05]), "평소 이하": stat(E[E["rel6"] <= E["regMed6"]])}
    out["byYear"] = {int(y): {lab: stat(G[(G["rel"] > lo_) & (G["rel"] <= hi_)]) if lo_ >= 0 else stat(G[G["rel"] <= hi_]) for lo_, hi_, lab in [(-1, 0.0001, "입주 없음"), (0.0001, 0.5, "50% 미만"), (0.5, 99, "50% 이상")]} for y, G in D1.groupby("yr")}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    # 앱 표시용: 시군구별 월별 입주 물량(2026-01 이후)
    fut = S[S["ym"] >= int(now.strftime("%Y%m")) - 100]
    payload = {"generatedAt": now.isoformat(), "byRegion": {}, "validation": out}
    for rg, G in fut.groupby("region"):
        payload["byRegion"][rg] = {"months": {str(k): int(v) for k, v in G.groupby("ym")["hh"].sum().items()},
                                   "complexes": G.sort_values("ym")[["name", "ym", "hh"]].head(30).to_dict("records"), "trades1y": trades1y.get(rg)}
    cyc.upsert_rows([{"id": "signal|__supply__", "payload": cyc.clean_json(payload), "fetched_at": now.isoformat()}])
    print("✅ 저장 완료")


if __name__ == "__main__":
    main()
