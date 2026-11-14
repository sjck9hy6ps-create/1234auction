"""🏘 같은 건물 거래가 오래될수록 오차가 커지나? + 시점 보정·최신 가중으로 줄일 수 있나(2026-11-14, 측정 전용).
시험 거래마다 '거래 30일 전까지의' 같은 건물(번지) 비교 거래(면적 ±6㎡, 최근 730일)로 예측하고, 가장 최근 비교 거래가 얼마나 오래됐는지(나이)별로 오차를 비교.
방식: ① 지금 방식(㎡당 가격 가중 중앙값, 시점 보정 없음) ② 가장 최근 한 건만 ③ 시점 보정(시군구 월 지수로 비교 거래를 지금 시점으로 옮김, 가중 중앙값) ④ 시점 보정 + 가장 최근 한 건."""
import json
import numpy as np, pandas as pd
df = pd.read_pickle("input/villa-df.pkl"); df = df[df["deal_date"] >= 20190101].copy().reset_index(drop=True)
mi = df.groupby(["region", "ym"])["ppm"].median().apply(np.log).unstack("ym"); mi = mi.T.sort_index().rolling(3, min_periods=1).mean().T
IDX = {rg: (row.dropna().index.values.astype(int), row.dropna().values) for rg, row in mi.iterrows()}
def lidx(rg, ym):
    t = IDX.get(rg)
    if t is None: return np.nan
    k = np.searchsorted(t[0], ym, side="right") - 1
    return t[1][k] if k >= 0 else np.nan
t0 = pd.Timestamp("2020-01-01")
def ym_of(day): d = t0 + pd.Timedelta(days=int(day)); return d.year * 100 + d.month
G = {k: (g["day"].values, g["size"].values, g["ppm"].values, g["ym"].values) for k, g in df.sort_values("day").groupby("bld")}
def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum(); return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])
rows = []
T = df[df["deal_date"] >= 20250101]
for r in T.itertuples():
    g = G.get(r.bld)
    if g is None: continue
    d, s, p, ym = g; cut = r.day - 30
    hi = np.searchsorted(d, cut, side="right"); lo = np.searchsorted(d, cut - 730, side="left")
    if hi <= lo: continue
    m = np.abs(s[lo:hi] - r.size) <= 6
    if not m.any(): continue
    dd = d[lo:hi][m]; ss = s[lo:hi][m]; pp = p[lo:hi][m]; yy = ym[lo:hi][m]
    age = cut - dd; w = np.exp(-age / 365.0) * np.exp(-np.abs(ss - r.size) / 10.0)
    Lnow = lidx(r.region, ym_of(cut)); Lc = np.array([lidx(r.region, y) for y in yy]); okm = ~np.isnan(Lc) & ~np.isnan(Lnow)
    e1 = wmed(pp, w) * r.size; j = int(np.argmin(age)); e2 = pp[j] * r.size
    if okm.any():
        adj = pp * np.exp(Lnow - Lc); adj = np.where(okm, adj, pp); e3 = wmed(adj, w) * r.size; e4 = adj[j] * r.size
    else: e3, e4 = e1, e2
    rows.append((r.price, int(age.min()), len(pp), e1, e2, e3, e4))
R = pd.DataFrame(rows, columns=["y", "age", "n", "e1", "e2", "e3", "e4"])
B = [(0, 90, "최근 거래 3개월 이내"), (91, 180, "3~6개월"), (181, 365, "6~12개월"), (366, 730, "1~2년")]
def st(x, c):
    e = x[c] / x["y"] - 1; a = e.abs()
    return {"중앙오차%": round(float(a.median()) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "쏠림%": round(float(e.median()) * 100, 1)}
res = {"시험 거래(같은 건물 근거 있음)": int(len(R))}
for lo, hi, nm in B:
    X = R[(R["age"] >= lo) & (R["age"] <= hi)]
    if len(X) < 300: continue
    res[nm] = {"건수": int(len(X)), "① 지금(가중 중앙값)": st(X, "e1"), "② 최신 한 건": st(X, "e2"), "③ 시점 보정+가중 중앙": st(X, "e3"), "④ 시점 보정+최신 한 건": st(X, "e4")}
res["전체"] = {"건수": int(len(R)), "① 지금": st(R, "e1"), "② 최신 한 건": st(R, "e2"), "③ 시점 보정+가중": st(R, "e3"), "④ 시점 보정+최신": st(R, "e4")}
for nm, X in (("비교 거래 1건", R[R["n"] == 1]), ("비교 거래 2~3건", R[(R["n"] >= 2) & (R["n"] <= 3)]), ("비교 거래 4건+", R[R["n"] >= 4])):
    if len(X) >= 300: res["건수별 " + nm] = {"건수": int(len(X)), "① 지금": st(X, "e1"), "③ 시점 보정+가중": st(X, "e3")}
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-recency-test.json", "w"), ensure_ascii=False, indent=1)
