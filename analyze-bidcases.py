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
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type",
                            extra_filter=f"&deal_date=gte.{cyc.START_DATE}{flt}")
    tr = tr[tr["dealing_type"] != "직거래"].copy() if "dealing_type" in tr.columns else tr
    for c in ("price", "size", "floor", "deal_date"):
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
    except Exception as e:
        print("  인기 등급 불러오기 실패(건너뜀):", e)

    out = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        rec = {"region": c.region, "sido": c.sido, "sale": c.sale_int, "actual": c.actual, "second": c.second, "bidders": c.bidders,
               "appraisal": c.appraisal, "minbid": c.minbid, "fails": c.fails, "est": None, "own": 0, "resale": None, "resale_m": None, "tier": None}
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

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    cyc.upsert_rows([{"id": "bidcase|__validation__", "payload": cyc.clean_json(summary), "fetched_at": now}])
    print("✅ 저장 완료")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 낙찰사례 검증\n\n```\n" + json.dumps(summary, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
