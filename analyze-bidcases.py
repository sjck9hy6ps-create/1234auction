"""
════════════════════════════════════════════════════════════
낙찰사례 대규모 검증 (2026-10)
════════════════════════════════════════════════════════════
사용자가 탱크옥션 CSV 68개(부산·대전·전남·광주 아파트 낙찰 6,800건, 2023~2026)를 낙찰사례로 올림 - 입찰자수·차순위(2등) 가격 포함.
앱 화면 검증은 지도용 최근 2년 실거래만 써서 2023~2025년 낙찰은 "당시 자료로 맞혔는지" 볼 수 없었음 - 여기서는
house_trades 2017~ 전체를 써서 사건마다 "입찰일 30일 전까지의 자료만으로" 예상매도가를 내고 실제 결과와 비교함.

예상매도가(앱 규칙을 단순화해 재현): 같은 단지(동+지번) 같은 면적(±2㎡) 실거래, 직거래 제외,
  같은 층 구간(1층 / 2층 이상) 우선 - 없으면 다른 층 구간을 1층 = 일반층의 91.5%로 보정,
  최근 1년 3건 이상이면 그것만, 아니면 3년까지 넓히고 시군구 월별 지수로 입찰 시점 가격으로 맞춤, 평당가 40% 지점 × 면적.
  같은 단지 거래가 없으면 예상매도가 없음(앱은 주변 단지를 쓰지만 여기선 제외 - 커버리지로 따로 보고).
재매도: 같은 단지·같은 면적·같은 층, 낙찰 14일 이후 첫 거래(직거래 제외), 낙찰가×1.02 이하인 건은 이상치로 제외.
낙찰 확률: 낙찰가 ÷ 예상매도가가 r 이하인 사건 비율 = "예상매도가의 r로 썼다면 낙찰됐을 비율"(1등보다 높게 쓰면 낙찰).
손해(근사): 재매도가 < 낙찰가 × 1.07 (취득세·등기·명도·이사·중개·이자 등 7% 가정 - 앱의 정밀 비용 계산은 아님).
⚠️ 2026-10 사용자 기준: "경매의 핵심은 낙찰될 가격이 아니라 낙찰·매도 후 수익을 구현할 수 있는지", "누구나 1등으로 보는
인기 물건보다 객관적 지표로 틈새를 찾는 게 중요" - 그래서 핵심 결과는 낙찰 확률이 아니라 "입찰 전에 알 수 있는 조건별로
낙찰자가 실제로 번 돈(실현 수익률)과 경쟁(입찰자 수)"이고, 수익은 높은데 입찰자가 적은 조건(틈새)을 찾아 순위를 매김.
실현 수익률(근사) = (재매도가 − 낙찰가 × 1.07) ÷ 낙찰가. 재매도 안 된 건은 수익을 알 수 없어 "재매도 비율"로 따로 봄.
결과: leader_follower_cache 'bidcase|__validation__' + GitHub 요약.
"""
import os
import json
import math
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
avm = cyc.avm

SITE_URL = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
GROUND_RATIO = 0.915
COST_RATIO = 1.07


def sido_norm(s):
    s = str(s or "")
    if s.startswith(("전남광주", "광주", "전남", "전라남")):
        return "전남광주"
    if s.startswith(("전북", "전라북")):
        return "전북"
    if s.startswith(("경남", "경상남")):
        return "경남"
    if s.startswith(("경북", "경상북")):
        return "경북"
    if s.startswith(("충남", "충청남")):
        return "충남"
    if s.startswith(("충북", "충청북")):
        return "충북"
    return s[:2]


def region_norm(addr_or_region):
    t = str(addr_or_region or "").split()
    if len(t) < 2:
        return None
    return sido_norm(t[0]) + " " + t[1]


def dong_key(d):
    t = str(d or "").split()
    return t[-1] if t else ""


