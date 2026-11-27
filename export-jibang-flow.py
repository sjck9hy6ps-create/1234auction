"""지방 아파트 계층 흐름 분석(2026-11-28, 측정 전용·앱 불변): 시군구 → 법정동 → 생활권(반경 1km) → 단지 흐름이 단지의 이후 시세에 주는 영향과
'현재 위치'(단지가 주변 대비 평소보다 앞서감/뒤처짐)별 이후 변화. 실거래만, 그 달까지의 자료만. 정답: 6개월 뒤 단지 시세(최근 3개월 ㎡당 로그평균) 변화."""
import os, re, json, importlib.util
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(s); s.loader.exec_module(bv); avm = bv.avm
NOT_METRO = "&and=(region.not.like.서울*,region.not.like.경기*,region.not.like.인천*)"
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20190101" + NOT_METRO)
T = bv.prep(raw); T["mi"] = (pd.to_numeric(T["deal_date"]) // 10000) * 12 + (pd.to_numeric(T["deal_date"]) // 100 % 100) - 1; T["lp"] = np.log(T["ppm"])
T["cx"] = T["region"].astype(str) + "|" + T["dong"].astype(str) + "|" + T["bunji"].astype(str); T["dg"] = T["region"].astype(str) + "|" + T["dong"].astype(str)
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&and=(sigungu_cd.not.like.11*,sigungu_cd.not.like.28*,sigungu_cd.not.like.41*)")
cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
mnum = pd.to_numeric(T["main_num"], errors="coerce"); snum = pd.to_numeric(T["sub_num"], errors="coerce")
base = T["dong"].fillna("").astype(str) + "|" + T["danji"].fillna("").astype(str) + "|" + T["bunji"].fillna("").astype(str) + "|" + T["road_name"].fillna("").astype(str) + "|"
k1 = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
k2 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
co = k1.map(cmap).where(lambda x: x.notna(), k2.map(cmap)); T["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); T["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
print("매매", len(T), "좌표 연결", round(float(T["lat"].notna().mean()) * 100, 1), "%", flush=True)
m0, m1 = int(T["mi"].min()), int(T["mi"].max()); L = m1 - m0 + 1
def mats(key):
    keys = pd.unique(T[key]); kid = {k: i for i, k in enumerate(keys)}
    g = T.groupby([key, "mi"])["lp"].agg(["sum", "size"]).reset_index()
    Sm = np.zeros((len(keys), L)); Nm = np.zeros((len(keys), L))
    Sm[g[key].map(kid).values, g["mi"].values - m0] = g["sum"].values; Nm[g[key].map(kid).values, g["mi"].values - m0] = g["size"].values
    return keys, kid, Sm, Nm
def roll(Sm, Nm, w, minn):
    cs = np.cumsum(Sm, 1); cn = np.cumsum(Nm, 1)
    S = cs.copy(); N = cn.copy(); S[:, w:] -= cs[:, :-w]; N[:, w:] -= cn[:, :-w]
    P = np.where(N >= minn, S / np.maximum(N, 1), np.nan); return P, N
ck, cid, CS, CN = mats("cx"); C3, _ = roll(CS, CN, 3, 2); _, C6n = roll(CS, CN, 6, 1)
dk, did, DS, DN = mats("dg"); D3, _ = roll(DS, DN, 3, 5); _, D6n = roll(DS, DN, 6, 1)
rk, rid, RS, RN = mats("region"); R3, _ = roll(RS, RN, 3, 20); _, R6n = roll(RS, RN, 6, 1)
first = T.groupby("cx").agg(dg=("dg", "first"), rg=("region", "first"), lat=("lat", "median"), lon=("lon", "median")).reindex(ck)
c2d = first["dg"].map(did).values; c2r = first["rg"].map(rid).values
# 생활권: 반경 1km 안 다른 단지들의 3개월 시세 평균(3곳 이상)
LV = np.full((len(ck), L), np.nan); ok = first["lat"].notna().values
X = np.c_[first["lat"].values * 111.0, first["lon"].values * 111.0 * np.cos(np.radians(36.0))]
tree = cKDTree(X[ok]); idx_ok = np.where(ok)[0]
for j, i in enumerate(idx_ok):
    nb = [idx_ok[k] for k in tree.query_ball_point(X[i], 1.0) if idx_ok[k] != i]
    if len(nb) >= 3:
        M = C3[nb]; cnt = np.sum(~np.isnan(M), 0); LV[i] = np.where(cnt >= 3, np.nanmean(np.where(np.isnan(M), np.nan, M), 0), np.nan)
print("패널 완료 단지", len(ck), "생활권 있음", int(np.any(~np.isnan(LV), 1).sum()), flush=True)
DD = D3[c2d]; RR = R3[c2r]
def ch(A, t, k): return A[:, t] - A[:, t - k]
rows = []
for t in range(30, L - 6):
    fut = C3[:, t + 6] - C3[:, t]; v = ~np.isnan(fut)
    if not v.any(): continue
    # 현재 위치: 단지-생활권 / 단지-시군구 가격 차이의 지난 24개월 평균 대비 벗어남
    gCL = C3[:, t] - LV[:, t]; gCL0 = np.nanmean(C3[:, t - 24:t - 3] - LV[:, t - 24:t - 3], 1)
    gCR = C3[:, t] - RR[:, t]; gCR0 = np.nanmean(C3[:, t - 24:t - 3] - RR[:, t - 24:t - 3], 1)
    f = dict(R6=ch(RR, t, 6), R12=ch(RR, t, 12), D6=ch(DD, t, 6), L6=ch(LV, t, 6), L12=ch(LV, t, 12), C6=ch(C3, t, 6), C12=ch(C3, t, 12),
             Rv=R6n[c2r, t] / np.maximum(R6n[c2r, t - 6], 1) - 1, Dv=D6n[c2d, t] / np.maximum(D6n[c2d, t - 6], 1) - 1, Cv=C6n[:, t] / np.maximum(C6n[:, t - 6], 1) - 1, Cn=C6n[:, t],
             posL=gCL - gCL0, posR=gCR - gCR0)
    for i in np.where(v)[0]:
        rows.append([t + m0, i] + [f[k][i] for k in f] + [fut[i]])
cols = ["mi", "i", "R6", "R12", "D6", "L6", "L12", "C6", "C12", "Rv", "Dv", "Cv", "Cn", "posL", "posR", "fut"]
Dd = pd.DataFrame(rows, columns=cols); Dd["yr"] = Dd["mi"] // 12; Dd["down"] = (Dd["fut"] <= np.log(0.97)).astype(int)
print("행", len(Dd), "하락 3%↓", round(Dd["down"].mean() * 100, 1), flush=True)
out = {"n": int(len(Dd)), "baseDown": round(float(Dd["down"].mean()), 3)}
# (1) 범위별 영향: 연도별 표준화 회귀계수(큰 범위부터 차례로 더함) + 설명력
from numpy.linalg import lstsq
steps = [("시군구", ["R6", "R12", "Rv"]), ("+법정동", ["D6", "Dv"]), ("+생활권", ["L6", "L12"]), ("+단지", ["C6", "C12", "Cv", "Cn"]), ("+현재 위치", ["posL", "posR"])]
imp = {}
for y in sorted(Dd["yr"].unique()):
    G = Dd[Dd["yr"] == y].copy(); feats = []; r2 = {}
    for nm_, fs in steps:
        feats = feats + fs; H = G.dropna(subset=feats + ["fut"])
        if len(H) < 2000: break
        Z = (H[feats] - H[feats].mean()) / H[feats].std().replace(0, 1); A = np.c_[np.ones(len(H)), Z.values]; b = lstsq(A, H["fut"].values, rcond=None)[0]
        res = H["fut"].values - A @ b; r2[nm_] = round(float(1 - res.var() / H["fut"].var()), 4)
        if nm_ == "+현재 위치": imp[str(int(y))] = {"n": int(len(H)), "설명력(누적)": r2, "계수(표준화, 6개월 로그변화)": {k: round(float(c), 4) for k, c in zip(feats, b[1:])}}
    if str(int(y)) not in imp: imp[str(int(y))] = {"설명력(누적)": r2}
out["levels"] = imp
# (2) 위치표: 위 흐름(시군구 6개월) × 단지 위치(생활권 대비 평소보다 앞섬/뒤처짐) → 이후 6개월 단지 변화·하락 비율, 연도별
def band(v, cuts, labs): return pd.cut(v, [-np.inf] + cuts + [np.inf], labels=labs)
Dd["upper"] = band(Dd["R6"], [-0.02, 0.02], ["시군구 하락", "시군구 보합", "시군구 상승"])
Dd["lupper"] = band(Dd["L6"], [-0.02, 0.02], ["생활권 하락", "생활권 보합", "생활권 상승"])
Dd["pos"] = band(Dd["posL"], [-0.03, 0.03], ["단지 뒤처짐", "제자리", "단지 앞서감"])
Dd["cflow"] = band(Dd["C6"], [-0.03, 0.03], ["단지 하락", "단지 보합", "단지 상승"])
tab = {}
for a, b2 in (("upper", "pos"), ("lupper", "pos"), ("upper", "cflow"), ("lupper", "cflow")):
    t2 = Dd.dropna(subset=[a, b2]).groupby([a, b2, "yr"], observed=True).agg(n=("fut", "size"), chg=("fut", "mean"), down=("down", "mean")).reset_index()
    tab[f"{a}×{b2}"] = [[str(r[a]), str(r[b2]), int(r["yr"]), int(r["n"]), round(float(np.exp(r["chg"]) - 1) * 100, 2), round(float(r["down"]) * 100, 1)] for _, r in t2.iterrows()]
out["positionTable"] = tab
json.dump(out, open("jibang-flow.json", "w"), ensure_ascii=False, indent=1)
# (3) 경매 사건별 입찰 35일 전(직전 완결 월) 흐름 위치 내보내기
import requests
bc = requests.get("https://1234auction.vercel.app/api/auction?kind=bidCases", timeout=300).json()
bykey = T.groupby(["dong", "bunji", "cx"]).size().reset_index(name="n").sort_values("n").drop_duplicates(["dong", "bunji"], keep="last")
dbk = {(r.dong, str(r.bunji)): r.cx for r in bykey.itertuples()}
# 경매 주소의 동은 마지막 단어만 있는 경우가 많아 끝 단어로도 찾음
T["dong1"] = T["dong"].astype(str).str.split().str[-1]
bykey1 = T.groupby(["dong1", "bunji", "cx"]).size().reset_index(name="n").sort_values("n").drop_duplicates(["dong1", "bunji"], keep="last")
dbk1 = {(r.dong1, str(r.bunji)): r.cx for r in bykey1.itertuples()}
cases = {}
for c in bc:
    if "아파트" not in (c.get("propertyType") or "") or not c.get("saleDate") or str(c.get("addrJibun") or "").startswith(("서울", "경기", "인천")): continue
    cxk = dbk.get((c.get("dong"), str(c.get("bunji")))) or dbk1.get((str(c.get("dong") or "").split()[-1] if c.get("dong") else "", str(c.get("bunji"))))
    if cxk is None or cxk not in cid: continue
    sd = pd.Timestamp(c["saleDate"]) - pd.Timedelta(days=35); t = sd.year * 12 + sd.month - 1 - 1 - m0
    if t < 30 or t >= L: continue
    i = cid[cxk]
    def gv(A, k=None):
        if k is None: v = A[i, t]
        else: v = A[i, t] - A[i, t - k]
        return None if not np.isfinite(v) else round(float(v), 5)
    gCL = C3[i, t] - LV[i, t]; gCL0 = np.nanmean(C3[i, t - 24:t - 3] - LV[i, t - 24:t - 3]); gCR = C3[i, t] - RR[i, t]; gCR0 = np.nanmean(C3[i, t - 24:t - 3] - RR[i, t - 24:t - 3])
    cases[c["id"]] = {"posL": None if not np.isfinite(gCL - gCL0) else round(float(gCL - gCL0), 5), "posR": None if not np.isfinite(gCR - gCR0) else round(float(gCR - gCR0), 5),
                      "L6": gv(LV, 6), "R6": gv(RR, 6), "D6": gv(DD, 6), "C6": gv(C3, 6), "C12": gv(C3, 12), "Cn": float(C6n[i, t])}
json.dump(cases, open("jibang-flow-cases.json", "w"))
print("경매 사건 위치", len(cases), "위치 있음", sum(1 for v in cases.values() if v["posL"] is not None), flush=True)

print("완료", flush=True)
