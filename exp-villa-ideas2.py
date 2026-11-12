"""
🧪 빌라 시세 개선 시도 ③ 앙상블·④ 쌍 추정 5년 (2026-11-12, 측정 전용) - exp-villa-ideas.py와 같은 시험 거래·같은 6개 시간순 구간·직전 24개월 학습. 기준은 현재 운영(쌍 3년 + 잔차 공유).
"""
import glob, json, os
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from merge_cols import cols1
P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
FOLDS = [(20240101, 20240701), (20240701, 20250101), (20250101, 20250701), (20250701, 20260101), (20260101, 20260701), (20260701, 99999999)]
PB = [0, 8000, 15000, 1e9]; PL = ["8천만 미만", "8천~1.5억", "1.5억 이상"]
df = pd.read_pickle(os.environ.get("DF_FILE", "input/villa-df.pkl"))
files = sorted(glob.glob(os.environ.get("SHARD_GLOB", "shards/**/feat-shard-*.pkl"), recursive=True))
D = pd.concat([pd.read_pickle(f) for f in files], ignore_index=True); D = D[D["deal_date"] >= 20220101].copy().reset_index(drop=True)
print(f"거래 {len(df):,}, 특징 {len(D):,}행(2022~)", flush=True)
D = D.merge(df[["bld", "dk", "region", "day", "size", "ppm", "ym"]].rename(columns={"size": "sz"}), left_on="i", right_index=True, how="left")
D["pb"] = pd.cut(D["base"], PB, labels=PL).astype(str)
# ── 시군구 월별 가격 지수(앱 estimate와 같은 방식: 월 중앙값 로그, 3개월 이동평균) ──
mi = df.groupby(["region", "ym"])["ppm"].median().apply(np.log).unstack("ym"); mi = mi.T.sort_index().rolling(3, min_periods=1).mean().T
IDX = {}
for rg, row in mi.iterrows():
    r = row.dropna(); IDX[rg] = (r.index.values.astype(int), r.values)
def lidx(rg, ym):
    t = IDX.get(rg)
    if t is None: return np.nan
    k = np.searchsorted(t[0], ym, side="right") - 1
    return t[1][k] if k >= 0 else np.nan
def ym_of_day(d): return (pd.Timestamp("2020-01-01") + pd.to_timedelta(d, unit="D"))
bg = {k: (g["day"].values, g["size"].values, g["ppm"].values, g["ym"].values) for k, g in df.groupby("bld")}
def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum(); return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])
# ── 반복매매 쌍 추정(창 길이를 바꿔 계산) ──
_t0 = pd.Timestamp("2020-01-01"); _dd = _t0 + pd.to_timedelta(D["day"].values - 30, unit="D"); cutym = (_dd.year * 100 + _dd.month).values
def pair_est(win):
    est_p = np.full(len(D), np.nan); n_p = np.zeros(len(D)); age_p = np.full(len(D), np.nan)
    for j, (b, rg, day, sz) in enumerate(zip(D["bld"].values, D["region"].values, D["day"].values, D["sz"].values)):
        g = bg.get(b)
        if g is None: continue
        d, s, pp, ym = g; cut = day - 30
        lo = np.searchsorted(d, cut - win, side="left"); hi = np.searchsorted(d, cut, side="right")
        if hi <= lo: continue
        m = np.abs(s[lo:hi] - sz) <= 6
        if not m.any(): continue
        L_now = lidx(rg, cutym[j])
        if np.isnan(L_now): continue
        adj = np.log(pp[lo:hi][m]) + (L_now - np.array([lidx(rg, y) for y in ym[lo:hi][m]]))
        ok = ~np.isnan(adj)
        if not ok.any(): continue
        age = cut - d[lo:hi][m][ok]; w = np.exp(-age / 540.0) * np.exp(-np.abs(s[lo:hi][m][ok] - sz) / 8.0)
        est_p[j] = np.exp(wmed(adj[ok], w)) * sz; n_p[j] = int(ok.sum()); age_p[j] = float(age.min())
    return np.log(est_p / D["base"].values), n_p, age_p
D["r_pair"], D["n_pair"], D["age_pair"] = pair_est(1095)
D["r_pair5"], D["n_pair5"], D["age_pair5"] = pair_est(1825)
print("쌍 추정 채움(시험) 3년", round(float(D.loc[D["istest"], "r_pair"].notna().mean()), 3), "5년", round(float(D.loc[D["istest"], "r_pair5"].notna().mean()), 3), flush=True)
# ── 시도 2: 동·시군구 잔차 부분 공유 ──
def icc(key):
    S = D[["y", key]].dropna(); g = S.groupby(key)["y"]; n = g.size(); m = g.mean(); N = len(S); k = len(n)
    msb = (n * (m - S["y"].mean()) ** 2).sum() / (k - 1); msw = ((S["y"] - S[key].map(m)) ** 2).sum() / (N - k); n0 = (N - (n ** 2).sum() / N) / (k - 1)
    var_b = max((msb - msw) / n0, 1e-6); return msw / var_b   # k = 개별 잔차 분산 ÷ 그룹 간 분산 (이만큼의 거래 수가 모이면 반반 반영)