def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def int_to_date(v):
    v = int(v)
    return datetime(v // 10000, (v // 100) % 100, v % 100)


def fails_from_ratio(r):
    if r is None or not np.isfinite(r):
        return None
    if r >= 0.995:
        return 0
    for n in range(1, 8):
        for lv in (0.8 ** n, 0.7 ** n, 0.7 * 0.8 ** (n - 1)):
            if abs(lv - r) < 0.004:
                return n
    return None


def main():
    now = datetime.now(timezone.utc).isoformat()
    print("🏃 낙찰사례 검증 시작", now)
    cases = requests.get(f"{SITE_URL}/api/auction?kind=bidCases", timeout=120).json()
    df = pd.DataFrame(cases)
    print(f"  낙찰사례 {len(df):,}건")
    df = df[df["propertyType"].astype(str).str.contains("아파트", na=False)]
    df = df[pd.to_numeric(df["finalBidPrice"], errors="coerce") > 0]
    df = df[df["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    df["actual"] = pd.to_numeric(df["finalBidPrice"]) / 10000.0
    df["appraisal"] = pd.to_numeric(df["appraisalPrice"], errors="coerce") / 10000.0
    df["minbid"] = pd.to_numeric(df["minBidPrice"], errors="coerce") / 10000.0
    df["second"] = pd.to_numeric(df.get("secondBidPrice"), errors="coerce") / 10000.0
    df["bidders"] = pd.to_numeric(df.get("bidders"), errors="coerce")
    df["area"] = pd.to_numeric(df["areaM2"], errors="coerce")
    df["floor_n"] = pd.to_numeric(df["floor"], errors="coerce")
    df["region"] = df["addrJibun"].map(region_norm)
    df["sido"] = df["region"].map(lambda r: r.split()[0] if r else None)
    df["dk"] = df["dong"].map(dong_key)
    df["bunji_s"] = df["bunji"].astype(str).str.strip()
    df["sale_int"] = df["saleDate"].str.replace("-", "").astype(int)
    df["fails"] = (df["minbid"] / df["appraisal"]).map(fails_from_ratio)
    df = df.dropna(subset=["region", "area", "dk"]).reset_index(drop=True)
    print(f"  아파트·낙찰가 있음 {len(df):,}건, 지역 {df['region'].nunique()}곳")

    # ── 실거래(2017~) - 대상 시군구만 ──
    want = set(df["region"].unique())
    names = set()
    for r in want:
        sd, gu = r.split(" ", 1)
        for alias in ({"전남광주": ["전남광주", "광주", "전남"]}.get(sd, [sd])):
            names.add(f"{alias} {gu}")
    flt = "&region=in.(" + ",".join('"' + n + '"' for n in sorted(names)) + ")"
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year",
                            extra_filter=f"&deal_date=gte.{cyc.START_DATE}{flt}")
    tr = tr[tr["dealing_type"] != "직거래"].copy() if "dealing_type" in tr.columns else tr
    for c in ("price", "size", "floor", "deal_date", "build_year"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr = tr[(tr["price"] > 0) & (tr["size"] > 10)]
    tr["region_n"] = tr["region"].map(region_norm)
    tr["dk"] = tr["dong"].map(dong_key)
    tr["bunji_s"] = tr["bunji"].astype(str).str.strip()
    tr["ppm"] = tr["price"] / tr["size"]
    tr["ym"] = (tr["deal_date"] // 100).astype(int)
    print(f"  실거래 {len(tr):,}건")

    # 시군구 월별 지수(평당가 중앙값, 3개월 이동평균) - 3년 창을 쓸 때 입찰 시점 가격으로 맞추는 데 씀
    idx = tr.groupby(["region_n", "ym"])["ppm"].median().rename("m").reset_index()
    idx_map = {}
    months = []
    y, m = 2017, 1
    while y * 100 + m <= int(datetime.now().strftime("%Y%m")):
        months.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    for rg, g in idx.groupby("region_n"):
        s = g.set_index("ym")["m"].sort_index().rolling(3, min_periods=1).median()
        idx_map[rg] = s.reindex(months).ffill().to_dict()  # 빈 달은 직전 값으로 채워 바로 찾기

    def idx_at(rg, ym):
        d = idx_map.get(rg)
        v = d.get(int(ym)) if d else None
        return v if v is not None and np.isfinite(v) else None

    groups = {k: g for k, g in tr.groupby(["region_n", "dk", "bunji_s"])}
    # 인기 등급(현재 기준 - 약간의 미래 정보가 섞임): pop|<시군구>
    pop = {}
    try:
        ids = ["pop|" + r for r in want]
        url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/leader_follower_cache"
        hdr = {"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"]}
        for i in range(0, len(ids), 20):
            q = ",".join('"' + x + '"' for x in ids[i:i + 20])
            res = requests.get(url, headers=hdr, params={"select": "id,payload", "id": f"in.({q})"}, timeout=60).json()
            for row in res or []:
                rg = row["id"].split("|", 1)[1]
                p = row["payload"] or {}
                for dg, lst in (p.get("byDong") or {}).items():
                    for x in lst:
                        pop[(rg, dong_key(dg), avm.normalize_complex_name(x.get("danji")))] = x.get("tier")
                for dg, bands in (p.get("byDongBand") or {}).items():
                    for bn, lst in (bands or {}).items():
                        for x in lst:
                            pop[(rg, dong_key(dg), avm.normalize_complex_name(x.get("danji")), bn)] = x.get("tier")
    except Exception as e:
        print("  인기 등급 불러오기 실패(건너뜀):", e)

    out = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        rec = {"region": c.region, "sido": c.sido, "sale": c.sale_int, "actual": c.actual, "second": c.second, "bidders": c.bidders,
               "appraisal": c.appraisal, "minbid": c.minbid, "fails": c.fails, "est": None, "own": 0, "resale": None, "resale_m": None, "tier": None,
               "area": c.area, "floor": c.floor_n, "cx3y": 0, "age": None, "bandTier": None,
               "notes": str(getattr(c, "specialConditions", "") or ""), "land": str(getattr(c, "landType", "") or "")}
        if g is not None and len(g):
            same = g[(g["size"] - c.area).abs() <= 2]
            sale_d = int_to_date(c.sale_int)
            cut = ymd_int(sale_d - timedelta(days=30))
            ground = (c.floor_n == 1)
            hist = same[same["deal_date"] < cut]
            tier_same = hist[(hist["floor"] == 1) == ground] if pd.notna(c.floor_n) else hist
            other = hist[(hist["floor"] == 1) != ground] if pd.notna(c.floor_n) else hist.iloc[0:0]
            cut_ym = cut // 100
            est = None; own = 0
            for days in (365, 1095):
                lo = ymd_int(sale_d - timedelta(days=30 + days))
                use = tier_same[tier_same["deal_date"] >= lo]
                adj = 1.0
                if len(use) == 0:
                    use = other[other["deal_date"] >= lo]
                    adj = GROUND_RATIO if ground else 1 / GROUND_RATIO
                if len(use) >= 3 or (days == 1095 and len(use) >= 1):
                    base = idx_at(c.region, cut_ym)
                    vals = []
                    for t in use.itertuples():
                        f = 1.0
                        if days == 1095 and base:
                            b0 = idx_at(c.region, t.ym)
                            if b0:
                                f = max(0.7, min(1.4, base / b0))
                        vals.append(t.ppm * f * adj)
                    vals = np.sort(np.array(vals))
                    est = float(np.quantile(vals, 0.4)) * c.area
                    own = len(use)
                    break
            rec["est"] = est; rec["own"] = own
            # 재매도
            if pd.notna(c.floor_n):
                after = same[(same["deal_date"] >= ymd_int(sale_d + timedelta(days=14))) & (same["floor"] == c.floor_n)]
                if len(after):
                    t0 = after.sort_values("deal_date").iloc[0]
                    if t0["price"] > c.actual * 1.02:
                        rec["resale"] = float(t0["price"])
                        rec["resale_m"] = round((int_to_date(int(t0["deal_date"])) - sale_d).days / 30.4, 1)
            nm = avm.normalize_complex_name(g["danji"].mode().iloc[0]) if len(g) else None
            rec["tier"] = pop.get((c.region, c.dk, nm))
            band = "소형" if c.area < 60 else ("중형" if c.area <= 85 else "대형")
            rec["bandTier"] = pop.get((c.region, c.dk, nm, band))
            # 단지 전체 최근 3년 거래(입찰 전 기준) - 거래 활발도
            rec["cx3y"] = int(((g["deal_date"] < cut) & (g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 1095)))).sum())
            by = pd.to_numeric(g["build_year"], errors="coerce").dropna()
            if len(by):
                rec["age"] = int(sale_d.year - int(by.mode().iloc[0]))
        out.append(rec)
    R = pd.DataFrame(out)
    R["ratio"] = R["actual"] / R["est"]
    R["err"] = (R["est"] - R["resale"]) / R["resale"]
    R["second_gap"] = (R["actual"] - R["second"]) / R["est"]
    R["loss"] = R["resale"] < R["actual"] * COST_RATIO
    obs_cut = ymd_int(datetime.now() - timedelta(days=270))  # 낙찰 후 9개월 이상 지난 건만 재매도 비율 계산

    def med(s):
        s = pd.Series(s).dropna()
        return round(float(s.median()), 3) if len(s) else None

    def block(G):
        e = G.dropna(subset=["est"])
        w = e[e["resale"].notna()]
        old = G[G["sale"] <= obs_cut]
        win = {}
        for r in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00):
            win[f"{int(r * 100)}%"] = round(float((e["ratio"] <= r).mean()) * 100, 1) if len(e) else None
        return {
            "n": int(len(G)), "estCoveragePct": round(len(e) / len(G) * 100, 1) if len(G) else None,
            "saleErrMedAbsPct": round(float(w["err"].abs().median()) * 100, 1) if len(w) else None,
            "saleErrBiasPct": round(float(w["err"].median()) * 100, 1) if len(w) else None,
            "resaleChecked": int(len(w)),
            "actualOverEstMed": med(e["ratio"]),
            "winProbByBidRatio": win,
            "secondGapMedPctOfEst": round(float(e["second_gap"].dropna().median()) * 100, 1) if e["second_gap"].notna().any() else None,
            "biddersMed": med(G["bidders"]),
            "resaleRateOld": round(float(old["resale"].notna().mean()) * 100, 1) if len(old) else None,
            "resaleMonthsMed": med(G["resale_m"]),
            "winnerLossPct": round(float(G.loc[G["resale"].notna(), "loss"].mean()) * 100, 1) if G["resale"].notna().any() else None,
        }

    summary = {"generatedAt": now, "n": int(len(R)), "all": block(R), "bySido": {}, "byFails": {}, "byBidders": {}, "byTierFails": {}, "byOwn": {}}
    for sd, G in R.groupby("sido"):
        summary["bySido"][sd] = block(G)
    R["fails_b"] = R["fails"].map(lambda f: "신건" if f == 0 else ("1회 유찰" if f == 1 else ("2회+ 유찰" if f and f >= 2 else None)))
    for k, G in R.groupby("fails_b"):
        summary["byFails"][k] = block(G)
    R["bid_b"] = R["bidders"].map(lambda b: None if pd.isna(b) else ("1명" if b <= 1 else ("2~3명" if b <= 3 else ("4~9명" if b <= 9 else "10명+"))))
    for k, G in R.groupby("bid_b"):
        summary["byBidders"][k] = block(G)
    R["own_b"] = R["own"].map(lambda o: "같은 단지 3건+" if o >= 3 else ("1~2건" if o >= 1 else "없음"))
    for k, G in R.groupby("own_b"):
        summary["byOwn"][k] = block(G)
    for (t, f), G in R.dropna(subset=["tier", "fails_b"]).groupby(["tier", "fails_b"]):
        summary["byTierFails"][f"{t}|{f}"] = block(G)

    # ── 틈새 찾기: 입찰 전에 알 수 있는 조건별 실현 수익 ──
    R["net"] = (R["resale"] - R["actual"] * COST_RATIO) / R["actual"]
    R["band"] = R["area"].map(lambda a: "소형" if a < 60 else ("중형" if a <= 85 else "대형"))
    R["floor_b"] = R["floor"].map(lambda f: None if pd.isna(f) else ("1층" if f <= 1 else ("2~3층" if f <= 3 else "4층+")))
    R["age_b"] = R["age"].map(lambda a: None if a is None or pd.isna(a) else ("10년 이하" if a <= 10 else ("11~20년" if a <= 20 else ("21~30년" if a <= 30 else "30년 초과"))))
    R["price_b"] = R["actual"].map(lambda v: "1억 미만" if v < 10000 else ("1~2억" if v < 20000 else ("2~3억" if v < 30000 else ("3~5억" if v < 50000 else "5억+"))))
    R["liq_b"] = R["cx3y"].map(lambda n: "3년 거래 0~5건" if n <= 5 else ("6~20건" if n <= 20 else ("21~60건" if n <= 60 else "61건+")))
    R["disc"] = R["minbid"] / R["est"]
    R["disc_b"] = R["disc"].map(lambda d: None if pd.isna(d) else ("최저가 시세 70% 미만" if d < 0.7 else ("70~80%" if d < 0.8 else ("80~90%" if d < 0.9 else "90%+"))))
    R["appr_b"] = (R["appraisal"] / R["est"]).map(lambda d: None if pd.isna(d) else ("감정가<시세 90%" if d < 0.9 else ("감정가≈시세" if d <= 1.1 else "감정가>시세 110%")))
    R["note_b"] = R["notes"].map(lambda t: "토지별도등기" if "토지별도" in t else ("외 필지" if "필지" in t else "특이사항 없음"))
    R["tier_b"] = R["tier"].fillna("자료없음")
    R["bandTier_b"] = R["bandTier"].fillna("자료없음")
    R = R[R["land"] != "none"]
    OLD = R[R["sale"] <= obs_cut]

    def seg_stats(G):
        res = G[G["resale"].notna()]
        old = G[G["sale"] <= obs_cut]
        if len(res) == 0:
            return None
        return {"n": int(len(G)), "resold": int(len(res)),
                "netMedPct": round(float(res["net"].median()) * 100, 1),
                "profitPct": round(float((res["net"] > 0).mean()) * 100, 1),
                "bigLossPct": round(float((res["net"] < -0.05).mean()) * 100, 1),
                "biddersMed": med(G["bidders"]),
                "resaleRateOld": round(float(old["resale"].notna().mean()) * 100, 1) if len(old) >= 10 else None,
                "monthsMed": med(res["resale_m"])}

    FEATS = ["fails_b", "tier_b", "bandTier_b", "band", "floor_b", "age_b", "price_b", "liq_b", "disc_b", "appr_b", "note_b"]
    single = {}
    for sd, GS in [("전체", R)] + list(R.groupby("sido")):
        single[sd] = {}
        for f in FEATS:
            single[sd][f] = {str(k): seg_stats(G) for k, G in GS.groupby(f) if seg_stats(G)}
    summary["profitBySingleFeature"] = single
    # 두 조건 조합 - 재매도 확인 30건 이상만, 수익률 높고 입찰자 적은 순(틈새 점수 = 수익률 중앙값 − 입찰자 1명당 0.3%p)
    combos = []
    for sd, GS in [("전체", R)] + list(R.groupby("sido")):
        for i, f1 in enumerate(FEATS):
            for f2 in FEATS[i + 1:]:
                for (k1, k2), G in GS.groupby([f1, f2]):
                    st = seg_stats(G)
                    if not st or st["resold"] < 30:
                        continue
                    base = GS[GS["resale"].notna()]["net"].median()
                    st.update({"sido": sd, "cond": f"{f1}={k1} & {f2}={k2}",
                               "vsRegionPctp": round((st["netMedPct"] / 100 - float(base)) * 100, 1),
                               "nicheScore": round(st["netMedPct"] - 0.3 * (st["biddersMed"] or 0), 1)})
                    combos.append(st)
    combos.sort(key=lambda x: -x["nicheScore"])
    summary["nicheTop"] = {sd: [c for c in combos if c["sido"] == sd and c["profitPct"] >= 70][:15] for sd in ["전체"] + sorted(R["sido"].dropna().unique())}
    summary["crowdedWorst"] = sorted([c for c in combos if c["sido"] == "전체"], key=lambda x: x["netMedPct"])[:10]

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    cyc.upsert_rows([{"id": "bidcase|__validation__", "payload": cyc.clean_json(summary), "fetched_at": now}])
    print("✅ 저장 완료")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 낙찰사례 검증\n\n```\n" + json.dumps(summary, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
