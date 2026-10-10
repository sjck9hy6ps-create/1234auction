"""
🏘️ 수도권 빌라(연립다세대) 예상매도가 백테스트 (2026-10-10, 사용자: "빌라는 동일 단지·동일 평형 거래가 없어 모두 별개의 집 - 지역 거래로 아파트 같은 예상매도가를 구할 수 있나")
방법: 거래마다 "그 거래 30일 전까지의 자료만"으로 가격을 예측해 실제 거래가와 비교(아파트 백테스트와 같은 기준).
  1순위 같은 건물(지번) 최근 24개월 비슷한 면적(±6㎡)  2순위 같은 법정동 12개월 면적 ±8㎡·준공연도 ±5년  3순위 같은 시군구 12개월 면적 ±8㎡
  가격은 ㎡당 가격으로 옮기고(면적 곱), 지역 월별 지수로 시점 보정(변형 비교)
결과: 단계별 오차·±10% 비율·쏠림, 어느 단계가 쓰였는지 비중, 분위(40%/50%)별 쏠림 → JSON 출력
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(avm)

START = 20210101
TEST_FROM = 20250101
N_TEST = int(os.environ.get("N_TEST", "40000"))


def to_dt(s):
    return pd.to_datetime(s.astype(int).astype(str), format="%Y%m%d", errors="coerce")


def main():
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year,cdeal_type",
                             extra_filter=f"&deal_date=gte.{START}{flt}")
    print(f"받은 빌라 거래 {len(raw):,}건")
    df = raw.copy()
    if "cdeal_type" in df.columns:
        df = df[df["cdeal_type"].fillna("").astype(str).str.strip() == ""]
    df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("price", "size", "floor", "deal_date", "build_year"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date"])
    df = df[(df["price"] > 0) & (df["size"] >= 15) & (df["size"] <= 150)]
    df["dt"] = to_dt(df["deal_date"]); df = df.dropna(subset=["dt"])
    df["day"] = (df["dt"] - pd.Timestamp("2020-01-01")).dt.days.astype(int)
    df["ppm"] = df["price"] / df["size"]
    df["bld"] = df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["bunji"].astype(str)
    df["dk"] = df["region"].astype(str) + "|" + df["dong"].astype(str)
    df = df.sort_values("day").reset_index(drop=True)
    print(f"분석 대상 {len(df):,}건 ({df['deal_date'].min()} ~ {df['deal_date'].max()}), 건물 {df['bld'].nunique():,}곳, 동 {df['dk'].nunique():,}곳")

    # 지역 월별 지수(㎡당 가격 중앙값의 로그, 3개월 이동평균) - 시점 보정용
    df["ym"] = (df["deal_date"] // 100).astype(int)
    mi = df.groupby(["region", "ym"])["ppm"].median().apply(np.log).unstack("ym")
    mi = mi.T.sort_index().rolling(3, min_periods=1).mean().T
    idx = {r: mi.loc[r].dropna().to_dict() for r in mi.index}

    def adj(region, ym_from, ym_to):
        d = idx.get(region)
        if not d: return 1.0
        a, b = d.get(ym_from), d.get(ym_to)
        return float(np.exp(b - a)) if a is not None and b is not None and np.isfinite(a) and np.isfinite(b) else 1.0

    groups = {}
    for key_col in ("bld", "dk", "region"):
        g = {}
        for k, G in df.groupby(key_col):
            g[k] = (G["day"].values, G["size"].values, G["ppm"].values, G["build_year"].values, G["ym"].values)
        groups[key_col] = g

    def wq(vals, w, q):
        o = np.argsort(vals); v = vals[o]; ww = w[o]; c = np.cumsum(ww) / ww.sum()
        return float(v[min(np.searchsorted(c, q), len(v) - 1)])

    def cands(key_col, key, day_c, days, size, tol, by=None, byy=None, reg=None, ym_c=None, tadj=True):
        t = groups[key_col].get(key)
        if t is None: return None
        d, sz, pp, yb, ym = t
        hi = np.searchsorted(d, day_c, side="right"); lo = np.searchsorted(d, day_c - days, side="left")
        if hi <= lo: return None
        m = np.abs(sz[lo:hi] - size) <= tol
        if by is not None and byy is not None and np.isfinite(by):
            ok = np.isnan(yb[lo:hi]) | (np.abs(yb[lo:hi] - by) <= byy); m &= ok
        if not m.any(): return None
        ppm = pp[lo:hi][m]; age = day_c - d[lo:hi][m]; ymm = ym[lo:hi][m]
        if tadj and reg is not None:
            ppm = ppm * np.array([adj(reg, int(x), ym_c) for x in ymm])
        w = np.exp(-age / 365.0) * np.exp(-np.abs(sz[lo:hi][m] - size) / 10.0)
        return ppm, w

    T = df[df["deal_date"] >= TEST_FROM]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    print(f"시험 {len(T):,}건 ({TEST_FROM}~)")
    rows = []
    for r in T.itertuples():
        day_c = r.day - 30; ym_c = int((pd.Timestamp("2020-01-01") + pd.Timedelta(days=int(day_c))).strftime("%Y%m"))
        by = r.build_year if np.isfinite(r.build_year) else None
        out = {"actual": r.price, "size": r.size, "region": r.region, "price": r.price}
        for tadj in (False, True):
            c1 = cands("bld", r.bld, day_c, 730, r.size, 6, reg=r.region, ym_c=ym_c, tadj=tadj)
            c2 = cands("dk", r.dk, day_c, 365, r.size, 8, by, 5, reg=r.region, ym_c=ym_c, tadj=tadj)
            c3 = cands("region", r.region, day_c, 365, r.size, 8, reg=r.region, ym_c=ym_c, tadj=tadj)
            n1 = 0 if c1 is None else len(c1[0]); n2 = 0 if c2 is None else len(c2[0])
            est = {}
            for q in (0.4, 0.5):
                v1 = wq(c1[0], c1[1], q) if c1 else None; v2 = wq(c2[0], c2[1], q) if c2 else None; v3 = wq(c3[0], c3[1], q) if c3 else None
                if n1 >= 3: p, lvl = v1, "건물3+"
                elif n1 >= 1 and v2 is not None: p, lvl = 0.5 * v1 + 0.5 * v2, "건물1~2+동"
                elif n1 >= 1: p, lvl = v1, "건물1~2"
                elif n2 >= 5: p, lvl = v2, "동5+"
                elif v2 is not None: p, lvl = 0.6 * v2 + 0.4 * (v3 if v3 else v2), "동1~4"
                elif v3 is not None: p, lvl = v3, "시군구"
                else: p, lvl = None, "없음"
                est[q] = (None if p is None else p * r.size, lvl)
            out[f"t{int(tadj)}"] = est
        rows.append(out)
    res = []
    for o in rows:
        for tadj in (0, 1):
            for q in (0.4, 0.5):
                e, lvl = o[f"t{tadj}"][q]
                if e: res.append({"tadj": tadj, "q": q, "lvl": lvl, "err": e / o["actual"] - 1, "price": o["actual"], "region": o["region"].split()[0]})
    R = pd.DataFrame(res)
    summ = {}
    for (tadj, q), G in R.groupby(["tadj", "q"]):
        a = G["err"].abs()
        summ[f"시점보정{tadj}_분위{q}"] = {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= .10).mean()) * 100, 1), "within20Pct": round(float((a <= .20).mean()) * 100, 1),
                                       "biasPct": round(float(G["err"].median()) * 100, 2)}
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    best = R[(R["tadj"] == 1) & (R["q"] == 0.5)]
    bylvl = {}
    for lvl, G in best.groupby("lvl"):
        a = G["err"].abs()
        bylvl[lvl] = {"n": int(len(G)), "share": round(len(G) / len(best) * 100, 1), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= .10).mean()) * 100, 1),
                      "p10": round(float(G["err"].quantile(.10)) * 100, 1), "p90": round(float(G["err"].quantile(.90)) * 100, 1), "biasPct": round(float(G["err"].median()) * 100, 2)}
    print("단계별(시점보정·중앙값):", json.dumps(bylvl, ensure_ascii=False, indent=1))
    bands = [(0, 10000, "1억 미만"), (10000, 20000, "1~2억"), (20000, 30000, "2~3억"), (30000, 50000, "3~5억"), (50000, 1e9, "5억+")]
    byb = {}
    for lo, hi, lab in bands:
        G = best[(best["price"] >= lo) & (best["price"] < hi)]
        if len(G) >= 100:
            a = G["err"].abs(); byb[lab] = {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= .10).mean()) * 100, 1), "biasPct": round(float(G["err"].median()) * 100, 2)}
    print("가격대별:", json.dumps(byb, ensure_ascii=False, indent=1))
    byr = {}
    for sd, G in best.groupby("region"):
        a = G["err"].abs(); byr[sd] = {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= .10).mean()) * 100, 1), "biasPct": round(float(G["err"].median()) * 100, 2)}
    print("시도별:", json.dumps(byr, ensure_ascii=False, indent=1))
    json.dump({"summary": summ, "byLevel": bylvl, "byBand": byb, "bySido": byr}, open("backtest-villa.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
