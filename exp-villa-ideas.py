"""
🧪 빌라 시세 개선 시도 1·2·3·5 (2026-11-11, 측정 전용) - 객관 자료(실거래)만 사용, 같은 시험 거래(약 2.4만 건)·같은 6개 시간순 구간·직전 24개월 학습(운영과 같은 설정)
1. 같은 건물 거래 쌍(반복매매) 추정: 같은 건물·비슷한 면적의 이전 거래가를 시군구 가격 지수 변화로 시점 보정해 이번 거래가를 추정 → 입력으로 추가
2. 지역 간 부분 공유(계층 방식): 같은 동·시군구의 최근 1년 '기준값 대비 실제' 잔차 평균을 거래 수에 따라 0쪽으로 줄여(거래 적을수록 주변 평균에 가깝게) 입력으로 추가
3. 불확실성 구간 보정(conformal): 학습 구간 끝 20%로 근거 단계×가격대별 하위 25%·10% 값을 목표 포함률(75%·90%)에 맞춰 보정
5. 후보 가중: 후보(근거 단계 건물3+/건물1~2+동/동5+ 이면서 기준가 8천만 원 이상)를 3배 가중해 학습, 후보 오차를 비교
입력: villa-df.pkl, 조각 feat-shard-*.pkl(각 거래의 30일 전 기준 입력). 외부 호출 없음.
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
# ── 시도 1: 반복매매 쌍 추정 ──
est_p = np.full(len(D), np.nan); n_p = np.zeros(len(D)); age_p = np.full(len(D), np.nan)
cutym = ((pd.Timestamp("2020-01-01") + pd.to_timedelta(D["day"].values - 30, unit="D")).year * 100 + (pd.Timestamp("2020-01-01") + pd.to_timedelta(D["day"].values - 30, unit="D")).month).values
for j, (b, rg, day, sz) in enumerate(zip(D["bld"].values, D["region"].values, D["day"].values, D["sz"].values)):
    g = bg.get(b)
    if g is None: continue
    d, s, pp, ym = g; cut = day - 30
    lo = np.searchsorted(d, cut - 1095, side="left"); hi = np.searchsorted(d, cut, side="right")
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
D["r_pair"] = np.log(est_p / D["base"]); D["n_pair"] = n_p; D["age_pair"] = age_p
print("쌍 추정 채움 비율", round(float(D["r_pair"].notna().mean()), 3), "시험 구간", round(float(D.loc[D["istest"], "r_pair"].notna().mean()), 3), flush=True)
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
c_pair = ["r_pair", "n_pair", "age_pair"]; c_pool = ["dres", "dres_n", "rres", "rres_n"]
def mb(d, k):
    t = (d // 10000) * 12 + ((d // 100) % 100 - 1) - k; return (t // 12) * 10000 + (t % 12 + 1) * 100 + 1
def pstat(e):
    a = np.abs(e); return {"n": int(len(e)), "오차%": round(float(np.median(a)) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 1)}
CAND = lambda X: X["lvl"].isin(["건물3+", "건물1~2+동", "동5+"]) & (X["base"] >= 8000)
acc = {k: [] for k in ("M0", "M1", "M2", "M12", "M5")}; accD = {k: [] for k in acc}
cq = {"기준": [], "보정": []}
for a_, b_ in FOLDS:
    TE = D[D["istest"] & (D["deal_date"] >= a_) & (D["deal_date"] < b_)]; TR = D[(~D["istest"]) & (D["deal_date"] < a_) & (D["deal_date"] >= mb(a_, 24))]
    if len(TE) < 300 or len(TR) < 3000: continue
    def fit(cols, w=None, T=TR):
        return HistGradientBoostingRegressor(loss="absolute_error", **P).fit(T[cols], T["y"], sample_weight=w)
    for nm, cols, w in (("M0", cols1, None), ("M1", cols1 + c_pair, None), ("M2", cols1 + c_pool, None), ("M12", cols1 + c_pair + c_pool, None), ("M5", cols1, np.where(CAND(TR), 3.0, 1.0))):
        m = fit(cols, w); e = TE["base"].values * np.exp(m.predict(TE[cols])) / TE["actual"].values - 1
        acc[nm].append(e); accD[nm].append(TE[["lvl", "pb", "base"]].assign(e=e, cand=CAND(TE).values))
        print(a_, nm, pstat(e), flush=True)
    # ── 시도 3: conformal ──
    TRs = TR.sort_values("deal_date"); k = int(len(TRs) * 0.8); FIT, CAL = TRs.iloc[:k], TRs.iloc[k:]
    ptA = fit(cols1); q25A = HistGradientBoostingRegressor(loss="quantile", quantile=0.25, **P).fit(TR[cols1], TR["y"]); q10A = HistGradientBoostingRegressor(loss="quantile", quantile=0.10, **P).fit(TR[cols1], TR["y"])
    ptF = fit(cols1, None, FIT); q25F = HistGradientBoostingRegressor(loss="quantile", quantile=0.25, **P).fit(FIT[cols1], FIT["y"]); q10F = HistGradientBoostingRegressor(loss="quantile", quantile=0.10, **P).fit(FIT[cols1], FIT["y"])
    def adj(q_pred_cal, y_cal, strat_cal, q_pred_te, strat_te, level):
        out = q_pred_te.copy(); allc = np.quantile(q_pred_cal - y_cal, level)
        for s in np.unique(strat_te):
            mc = strat_cal == s; mt = strat_te == s
            c = np.quantile((q_pred_cal - y_cal)[mc], level) if mc.sum() >= 150 else allc
            out[mt] = q_pred_te[mt] - c
        return out
    st_cal = (CAL["lvl"] + "|" + CAL["pb"]).values; st_te = (TE["lvl"] + "|" + TE["pb"]).values
    for nm, (pt, q25, q10) in (("기준", (ptA.predict(TE[cols1]), q25A.predict(TE[cols1]), q10A.predict(TE[cols1]))),
                               ("보정", (ptF.predict(TE[cols1]), adj(q25F.predict(CAL[cols1]), CAL["y"].values, st_cal, q25F.predict(TE[cols1]), st_te, 0.75), adj(q10F.predict(CAL[cols1]), CAL["y"].values, st_cal, q10F.predict(TE[cols1]), st_te, 0.90)))):
        y = TE["y"].values
        cq[nm].append(pd.DataFrame({"lvl": TE["lvl"].values, "pb": TE["pb"].values, "c25": (y >= q25).astype(float), "c10": (y >= q10).astype(float), "w25": np.exp(pt - q25) - 1, "w10": np.exp(pt - q10) - 1}))
    print(a_, "conformal 완료", flush=True)
res = {"쌍 추정 채움(시험)": round(float(D.loc[D["istest"], "r_pair"].notna().mean()), 3), "부분 공유 k": [round(K_DONG, 1), round(K_REG, 1)]}
names = {"M0": "기준(현재 운영 설정)", "M1": "1. + 같은 건물 거래 쌍 추정", "M2": "2. + 동·시군구 잔차 부분 공유", "M12": "1+2 함께", "M5": "5. 후보 가중 3배"}
for k, nm in names.items():
    E = np.concatenate(acc[k]); T = pd.concat(accD[k])
    res[nm] = {"전체": pstat(E), "후보만": pstat(T.loc[T["cand"], "e"].values), "단계별 오차%": {l: pstat(G["e"].values)["오차%"] for l, G in T.groupby("lvl") if len(G) >= 200}, "가격대별 오차%": {l: pstat(G["e"].values)["오차%"] for l, G in T.groupby("pb")}}
    print(nm, res[nm]["전체"], "후보", res[nm]["후보만"], flush=True)
cres = {}
for nm in cq:
    Q = pd.concat(cq[nm]); st = Q.groupby(["lvl", "pb"]).agg(n=("c25", "size"), c25=("c25", "mean"), c10=("c10", "mean"), w25=("w25", "median"), w10=("w10", "median")); st = st[st["n"] >= 200]
    cres[nm] = {"전체": {"25% 값 포함률%": round(float(Q["c25"].mean()) * 100, 1), "10% 값 포함률%": round(float(Q["c10"].mean()) * 100, 1), "25% 여유폭%": round(float(Q["w25"].median()) * 100, 1), "10% 여유폭%": round(float(Q["w10"].median()) * 100, 1)},
                "단계×가격대 포함률 목표와의 평균 어긋남(%p) 25%/10%": [round(float((np.abs(st["c25"] - 0.75) * st["n"]).sum() / st["n"].sum()) * 100, 2), round(float((np.abs(st["c10"] - 0.90) * st["n"]).sum() / st["n"].sum()) * 100, 2)],
                "가장 어긋난 5곳(25% 값)": {f"{i[0]}|{i[1]}": [round(float(r["c25"]) * 100, 1), int(r["n"])] for i, r in st.assign(d=np.abs(st["c25"] - 0.75)).sort_values("d", ascending=False).head(5).iterrows()}}
    print("conformal", nm, json.dumps(cres[nm], ensure_ascii=False), flush=True)
res["3. conformal 구간 보정"] = cres
json.dump(res, open("villa-ideas.json", "w"), ensure_ascii=False, indent=1)
