"""아파트 예상매도가 '같은 단지 다른 층·평형 거래 + 조건 보정' 시험(2026-11-28, 측정 전용·앱 불변).
사용자: 아파트 1층은 거래가 드물어 다른 층 거래의 영향을 받음 → 같은 단지 다른 층·평형 거래를 층·면적·시점 차이만큼 보정해 추론.
같은 단지 거래가 없으면 1km 안 다른 단지 거래를 연식·면적·층·시점 보정. 조건 효과는 2023년 이전 거래로만 학습. 결과: 사건별 추정값(낙찰 35일 전 기준)."""
import os, re, json, importlib.util
import numpy as np, pandas as pd, requests
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(s); s.loader.exec_module(bv); avm = bv.avm
raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20170101")
df = bv.prep(raw); del raw
df["lp"] = np.log(df["ppm"]); df["mi"] = df["dt"].dt.year * 12 + df["dt"].dt.month - 1
df["by"] = df["build_year"].where(df["build_year"].between(1960, 2026)); df["age"] = (df["dt"].dt.year - df["by"]).clip(0, 60)
df["cx"] = df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["bunji"].astype(str)
print("아파트 거래", len(df), flush=True)
def F_in(size, floor):   # 단지 안 비교: 층·면적
    size = np.asarray(size, float); fl = np.asarray(floor, float)
    return np.c_[np.log(size), np.log(size) ** 2, fl == 1, fl == 2, (fl >= 6) & (fl <= 10), (fl >= 11) & (fl <= 20), fl >= 21].astype(float)
def F_x(size, floor, age):   # 단지 사이 비교: + 연식
    a = np.asarray(age, float); an = np.nan_to_num(a, nan=20.0)
    return np.c_[F_in(size, floor), an / 10, (an / 10) ** 2, np.isnan(a)].astype(float)
tr = df[df["mi"] < 2023 * 12]
r1 = tr["lp"] - tr.groupby(["cx", tr["dt"].dt.year])["lp"].transform("median")
X1 = np.c_[np.ones(len(tr)), F_in(tr["size"], tr["floor"])]; b_in = np.linalg.lstsq(X1, r1.values, rcond=None)[0]
r2 = tr["lp"] - tr.groupby(["region", "mi"])["lp"].transform("median")
X2 = np.c_[np.ones(len(tr)), F_x(tr["size"], tr["floor"], tr["age"])]; b_x = np.linalg.lstsq(X2, r2.values, rcond=None)[0]
print("단지 안 계수", np.round(b_in, 3).tolist(), "단지 사이 계수", np.round(b_x, 3).tolist(), flush=True)
df["qi"] = df["lp"] - F_in(df["size"], df["floor"]) @ b_in[1:]
df["qx"] = df["lp"] - F_x(df["size"], df["floor"], df["age"]) @ b_x[1:]
# 시군구 월 지수: 단지 고정효과(2023 이전 평균)를 뺀 값의 월 중앙
cxm = df[df["mi"] < 2023 * 12].groupby("cx")["qi"].mean()
d2 = df[df["cx"].isin(cxm.index)].copy(); d2["dv"] = d2["qi"] - d2["cx"].map(cxm)
IX = d2.groupby(["region", "mi"])["dv"].median()
idx = {}
for reg, g in IX.groupby(level=0):
    s_ = g.droplevel(0).sort_index(); full = pd.Series(np.nan, index=range(int(s_.index.min()), int(s_.index.max()) + 1)); full.loc[s_.index] = s_.values
    idx[reg] = full.rolling(3, min_periods=1).mean().ffill()
def ix(reg, m):
    s_ = idx.get(reg)
    if s_ is None: return 0.0
    m = min(max(m, s_.index.min()), s_.index.max()); v = s_.loc[m]; return float(v) if np.isfinite(v) else 0.0