K_DONG, K_REG = icc("dk"), icc("region"); print("부분 공유 k(동, 시군구)", round(K_DONG, 1), round(K_REG, 1), flush=True)
def nbr(key, win, K):
    out_m = np.full(len(D), np.nan); out_n = np.zeros(len(D))
    for _, G in D.groupby(key):
        o = np.argsort(G["day"].values); idx = G.index.values[o]; d = G["day"].values[o]; y = G["y"].values[o]
        for a, j in enumerate(idx):
            lo = np.searchsorted(d, d[a] - 30 - win, side="left"); hi = np.searchsorted(d, d[a] - 30, side="right")
            yy = y[lo:hi]; yy = yy[~np.isnan(yy)]
            if len(yy): out_n[j] = len(yy); out_m[j] = yy.sum() / (len(yy) + K)
    return out_m, out_n
D["dres"], D["dres_n"] = nbr("dk", 365, K_DONG); D["rres"], D["rres_n"] = nbr("region", 180, K_REG)
print("잔차 공유 채움 비율", round(float(D["dres"].notna().mean()), 3), flush=True)
def mb(d, k):
    t = (d // 10000) * 12 + ((d // 100) % 100 - 1) - k; return (t // 12) * 10000 + (t % 12 + 1) * 100 + 1
def pstat(e):
    a = np.abs(e); return {"n": int(len(e)), "오차%": round(float(np.median(a)) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 1)}
CAND = lambda X: X["lvl"].isin(["건물3+", "건물1~2+동", "동5+"]) & (X["base"] >= 8000)

c_pair = ["r_pair", "n_pair", "age_pair"]; c_pair5 = ["r_pair5", "n_pair5", "age_pair5"]; c_pool = ["dres", "dres_n", "rres", "rres_n"]
from sklearn.ensemble import ExtraTreesRegressor
def fill(X): return X.fillna(-999.0).values
VARS = {"B 현재(3년 쌍+잔차 공유)": cols1 + c_pair + c_pool, "P5 쌍 5년으로 교체": cols1 + c_pair5 + c_pool, "P35 쌍 3년+5년 모두": cols1 + c_pair + c_pair5 + c_pool}
ENS = ["E1 HGB 5개 평균(씨앗·열 샘플 다름)", "E2 HGB+제곱손실 HGB+ExtraTrees 평균", "E3 HGB 깊이 3·5·8 평균", "E4 E2의 중앙값"]
names = list(VARS) + ENS
acc = {k: [] for k in names}; accD = {k: [] for k in names}
for a_, b_ in FOLDS:
    TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)]; TR = D[(~D["istest"]) & (D["deal_date"] < a_) & (D["deal_date"] >= mb(a_, 24))]
    if len(TE) < 300 or len(TR) < 3000: continue
    for nm, cols in VARS.items():
        m = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols], TR["y"]); e = TE["base"].values * np.exp(m.predict(TE[cols])) / TE["actual"].values - 1
        acc[nm].append(e); accD[nm].append(TE[["lvl", "pb", "base"]].assign(e=e, cand=CAND(TE).values)); print(a_, nm, pstat(e), flush=True)
    cols = VARS["B 현재(3년 쌍+잔차 공유)"]; Xtr, Xte = TR[cols], TE[cols]; ytr = TR["y"].values
    def put(nm, pred):
        e = TE["base"].values * np.exp(pred) / TE["actual"].values - 1
        acc[nm].append(e); accD[nm].append(TE[["lvl", "pb", "base"]].assign(e=e, cand=CAND(TE).values)); print(a_, nm, pstat(e), flush=True)
    p_abs = [HistGradientBoostingRegressor(loss="absolute_error", **dict(P, random_state=s_, max_features=0.8)).fit(Xtr, ytr).predict(Xte) for s_ in range(5)]
    put(ENS[0], np.mean(p_abs, axis=0))
    p_sq = HistGradientBoostingRegressor(loss="squared_error", **P).fit(Xtr, ytr).predict(Xte)
    et = ExtraTreesRegressor(n_estimators=150, min_samples_leaf=25, max_features=0.6, n_jobs=-1, random_state=1).fit(fill(Xtr), ytr).predict(fill(Xte))
    p0 = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(Xtr, ytr).predict(Xte)
    put(ENS[1], np.mean([p0, p_sq, et], axis=0)); put(ENS[3], np.median([p0, p_sq, et], axis=0))
    p3 = HistGradientBoostingRegressor(loss="absolute_error", **dict(P, max_depth=3, max_iter=400)).fit(Xtr, ytr).predict(Xte)
    p8 = HistGradientBoostingRegressor(loss="absolute_error", **dict(P, max_depth=8, min_samples_leaf=100)).fit(Xtr, ytr).predict(Xte)
    put(ENS[2], np.mean([p3, p0, p8], axis=0))
res = {}
for nm in names:
    E = np.concatenate(acc[nm]); T = pd.concat(accD[nm])
    res[nm] = {"전체": pstat(E), "후보만": pstat(T.loc[T["cand"], "e"].values), "단계별 오차%": {l: pstat(G["e"].values)["오차%"] for l, G in T.groupby("lvl") if len(G) >= 200},
               "높게 예상 10%+ %": round(float((E > .10).mean()) * 100, 1), "낮게 예상 10%+ %": round(float((E < -.10).mean()) * 100, 1)}
    print(nm, json.dumps(res[nm], ensure_ascii=False), flush=True)
json.dump(res, open("villa-ideas2.json", "w"), ensure_ascii=False, indent=1)
