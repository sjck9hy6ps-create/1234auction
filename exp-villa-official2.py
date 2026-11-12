"""
🏛️ 빌라 호별 공시가격 시험(2026-11-13, 측정 전용) - 이 파일의 앞부분은 exp-villa-ideas2.py와 같은 준비 과정.
(원래 설명: ③ 앙상블·④ 쌍 추정 5년 (2026-11-12, 측정 전용) - exp-villa-ideas.py와 같은 시험 거래·같은 6개 시간순 구간·직전 24개월 학습. 기준은 현재 운영(쌍 3년 + 잔차 공유).
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
D = D.merge(df[["bld", "dk", "region", "day", "size", "ppm", "ym", "sg", "bj", "bun", "ji", "floor"]].rename(columns={"size": "sz", "floor": "fl_raw"}), left_on="i", right_index=True, how="left")
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
D["r_pair5"], D["n_pair5"], D["age_pair5"] = pair_est(1825)
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
# ── 공시가격 읽기: {(PNU, 연도): (층, 전용면적, 공시가격[만원])} ──
OP = {}
for ln in open(os.environ.get("OFFICIAL_FILE", "input2/official-price.jsonl"), encoding="utf-8"):
    r = json.loads(ln)
    if not r["units"]: continue
    fl = []; ar = []; pr = []
    for dong, f, ho, a, p in r["units"]:
        try: fl.append(int("".join(ch for ch in str(f) if ch.lstrip("-").isdigit()) or "nan")); ar.append(float(a)); pr.append(float(p) / 10000.0)
        except Exception: pass
    if pr: OP[(r["pnu"], r["year"])] = (np.array(fl, float), np.array(ar), np.array(pr))
print("공시 건물-연도", len(OP), flush=True)
D["pnu"] = D["sg"].astype(str) + D["bj"].astype(str) + "1" + D["bun"].astype(str).str.zfill(4) + D["ji"].fillna("0").astype(str).str.zfill(4)
_dd = _t0 + pd.to_timedelta(D["day"].values, unit="D"); yr = np.where(_dd.month >= 5, _dd.year, _dd.year - 1)   # 그 거래 시점에 이미 공표된 가장 최근 공시(4월 말 공표 → 5월부터 사용)
g_unit = np.full(len(D), np.nan); g_rel = np.full(len(D), np.nan); g_ppm = np.full(len(D), np.nan); g_exact = np.zeros(len(D)); g_n = np.zeros(len(D))
for j, (p, y, sz, fl) in enumerate(zip(D["pnu"].values, yr, D["sz"].values, D["fl_raw"].values)):
    t = OP.get((p, int(y)))
    if t is None: continue
    F, A, Pr = t; near = np.abs(A - sz) <= 3.0
    if not near.any(): continue
    ff = near & (F == fl) if not np.isnan(fl) else near & False
    if ff.any(): k = np.where(ff)[0]; ex = 1
    else: k = np.where(near)[0]; ex = 0
    i0 = k[np.argmin(np.abs(A[k] - sz))]; pp = Pr[i0]
    if not pp > 0: continue
    g_unit[j] = np.log(pp); g_ppm[j] = np.log(pp / A[i0]); g_rel[j] = np.log((Pr / A).mean()) ; g_exact[j] = ex; g_n[j] = len(Pr)
D["g_ratio"] = g_unit - np.log(D["base"].values); D["g_ppm"] = g_ppm; D["g_unit_rel"] = g_ppm - g_rel; D["g_exact"] = g_exact; D["g_n"] = g_n
D["has_g"] = ~np.isnan(g_unit)
print("공시 매칭 비율(2024-05 이후 거래)", round(float(D.loc[D["deal_date"] >= 20240501, "has_g"].mean()), 3), flush=True)
c_pair5 = ["r_pair5", "n_pair5", "age_pair5"]; c_pool = ["dres", "dres_n", "rres", "rres_n"]; c_g = ["g_ratio", "g_ppm", "g_unit_rel", "g_exact", "g_n"]
base_cols = cols1 + c_pair5 + c_pool
FOLDS2 = [(20250101, 20250701), (20250701, 20260101), (20260101, 20260701), (20260701, 99999999)]
names = ["기준(공시 없음)", "공시 추가"]
VARC = {names[0]: base_cols, names[1]: base_cols + c_g}
def pbf(X): return pd.cut(X["base"], PB, labels=PL).astype(str)
acc = {k: [] for k in names}   # 구간별: (표 DataFrame)
for a_, b_ in FOLDS2:
    TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)]
    TR = D[(~D["istest"]) & (D["deal_date"] < a_) & (D["deal_date"] >= mb(a_, 24))].sort_values("deal_date")
    print(a_, "시험", len(TE), "(공시 연결", int(TE["has_g"].sum()), ") 학습", len(TR), flush=True)
    if len(TE) < 300 or len(TR) < 3000: continue
    k80 = int(len(TR) * 0.8)
    for nm, cols in VARC.items():
        pt = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols], TR["y"])
        FIT, CAL = TR.iloc[:k80], TR.iloc[k80:]
        mq = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, **P).fit(FIT[cols], FIT["y"]) for q in (0.1, 0.25)}
        stc = (CAL["lvl"].astype(str) + "|" + pbf(CAL)).values; stt = (TE["lvl"].astype(str) + "|" + pbf(TE)).values
        out = TE[["lvl", "pb", "base", "has_g"]].copy(); out["y"] = TE["y"].values
        out["e"] = TE["base"].values * np.exp(pt.predict(TE[cols])) / TE["actual"].values - 1
        for q, lev, col in ((0.25, 0.75, "q25"), (0.1, 0.9, "q10")):
            sc = mq[q].predict(CAL[cols]) - CAL["y"].values; allv = float(np.quantile(sc, lev)); cm = {}
            for kk in np.unique(stc):
                mk_ = stc == kk
                if mk_.sum() >= 150: cm[kk] = float(np.quantile(sc[mk_], lev))
            out[col] = mq[q].predict(TE[cols]) - np.array([cm.get(k_, allv) for k_ in stt])
        out["hit25"] = out["y"].values >= out["q25"].values; out["hit10"] = out["y"].values >= out["q10"].values   # 실제가 하위값 이상이면 '맞힘'
        out["cand"] = CAND(TE).values; acc[nm].append(out); print(a_, nm, pstat(out["e"].values), "적중 25%선", round(float(out["hit25"].mean()) * 100, 1), "10%선", round(float(out["hit10"].mean()) * 100, 1), flush=True)
def summ(T):
    return {"건수": int(len(T)), **{k: v for k, v in pstat(T["e"].values).items() if k != "n"}, "하위25% 적중(목표75)": round(float(T["hit25"].mean()) * 100, 1), "하위10% 적중(목표90)": round(float(T["hit10"].mean()) * 100, 1),
            "높게 예상 10%+ %": round(float((T["e"] > .10).mean()) * 100, 1), "낮게 예상 10%+ %": round(float((T["e"] < -.10).mean()) * 100, 1)}
res = {}
for nm in names:
    if not acc[nm]: continue
    T = pd.concat(acc[nm]); res[nm] = {"전체": summ(T), "후보만": summ(T[T["cand"]]), "공시 연결된 것만": summ(T[T["has_g"]]),
        "구간별": [{"오차%": pstat(o["e"].values)["오차%"], "25%선": round(float(o["hit25"].mean()) * 100, 1), "10%선": round(float(o["hit10"].mean()) * 100, 1)} for o in acc[nm]],
        "단계별": {l: {"오차%": pstat(G["e"].values)["오차%"], "25%선": round(float(G["hit25"].mean()) * 100, 1), "10%선": round(float(G["hit10"].mean()) * 100, 1), "n": int(len(G))} for l, G in T.groupby("lvl") if len(G) >= 150}}
    print(nm, json.dumps(res[nm], ensure_ascii=False), flush=True)
json.dump(res, open("villa-official-test2.json", "w"), ensure_ascii=False, indent=1)
