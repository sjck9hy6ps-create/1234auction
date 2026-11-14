"""🏘 '같은 건물' 기준 시험(2026-11-14, 측정 전용): 번지(지금) vs 단지명(같은 동 안에서 이름이 같은 건물들 묶음).
예: 현대그린빌라(305-1)1동 · 현대그린빌라(305-6)2동 → 단지명 '현대그린빌라'. 각 시험 거래를 '거래 30일 전까지 자료'로 예측(서버와 같은 비교 규칙: 최근 730일·면적 ±6㎡·연식 ±6년·시간·면적 가중 중앙값).
비교: ① 번지 근거가 있는 거래에 단지명으로 넓히면 좋아지나/나빠지나 ② 번지 근거가 없는데 단지명 근거만 있는 거래에서 단지명 값이 동 값(지금 대신 쓰는 값)보다 정확한가."""
import re, json
import numpy as np, pandas as pd
df = pd.read_pickle("input/villa-df.pkl")
df = df[df["deal_date"] >= 20190101].copy()
def name_key(s):
    t = re.sub(r"\(.*?\)", "", str(s)); t = re.sub(r"\s+", "", t)
    t = re.sub(r"(제?\d+동|[가-힣A-Za-z]동|동)$", "", t)
    t = re.sub(r"\d+차?$", lambda m: m.group(0), t)
    return t
df["nm"] = df["danji"].map(name_key)
bad = df["nm"].str.len() < 3
df["nk"] = np.where(bad, None, df["dk"].astype(str) + "|" + df["nm"])
print("거래", len(df), "단지명 묶음 가능", int((~bad).sum()), "| 번지 건물", df["bld"].nunique(), "단지명 건물", df["nk"].nunique(), flush=True)
df = df.reset_index(drop=True)
def groups(col):
    G = {}
    for k, g in df.groupby(col):
        if k is None: continue
        g = g.sort_values("day"); G[k] = (g["day"].values, g["size"].values, g["ppm"].values, g["by2"].values, g.index.values)
    return G
GB, GN, GD = groups("bld"), groups("nk"), groups("dk")
def comp(G, key, day, size, by, days, stol, yb, exclude_idx):
    g = G.get(key)
    if g is None: return None
    d, s, p, y, ix = g; cut = day - 30
    hi = np.searchsorted(d, cut, side="right"); lo = np.searchsorted(d, cut - days, side="left")
    if hi <= lo: return None
    m = np.abs(s[lo:hi] - size) <= stol
    if yb is not None and np.isfinite(by): m &= (np.isnan(y[lo:hi]) | (np.abs(y[lo:hi] - by) <= yb))
    if not m.any(): return None
    age = cut - d[lo:hi][m]; w = np.exp(-age / 365.0) * np.exp(-np.abs(s[lo:hi][m] - size) / 10.0); pp = p[lo:hi][m]
    o = np.argsort(pp); c = np.cumsum(w[o]) / w.sum(); return float(pp[o][min(np.searchsorted(c, 0.5), len(pp) - 1)] * size), int(m.sum())
T = df[df["deal_date"] >= 20250101]
rows = []
for r in T.itertuples():
    a = comp(GB, r.bld, r.day, r.size, r.by2, 730, 6, 6, None)
    b = comp(GN, r.nk, r.day, r.size, r.by2, 730, 6, 6, None) if r.nk is not None else None
    d = comp(GD, r.dk, r.day, r.size, r.by2, 365, 8, 5, None)
    rows.append((r.deal_date, r.price, a[0] if a else np.nan, a[1] if a else 0, b[0] if b else np.nan, b[1] if b else 0, d[0] if d else np.nan, d[1] if d else 0))
R = pd.DataFrame(rows, columns=["dd", "y", "eA", "nA", "eB", "nB", "eD", "nD"])
def st(x, col):
    e = x[col] / x["y"] - 1; e = e.dropna(); a = e.abs()
    return {"건수": int(len(e)), "중앙오차%": round(float(a.median()) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "쏠림%": round(float(e.median()) * 100, 1), "높게10%+": round(float((e > .1).mean()) * 100, 1)}
res = {}
S1 = R[R["eA"].notna()]; res["① 번지 근거 있는 거래: 번지로 / 단지명으로(번지+같은 이름 다른 번지)"] = {"번지": st(S1, "eA"), "단지명": st(S1.dropna(subset=["eB"]), "eB"), "단지명(건수 같은 행만 비교용 번지)": st(S1.dropna(subset=["eB"]), "eA")}
S2 = R[R["eA"].isna() & R["eB"].notna()]; res["② 번지 근거 없고 단지명만 있는 거래: 단지명 값 vs 동 값"] = {"행수": int(len(S2)), "단지명": st(S2, "eB"), "동(지금 대신 쓰는 값)": st(S2.dropna(subset=["eD"]), "eD"), "동값 비교행의 단지명": st(S2.dropna(subset=["eD"]), "eB")}
res["전체 규모"] = {"시험 거래": int(len(R)), "번지 근거 있음": int(R["eA"].notna().sum()), "번지 없음·단지명 있음": int(len(S2)), "둘 다 없음": int(R["eA"].isna().sum() - len(S2))}
for nm, lo, hi in (("2025상", 20250101, 20250701), ("2025하", 20250701, 20260101), ("2026", 20260101, 99999999)):
    X = R[(R["dd"] >= lo) & (R["dd"] < hi)]; X2 = X[X["eA"].isna() & X["eB"].notna() & X["eD"].notna()]
    res["②기간별 " + nm] = {"행수": int(len(X2)), "단지명": st(X2, "eB"), "동": st(X2, "eD")} if len(X2) else {"행수": 0}
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-danji-test.json", "w"), ensure_ascii=False, indent=1)
