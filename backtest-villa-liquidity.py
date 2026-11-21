"""
🏘️ 빌라 '생활권 거래 활발도'와 낙찰 후 되팔림 (2026-10-10, 사용자: "빌라는 지역이 중요 - 최근 1년·6개월·1년 이전 거래를 나눠 보던 이유는 구매하는 지역을 확인하려는 것. 법정동이 아니라 생활권.
최근 거래가 없는 지역은 금액만 보고 낙찰받아도 매도가 어렵다는 판단 - 근거와 적절한 조건을 만들어줘")
방법: 수도권 빌라 낙찰사례(매각, 2021~2025-05)마다 낙찰일 기준 반경 500m/1km 안 빌라 매매 거래 수(최근 6개월 / 6~12개월 / 12~24개월)를 세고,
      낙찰 후 12개월 안에 같은 건물·같은 층·같은 면적(±1.5㎡)의 매매가 있었는지(=되팔림 흔적)와 되판 값÷낙찰가를 봄.
결과: 거래 수 구간별 되팔림 비율, '최근 6개월 거래 0건' 여부별 비교, 같은 건물 직전 거래 유무로 나눈 비교
"""
import os, json, importlib.util, requests
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.20190101{FLT}")
    df = bv.prep(raw)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    co = k_new.map(cmap)
    for alt in (k_leg, k_leg0): co = co.where(~co.isna(), alt.map(cmap))
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    D = df[df["lat"].notna()].reset_index(drop=True)
    print(f"빌라 거래 {len(df):,}건, 좌표 있는 거래 {len(D):,}건, 마지막 거래일 {int(df['deal_date'].max())}")
    X = np.c_[D["lat"].values * 111.0, D["lon"].values * 111.0 * np.cos(np.radians(37.5))]
    tree = cKDTree(X); day = D["day"].values
    # 같은 건물 거래 색인
    bld = {k: G for k, G in df.groupby("bld")}
    cases = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json()
    last_day = int(df["day"].max())
    rows = []
    for c in cases:
        if not any(k in str(c.get("propertyType") or "") for k in ("다세대", "연립", "도시형")): continue
        if c.get("status") != "매각" or not str(c.get("addrJibun", "")).startswith(("서울", "경기", "인천")): continue
        sd = str(c.get("saleDate") or "")
        if not (sd >= "2021-01-01" and sd <= "2026-03-31"): continue
        try: sday = (pd.Timestamp(sd) - pd.Timestamp("2020-01-01")).days; bidp = float(c["finalBidPrice"]) / 10000; area = float(c["areaM2"])
        except Exception: continue
        lat, lon = c.get("lat"), c.get("lon")
        sub = df[(df["dong"] == c.get("dong")) & (df["bunji"].astype(str) == str(c.get("bunji")))] if c.get("dong") and c.get("bunji") else df.iloc[0:0]
        reg = None
        if len(sub):
            reg = sub["region"].mode().iloc[0]
            sub = sub[sub["region"] == reg]
            if not (lat and lon):
                m = sub[sub["lat"].notna()]
                if len(m): lat, lon = float(m["lat"].iloc[0]), float(m["lon"].iloc[0])
        if not (lat and lon): continue
        p = np.array([float(lat) * 111.0, float(lon) * 111.0 * np.cos(np.radians(37.5))])
        rec = {"sale": sd, "bid": bidp, "bidders": c.get("bidders")}
        for R in (500, 1000):
            nb = np.array(tree.query_ball_point(p, R / 1000.0), dtype=int)
            d0 = sday - day[nb] if len(nb) else np.array([])
            rec[f"n6_{R}"] = int(((d0 >= 0) & (d0 < 183)).sum()); rec[f"n12_{R}"] = int(((d0 >= 183) & (d0 < 365)).sum()); rec[f"n24_{R}"] = int(((d0 >= 365) & (d0 < 730)).sum())
        # 같은 건물 직전 12개월 거래 수
        own_before = 0; resold = None; ratio = None; resale_m = None
        if len(sub):
            g = sub
            own_before = int(((sday - g["day"] >= 0) & (sday - g["day"] < 365)).sum())
            m = g[(g["day"] > sday) & (g["day"] <= sday + 365) & ((g["size"] - area).abs() <= 1.5)]
            fl = pd.to_numeric(c.get("floor"), errors="coerce")
            if pd.notna(fl): m = m[m["floor"] == fl]
            resold = bool(len(m)); ratio = float(m["price"].iloc[0] / bidp) if len(m) else None
            m18 = g[(g["day"] > sday) & (g["day"] <= sday + 548) & ((g["size"] - area).abs() <= 1.5)]
            if pd.notna(fl): m18 = m18[m18["floor"] == fl]
            resale_m = float((m18["day"].min() - sday) / 30.4) if len(m18) else None
        else:
            resold = False; resale_m = None  # 같은 건물 거래 자체가 없으면 되판 흔적 없음
        rec.update({"own12": own_before, "resold": resold, "ratio": ratio, "hasBld": bool(len(sub)), "resale_m": resale_m, "sday": sday}); rows.append(rec)
    R = pd.DataFrame(rows); print(f"분석 낙찰사례 {len(R):,}건 · 되판 흔적 {R['resold'].mean() * 100:.1f}%")
    out = {"n": int(len(R)), "resold12Pct": round(float(R["resold"].mean()) * 100, 1), "건물 거래 이력 있는 사례": int(R["hasBld"].sum())}
    def tab(col, bins, labels, sub=None):
        S = R if sub is None else sub
        g = S.groupby(pd.cut(S[col], bins, labels=labels, right=False), observed=True).agg(n=("resold", "size"), resold=("resold", "mean"), ratio=("ratio", "median"))
        return {str(k): {"n": int(v.n), "resoldPct": round(float(v.resold) * 100, 1), "ratioMed": None if pd.isna(v.ratio) else round(float(v.ratio), 3)} for k, v in g.iterrows() if v.n >= 30}
    for Rr in (500, 1000):
        R[f"n_all_{Rr}"] = R[f"n6_{Rr}"] + R[f"n12_{Rr}"]
        out[f"반경{Rr}m 최근12개월 거래 수별"] = tab(f"n_all_{Rr}", [0, 1, 3, 6, 11, 21, 10000], ["0", "1-2", "3-5", "6-10", "11-20", "21+"])
        out[f"반경{Rr}m 최근6개월 거래 수별"] = tab(f"n6_{Rr}", [0, 1, 2, 4, 8, 10000], ["0", "1", "2-3", "4-7", "8+"])
        R["recentZero"] = R[f"n6_{Rr}"] == 0
        out[f"반경{Rr}m 최근6개월 0건 여부"] = {str(k): {"n": int(len(G)), "resoldPct": round(float(G["resold"].mean()) * 100, 1)} for k, G in R.groupby("recentZero")}
        R["old"] = (R[f"n24_{Rr}"] > 0) & (R[f"n_all_{Rr}"] == 0)
        out[f"반경{Rr}m 1년 이전엔 있었지만 최근 1년 0건"] = {str(k): {"n": int(len(G)), "resoldPct": round(float(G["resold"].mean()) * 100, 1)} for k, G in R.groupby("old")}
    H = R[R["hasBld"]]
    out["건물 거래 이력 있는 사례만 - 반경1km 최근12개월"] = tab("n_all_1000", [0, 1, 6, 21, 10000], ["0", "1-5", "6-20", "21+"], H)
    out["같은 건물 직전 12개월 거래 수별"] = tab("own12", [0, 1, 3, 10000], ["0", "1-2", "3+"], R)
    # ── 빌라 환금성 곡선(2026-11-21): 아파트 liquidity-curve와 같은 방식. 생활권(반경 500m) 최근 12개월 거래 수 구간별 '낙찰 후 같은 건물·같은 층·같은 면적 되팔림 흔적'까지 걸린 달.
    #    holdMonths = (18개월 안 되팔림이 25% 미만이면 그 달수의 75% 지점, 아니면 평균), 3~12개월로 제한
    R["resale_m"] = pd.to_numeric(R["resale_m"], errors="coerce")
    O12 = R[R["sday"] <= last_day - 365]; O18 = R[R["sday"] <= last_day - 548]
    bins = []
    for lo, hi, lab in ((0, 0, "0건"), (1, 2, "1~2건"), (3, 5, "3~5건"), (6, 10, "6~10건"), (11, 20, "11~20건"), (21, 10 ** 9, "21건 이상")):
        a = O12[(O12["n_all_500"] >= lo) & (O12["n_all_500"] <= hi)]; b = O18[(O18["n_all_500"] >= lo) & (O18["n_all_500"] <= hi)]
        if len(a) < 60 or len(b) < 60: print("  빌라 환금성:", lab, "사례 부족", len(a), len(b)); continue
        w = b[b["resale_m"].notna() & (b["resale_m"] <= 18)]; p18 = len(w) / len(b)
        rec = {"lo": lo, "hi": hi if hi < 10 ** 9 else None, "label": lab, "n": int(len(a)), "p6": round(float((a["resale_m"] <= 6).mean()) * 100, 1), "p12": round(float((a["resale_m"] <= 12).mean()) * 100, 1), "p18": round(p18 * 100, 1)}
        if len(w) >= 20:
            hold = round(float(w["resale_m"].quantile(.75))) if p18 < 0.25 else round(float(w["resale_m"].mean()))
            rec.update({"medMonths": round(float(w["resale_m"].median()), 1), "meanMonths": round(float(w["resale_m"].mean()), 1), "p75Months": round(float(w["resale_m"].quantile(.75)), 1), "holdMonths": int(max(3, min(12, hold)))})
        else: rec.update({"holdMonths": 12, "note": "되팔림 흔적 20건 미만 - 12개월로 둠"})
        bins.append(rec)
    out["villaLiqCurve"] = {"generatedAt": pd.Timestamp.now().strftime("%Y-%m-%d"), "basis": "수도권 빌라 낙찰사례(2021~) · 낙찰일 기준 반경 500m 최근 12개월 빌라 매매 수", "bins": bins}
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-villa-liquidity.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
