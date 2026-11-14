"""🏘 생활권 반복매매 지수로 시점 보정(2026-11-14, 측정 전용) - 사용자 원칙: 모든 빌라 시험의 가장 중요한 것은 생활권 비교.
앞 시험: 같은 건물 근거가 있어도 가장 최근 거래가 오래될수록 오차가 커지고(6.3→11.2%), 시군구 월 중앙값 지수로 시점을 옮기면 오히려 나빠짐(8.57→9.79%).
여기서는 '이 건물 주변 생활권(반경)의 반복매매'(같은 건물 같은 면적대의 두 거래 사이 ㎡당 가격 변화)로 지금 시점까지의 연 변화율을 구해 비교 거래를 옮김.
 - 반경 0.5/1/2/5km 중 반복매매 쌍이 충분한(8쌍+) 가장 가까운 생활권을 씀(적응형), 고정 반경 1km도 비교. 시험 거래 30일 전까지의 자료만 사용."""
import json
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
df = pd.read_pickle("input/villa-df.pkl"); df = df[df["deal_date"] >= 20190101].copy().reset_index(drop=True)
d0 = df[df["lat"].notna()].copy()
KM = 111.0 * np.cos(np.radians(37.5))
print("거래", len(df), "좌표 있음", len(d0), flush=True)
# 반복매매 쌍: 같은 건물에서 면적 ±6㎡ 이내인 연속 거래(시간순 이웃) - 기록: 뒤 거래일, 앞 거래일, ㎡당 가격 로그 변화, 좌표
PA = []
for b, g in d0.sort_values("day").groupby("bld"):
    if len(g) < 2: continue
    d = g["day"].values; s = g["size"].values; p = g["ppm"].values; la = g["lat"].values[0]; lo = g["lon"].values[0]
    for i in range(1, len(g)):
        for j in range(i - 1, max(-1, i - 6), -1):
            if abs(s[i] - s[j]) <= 6 and d[i] - d[j] >= 90:
                PA.append((d[i], d[j], np.log(p[i] / p[j]), la, lo)); break
P = pd.DataFrame(PA, columns=["t2", "t1", "dl", "la", "lo"]); P = P[(P["dl"].abs() < 1.0)].reset_index(drop=True)
P["dy"] = (P["t2"] - P["t1"]) / 365.0; P["rate"] = P["dl"] / P["dy"]
print("반복매매 쌍", len(P), "연 변화율 중앙", round(float(P["rate"].median()) * 100, 2), "%", flush=True)
tree = cKDTree(np.c_[P["la"].values * 111.0, P["lo"].values * KM]); T2 = P["t2"].values; RATE = P["rate"].values; DY = P["dy"].values; T1 = P["t1"].values
def drift(la, lo, cut, rad_list, min_n=8, win=730):
    for R in rad_list:
        ix = np.array(tree.query_ball_point([la * 111.0, lo * KM], R), dtype=int)
        if len(ix) == 0: continue
        ix = ix[(T2[ix] <= cut) & (T2[ix] >= cut - win)]   # 뒤 거래가 시험 시점 이전·최근 2년
        if len(ix) >= min_n:
            r = RATE[ix]; w = np.minimum(DY[ix], 1.5)   # 긴 간격일수록 변화율 추정이 안정적(최대 1.5년 가중)
            o = np.argsort(r); c = np.cumsum(w[o]) / w.sum(); return float(r[o][min(np.searchsorted(c, 0.5), len(r) - 1)]), R, len(ix)
    return None, None, 0
G = {k: (g["day"].values, g["size"].values, g["ppm"].values) for k, g in df.sort_values("day").groupby("bld")}
def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum(); return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])
rows = []
T = df[(df["deal_date"] >= 20250101) & df["lat"].notna()]
for r in T.itertuples():
    g = G.get(r.bld)
    if g is None: continue
    d, s, p = g; cut = r.day - 30
    hi = np.searchsorted(d, cut, side="right"); lo = np.searchsorted(d, cut - 730, side="left")
    if hi <= lo: continue
    m = np.abs(s[lo:hi] - r.size) <= 6
    if not m.any(): continue
    dd = d[lo:hi][m]; ss = s[lo:hi][m]; pp = p[lo:hi][m]; age = cut - dd
    w = np.exp(-age / 365.0) * np.exp(-np.abs(ss - r.size) / 10.0)
    base = wmed(pp, w) * r.size
    rec = {"y": r.price, "age": int(age.min()), "n": len(pp), "e1": base}
    gA, RA, nA = drift(r.lat, r.lon, cut, [0.5, 1.0, 2.0, 5.0]); g1, R1, n1 = drift(r.lat, r.lon, cut, [1.0])
    rec["radA"] = RA; rec["nA"] = nA
    adjA = pp * np.exp((gA if gA is not None else 0.0) * age / 365.0); rec["eA"] = wmed(adjA, w) * r.size
    adj1 = pp * np.exp((g1 if g1 is not None else 0.0) * age / 365.0); rec["e1k"] = wmed(adj1, w) * r.size
    rec["gA"] = gA; rows.append(rec)
R = pd.DataFrame(rows)
print("시험 거래", len(R), "생활권 지수 사용 가능(적응형)", int(R["gA"].notna().sum()), flush=True)
def st(x, c):
    e = x[c] / x["y"] - 1; a = e.abs(); return {"중앙오차%": round(float(a.median()) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "쏠림%": round(float(e.median()) * 100, 1), "높게10%+": round(float((e > .1).mean()) * 100, 1)}
res = {"시험 거래": int(len(R)), "생활권 지수 사용 가능 %": round(float(R["gA"].notna().mean()) * 100, 1), "사용한 반경 분포": R["radA"].value_counts(dropna=False).to_dict().__repr__()}
for lo_, hi_, nm in ((0, 90, "최근 같은 건물 거래 3개월 이내"), (91, 180, "3~6개월"), (181, 365, "6~12개월"), (366, 730, "1~2년")):
    X = R[(R["age"] >= lo_) & (R["age"] <= hi_)]
    if len(X) >= 300: res[nm] = {"건수": int(len(X)), "① 지금(시점 보정 없음)": st(X, "e1"), "A 생활권 지수(0.5→5km 적응형)": st(X, "eA"), "B 생활권 지수(고정 1km)": st(X, "e1k")}
res["전체"] = {"건수": int(len(R)), "① 지금": st(R, "e1"), "A 적응형": st(R, "eA"), "B 고정 1km": st(R, "e1k")}
Xv = R[R["gA"].notna()]; res["생활권 지수가 있는 거래만"] = {"건수": int(len(Xv)), "① 지금": st(Xv, "e1"), "A 적응형": st(Xv, "eA"), "B 고정 1km": st(Xv, "e1k")}
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-livingarea-test.json", "w"), ensure_ascii=False, indent=1)
