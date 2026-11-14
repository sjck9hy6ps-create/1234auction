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
D = D.merge(df[["bld", "dk", "region", "day", "size", "ppm", "ym", "sg", "bj", "bun", "ji", "floor", "lat", "lon", "danji"]].rename(columns={"size": "sz", "floor": "fl_raw"}), left_on="i", right_index=True, how="left")
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
# ── 생활권 반복매매 지수(2026-11-14): 같은 건물 같은 면적대 두 거래 사이 ㎡당 가격 변화로 '주변 반경'의 연 변화율을 구함 ──
from scipy.spatial import cKDTree
KM_ = 111.0 * np.cos(np.radians(37.5))
d0 = df[df["lat"].notna()]
PA = []
for b_, g_ in d0.sort_values("day").groupby("bld"):
    if len(g_) < 2: continue
    dd_ = g_["day"].values; ss_ = g_["size"].values; pp_ = g_["ppm"].values; la_ = g_["lat"].values[0]; lo_ = g_["lon"].values[0]
    for i_ in range(1, len(g_)):
        for j_ in range(i_ - 1, max(-1, i_ - 6), -1):
            if abs(ss_[i_] - ss_[j_]) <= 6 and dd_[i_] - dd_[j_] >= 90:
                PA.append((dd_[i_], dd_[j_], np.log(pp_[i_] / pp_[j_]), la_, lo_)); break
PR = pd.DataFrame(PA, columns=["t2", "t1", "dl", "la", "lo"]); PR = PR[PR["dl"].abs() < 1.0].reset_index(drop=True)
PR["dy"] = (PR["t2"] - PR["t1"]) / 365.0; PR["rate"] = PR["dl"] / PR["dy"]
PTREE = cKDTree(np.c_[PR["la"].values * 111.0, PR["lo"].values * KM_]); PT2 = PR["t2"].values; PRATE = PR["rate"].values; PDY = PR["dy"].values
print("반복매매 쌍", len(PR), flush=True)
def la_drift(la, lo, cut, rads=(0.5, 1.0, 2.0, 5.0), min_n=8, win=730):
    for R_ in rads:
        ix = np.array(PTREE.query_ball_point([la * 111.0, lo * KM_], R_), dtype=int)
        if len(ix) == 0: continue
        ix = ix[(PT2[ix] <= cut) & (PT2[ix] >= cut - win)]
        if len(ix) >= min_n:
            r_ = PRATE[ix]; w_ = np.minimum(PDY[ix], 1.5); o_ = np.argsort(r_); c_ = np.cumsum(w_[o_]) / w_.sum(); return float(r_[o_][min(np.searchsorted(c_, 0.5), len(r_) - 1)])
    return 0.0
def pair_est(win, mode="region"):
    est_p = np.full(len(D), np.nan); n_p = np.zeros(len(D)); age_p = np.full(len(D), np.nan)
    LAT = D["lat"].values; LON = D["lon"].values
    for j, (b, rg, day, sz) in enumerate(zip(D["bld"].values, D["region"].values, D["day"].values, D["sz"].values)):
        g = bg.get(b)
        if g is None: continue
        d, s, pp, ym = g; cut = day - 30
        lo = np.searchsorted(d, cut - win, side="left"); hi = np.searchsorted(d, cut, side="right")
        if hi <= lo: continue
        m = np.abs(s[lo:hi] - sz) <= 6
        if not m.any(): continue
        age = cut - d[lo:hi][m]
        if mode == "la" and not np.isnan(LAT[j]):
            adj = np.log(pp[lo:hi][m]) + la_drift(LAT[j], LON[j], cut) * age / 365.0; ok = np.ones(len(adj), bool)
        else:
            L_now = lidx(rg, cutym[j])
            if np.isnan(L_now): continue
            adj = np.log(pp[lo:hi][m]) + (L_now - np.array([lidx(rg, y) for y in ym[lo:hi][m]]))
            ok = ~np.isnan(adj)
        if not ok.any(): continue
        age = age[ok]; w = np.exp(-age / 540.0) * np.exp(-np.abs(s[lo:hi][m][ok] - sz) / 8.0)
        est_p[j] = np.exp(wmed(adj[ok], w)) * sz; n_p[j] = int(ok.sum()); age_p[j] = float(age.min())
    return np.log(est_p / D["base"].values), n_p, age_p