# 좌표(단지 사이 비교용)
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id")
cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
k1 = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
k2 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
co = k1.map(cmap).where(lambda x: x.notna(), k2.map(cmap))
df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
print("좌표", round(df["lat"].notna().mean() * 100, 1), "%", flush=True)
GC = {k: g for k, g in df.groupby("cx")}
G = df[df["lat"].notna()].reset_index(drop=True)
tree = cKDTree(np.c_[G["lat"].values * 111.0, G["lon"].values * 111.0 * np.cos(np.radians(36.5))])
bykey = df.groupby(["dong", "bunji", "cx"]).size().reset_index(name="n").sort_values("n").drop_duplicates(["dong", "bunji"], keep="last")
dbk = {(r.dong, str(r.bunji)): r.cx for r in bykey.itertuples()}
df["dong1"] = df["dong"].astype(str).str.split().str[-1]
bykey1 = df.groupby(["dong1", "bunji", "cx"]).size().reset_index(name="n").sort_values("n").drop_duplicates(["dong1", "bunji"], keep="last")
dbk1 = {(r.dong1, str(r.bunji)): r.cx for r in bykey1.itertuples()}
bc = requests.get("https://1234auction.vercel.app/api/auction?kind=bidCases", timeout=300).json()
def wmed(v, w):
    o = np.argsort(v); cw = np.cumsum(w[o]); return float(v[o][np.searchsorted(cw, cw[-1] / 2)])
out = {}
for c in bc:
    if "아파트" not in (c.get("propertyType") or "") or not c.get("saleDate") or c["saleDate"] < "2023-01-01" or not c.get("areaM2"): continue
    cut = pd.Timestamp(c["saleDate"]) - pd.Timedelta(days=35); cm = cut.year * 12 + cut.month - 1; area = float(c["areaM2"])
    try: fl = float(str(c.get("floor")).strip()) if c.get("floor") not in (None, "") else np.nan
    except Exception: fl = np.nan
    cxk = dbk.get((c.get("dong"), str(c.get("bunji")))) or dbk1.get((str(c.get("dong") or "").split()[-1] if c.get("dong") else "", str(c.get("bunji"))))
    res = None
    if cxk is not None:
        g = GC[cxk]; g = g[(g["dt"] <= cut)]; reg = g["region"].iloc[0] if len(g) else None
        for months in (24, 60, 120):
            h = g[g["mi"] >= cm - months]
            if len(h) >= 3:
                v = h["qi"].values + np.array([ix(reg, cm) - ix(reg, m) for m in h["mi"].values]) + float(np.ravel(F_in([area], [fl]) @ b_in[1:])[0])
                w = np.exp(-(cm - h["mi"].values) / 18.0) * np.exp(-np.abs(np.log(h["size"].values / area)) / 0.15)
                same = int((np.abs(h["size"].values - area) <= 3).sum())
                res = {"est": round(float(np.exp(wmed(v, w)) * area)), "lv": "같은 단지", "m": months, "n": int(len(h)), "same": same,
                       "sameFloor": int(((np.abs(h["size"].values - area) <= 3) & (h["floor"].values == fl)).sum())}
                break
    if res is None and c.get("lat") and c.get("lon"):
        nb = np.array(tree.query_ball_point([float(c["lat"]) * 111.0, float(c["lon"]) * 111.0 * np.cos(np.radians(36.5))], 1.0), int)
        if len(nb):
            nb = nb[(G["dt"].values[nb] <= np.datetime64(cut)) & (G["mi"].values[nb] >= cm - 24)]
            if len(nb) >= 5:
                age_t = np.nan
                try: age_t = cut.year - float(c.get("buildYear")) if c.get("buildYear") else np.nan
                except Exception: age_t = np.nan
                regs = G["region"].values[nb]
                v = G["qx"].values[nb] + np.array([ix(r, cm) - ix(r, m) for r, m in zip(regs, G["mi"].values[nb])]) + float(np.ravel(F_x([area], [fl], [age_t]) @ b_x[1:])[0])
                dkm = np.sqrt(((G["lat"].values[nb] - float(c["lat"])) * 111.0) ** 2 + ((G["lon"].values[nb] - float(c["lon"])) * 111.0 * np.cos(np.radians(36.5))) ** 2)
                w = np.exp(-dkm / 0.5) * np.exp(-np.abs(np.log(G["size"].values[nb] / area)) / 0.2)
                res = {"est": round(float(np.exp(wmed(v, w)) * area)), "lv": "주변 단지", "n": int(len(nb))}
    if res: out[c["id"]] = res
json.dump(out, open("apt-comp.json", "w"))
print("완료", len(out), pd.Series([v["lv"] for v in out.values()]).value_counts().to_dict(), flush=True)