D["r_pair5"], D["n_pair5"], D["age_pair5"] = pair_est(1825, "la")   # 현재 운영(2026-11-14 생활권 지수)
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

# ── 단지명 근거(2026-11-14 시험): 같은 동 안에서 이름이 같은 '다른 번지' 건물(예: 현대그린빌라 1동·2동)의 거래로 낸 추정 ──
import re as _re
def _nk(sx):
    t = _re.sub(r"\(.*?\)", "", str(sx)); t = _re.sub(r"\s+", "", t); t = _re.sub(r"(제?\d+동|[가-힣A-Za-z]동|동)$", "", t); return t
df["_nm"] = df["danji"].map(_nk); df["_nk"] = np.where(df["_nm"].str.len() < 3, None, df["dk"].astype(str) + "|" + df["_nm"])
NG = {k: (g["day"].values, g["size"].values, g["ppm"].values, g["bld"].values) for k, g in df[df["_nk"].notna()].sort_values("day").groupby("_nk")}
D["_nk"] = df["_nk"].reindex(D["i"].values).values
def nm_est():
    est = np.full(len(D), np.nan); n_ = np.zeros(len(D)); age_ = np.full(len(D), np.nan)
    for j, (k, b, day, sz) in enumerate(zip(D["_nk"].values, D["bld"].values, D["day"].values, D["sz"].values)):
        if k is None or k != k: continue
        g = NG.get(k)
        if g is None: continue
        d, s_, pp, bb = g; cut = day - 30
        lo = np.searchsorted(d, cut - 730, side="left"); hi = np.searchsorted(d, cut, side="right")
        if hi <= lo: continue
        m = (np.abs(s_[lo:hi] - sz) <= 6) & (bb[lo:hi] != b)
        if not m.any(): continue
        age = cut - d[lo:hi][m]; w = np.exp(-age / 365.0) * np.exp(-np.abs(s_[lo:hi][m] - sz) / 10.0)
        est[j] = wmed(pp[lo:hi][m], w) * sz; n_[j] = int(m.sum()); age_[j] = float(age.min())
    return np.log(est / D["base"].values), n_, age_
D["r_nm"], D["n_nm"], D["age_nm"] = nm_est(); c_nm = ["r_nm", "n_nm", "age_nm"]; D["_sub"] = ((D["n_pair5"] == 0) | D["n_pair5"].isna()) & D["r_nm"].notna()   # 같은 번지 근거 없고 단지명(다른 번지) 근거만 있는 거래
print("단지명 근거(다른 번지) 있는 거래 비율", round(float(D["r_nm"].notna().mean()) * 100, 1), "%", flush=True)
c_pair5 = ["r_pair5", "n_pair5", "age_pair5"]; c_pool = ["dres", "dres_n", "rres", "rres_n"]; c_g = ["g_ratio", "g_ppm", "g_unit_rel", "g_exact", "g_n"]
base_cols = cols1 + c_pair5 + c_pool
# 2026-11-13 롤링 검증: 분기(3개월)마다 '그 직전 24개월 거래로만 학습' → 그 분기 모든 거래로 시험. 현재 운영 계산식(쌍 5년·잔차 공유·공시가격·하위값 보정)
def qstart(y, q): return y * 10000 + (3 * q + 1) * 100 + 1
FOLDS3 = []
for y in (2024, 2025, 2026):
    for q in range(4):
        a_ = qstart(y, q); b_ = qstart(y + (1 if q == 3 else 0), (q + 1) % 4)
        if a_ <= 20261001: FOLDS3.append((a_, b_))
def pbf(X): return pd.cut(X["base"], PB, labels=PL).astype(str)
def run_variant(DD, tag, extra=()):
    parts = []
    for a_, b_ in FOLDS3:
        TE = DD[(DD["deal_date"] >= a_) & (DD["deal_date"] < b_)]
        TR = DD[(DD["deal_date"] < a_) & (DD["deal_date"] >= mb(a_, 24))].sort_values("deal_date")
        if len(TE) < 500 or len(TR) < 5000: print(a_, "건너뜀", len(TE), len(TR), flush=True); continue
        allc = base_cols + c_g + list(extra)
        cols = [c for c in allc if TR[c].nunique(dropna=True) > 1]   # 학습 구간에 값이 하나뿐인 열(2024-05 전에는 공시가 없음)은 제외
        k80 = int(len(TR) * 0.8); FIT, CAL = TR.iloc[:k80], TR.iloc[k80:]
        colq = [c for c in cols if FIT[c].nunique(dropna=True) > 1]   # 하위값 모델은 앞 80%만 학습하므로 거기서도 한 값뿐인 열 제외
        pt = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols], TR["y"])
        mq = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, **P).fit(FIT[colq], FIT["y"]) for q in (0.1, 0.25)}
        stc = (CAL["lvl"].astype(str) + "|" + pbf(CAL)).values; stt = (TE["lvl"].astype(str) + "|" + pbf(TE)).values
        out = TE[["lvl", "pb", "base", "has_g", "deal_date", "_sub"]].copy(); out["y"] = TE["y"].values; out["fold"] = a_
        out["e"] = TE["base"].values * np.exp(pt.predict(TE[cols])) / TE["actual"].values - 1
        out["e_base"] = TE["base"].values / TE["actual"].values - 1   # 모델 보정 전 '기준 추정'(비교용)
        for q, lev, col in ((0.25, 0.75, "q25"), (0.1, 0.9, "q10")):
            sc = mq[q].predict(CAL[colq]) - CAL["y"].values; allv = float(np.quantile(sc, lev)); cm = {}
            for kk in np.unique(stc):
                mk_ = stc == kk
                if mk_.sum() >= 150: cm[kk] = float(np.quantile(sc[mk_], lev))
            out[col] = mq[q].predict(TE[colq]) - np.array([cm.get(k_, allv) for k_ in stt])
        out["hit25"] = out["y"].values >= out["q25"].values; out["hit10"] = out["y"].values >= out["q10"].values; out["cand"] = CAND(TE).values
        parts.append(out); print(tag, a_, "시험", len(TE), "학습", len(TR), pstat(out["e"].values), "적중", round(float(out["hit25"].mean()) * 100, 1), round(float(out["hit10"].mean()) * 100, 1), flush=True)
    return pd.concat(parts)

def summ(X, col="e"):
    return {"건수": int(len(X)), **{k: v for k, v in pstat(X[col].values).items() if k != "n"}, "하위25% 적중(목표75)": round(float(X["hit25"].mean()) * 100, 1), "하위10% 적중(목표90)": round(float(X["hit10"].mean()) * 100, 1),
            "높게 예상 10%+ %": round(float((X[col] > .10).mean()) * 100, 1), "낮게 예상 10%+ %": round(float((X[col] < -.10).mean()) * 100, 1)}
TA = run_variant(D, "A 현재(생활권 지수)"); TB = run_variant(D, "B +단지명 근거", c_nm)
res = {}
for nm_, T in (("A 현재", TA), ("B +단지명 근거", TB)):
    T = T.copy(); res[nm_] = {"전체": summ(T), "후보만": summ(T[T["cand"]]), "번지 근거 없고 단지명 근거만 있는 거래": summ(T[T["_sub"]]) if T["_sub"].sum() >= 300 else {"건수": int(T["_sub"].sum())}, "분기별": {str(f): summ(G) for f, G in T.groupby("fold")},
               "단계별": {l: summ(G) for l, G in T.groupby("lvl") if len(G) >= 300}, "가격대별": {l: summ(G) for l, G in T.groupby("pb") if len(G) >= 300}}
# 번지 근거 없고 단지명 근거만 있는 거래(전체의 약 9%)만 따로
key = D[["i"]].assign(has_nm=D["r_nm"].notna().values, no_bld=(D["n_pair5"] == 0).values).set_index("i") if False else None
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-roll-nm-test.json", "w"), ensure_ascii=False, indent=1)
