"""빌라 예상매도가 '주변 거래 + 조건 보정' 시험(2026-11-28, 측정 전용·앱 불변).
사용자: 빌라는 같은 건물·같은 집 거래가 거의 한 번뿐 → 주변 거래를 그 집 조건에 맞게 옮겨 와 추론(아파트 1층이 다른 층 거래로 추론되는 것과 같은 구조).
① 2025-01 이전 거래로 조건 효과(연식·면적·층·승강기·세대수) 학습(같은 시군구·같은 달 안에서 비교) ② 시군구 월간 흐름 지수(조건 보정 후)
③ 경매 빌라마다 입찰 35일 전까지의 주변 거래(300m→500m→1km, 최근 10년)를 시점·조건 보정 → 거리·최근성·면적 유사도 가중 중앙값."""
import os, re, glob, json, importlib.util
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py"); avm = bv.avm
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20160101" + FLT)
df = bv.prep(raw)
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd,lat,lon", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd, r.lat, r.lon) for r in cc.itertuples()}
mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
c2 = k_new.map(cmap)
for alt in (k_leg, k_leg0): c2 = c2.where(~c2.isna(), alt.map(cmap))
df["sg"] = c2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = c2.map(lambda x: x[1] if isinstance(x, tuple) else None)
df["lat"] = c2.map(lambda x: x[2] if isinstance(x, tuple) and x[2] else np.nan); df["lon"] = c2.map(lambda x: x[3] if isinstance(x, tuple) and x[3] else np.nan)
bb = df["bunji"].map(vf.bunji_to_bunji); df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
B = vf.fetch_buildings()
for c in ("elv", "emg", "grnd", "hh"): B[c] = pd.to_numeric(B.get(c), errors="coerce")
B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce"); B["elvAny"] = ((B["elv"].fillna(0) + B["emg"].fillna(0)) > 0).astype(float)
Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), hh=("hh", "max"), apr=("apr", "min")).reset_index()
df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"]).reset_index(drop=True)
df["by2"] = df["build_year"].where(df["build_year"].between(1960, 2026), df["apr"].where(df["apr"].between(1960, 2026)))
df["age"] = (df["dt"].dt.year - df["by2"]).clip(0, 60); df["lp"] = np.log(df["ppm"]); df["mi"] = df["dt"].dt.year * 12 + df["dt"].dt.month - 1
print("빌라 거래", len(df), "좌표", round(df["lat"].notna().mean() * 100, 1), "%", "대장", round(df["elv"].notna().mean() * 100, 1), "%", flush=True)
# ① 조건 효과: 같은 시군구·같은 달 중앙값을 뺀 값을 조건으로 설명(2025-01 이전만)
APPMODE = os.environ.get("APPMODE") == "1"   # 앱과 같은 조건(승강기·세대수 없이)
def feats(age, size, floor, elv, hh):
    age = np.asarray(age, float); size = np.asarray(size, float); floor = np.asarray(floor, float); elv = np.asarray(elv, float); hh = np.asarray(hh, float)
    a = np.nan_to_num(age, nan=20.0)
    base = [a / 10, (a / 10) ** 2, np.isnan(age), np.log(size), np.log(size) ** 2, floor <= 0, floor == 1, (floor >= 4) & (floor < 99)]
    if APPMODE: return np.c_[tuple(base)].astype(float)
    return np.c_[tuple(base + [np.nan_to_num(elv, nan=0) > 0, np.isnan(elv), np.log1p(np.nan_to_num(hh, nan=10))])].astype(float)
tr = df[df["mi"] < 2025 * 12].copy()
KEY = "sg" if APPMODE else "region"
tr = tr[tr[KEY].notna()] if APPMODE else tr
tr["res"] = tr["lp"] - tr.groupby([KEY, "mi"])["lp"].transform("median")
Xt = feats(tr["age"], tr["size"], tr["floor"], tr["elv"], tr["hh"]); Xt = np.c_[np.ones(len(Xt)), Xt]
beta = np.linalg.lstsq(Xt, tr["res"].values, rcond=None)[0]
def xb(age, size, floor, elv, hh): X = feats(age, size, floor, elv, hh); return X @ beta[1:]
print("조건 효과 학습", len(tr), "계수", np.round(beta, 3).tolist(), flush=True)
# ② 시군구 월간 흐름 지수(조건 보정 후 중앙, 3개월 이동)
df["xb"] = xb(df["age"], df["size"], df["floor"], df["elv"], df["hh"]); df["q"] = df["lp"] - df["xb"]
IX = df.dropna(subset=[KEY]).groupby([KEY, "mi"])["q"].agg(["median", "size"]).reset_index()
idx = {}
for reg, g in IX.groupby(KEY):
    s = g.set_index("mi")["median"].sort_index(); full = pd.Series(np.nan, index=range(int(s.index.min()), int(s.index.max()) + 1)); full.loc[s.index] = s.values
    idx[reg] = full.rolling(3, min_periods=1).mean().ffill()
def ix(reg, m):
    s = idx.get(reg)
    if s is None: return np.nan
    m = min(max(m, s.index.min()), s.index.max()); return float(s.loc[m])
# ③ 경매 빌라(그 당시 사례 파일)
cases = {}
for f in glob.glob("vca-*/villa-cases-asof.json"):
    lg = open(os.path.join(os.path.dirname(f), "export-log.txt"), errors="ignore").read() if os.path.exists(os.path.join(os.path.dirname(f), "export-log.txt")) else ""
    m = re.search(r"(20\d{6})", lg); cut = m.group(1) if m else "0"
    for x in json.load(open(f)):
        if not x.get("est") or str(x["sale"]) < cut: continue
        o = cases.get(x["id"])
        if o is None or o["_cut"] < cut: cases[x["id"]] = dict(x, _cut=cut)
G = df[df["lat"].notna()].reset_index(drop=True)
KM = 111.0 * np.cos(np.radians(37.5)); tree = cKDTree(np.c_[G["lat"].values * 111.0, G["lon"].values * KM])
Gmi = G["mi"].values; Gq = G["q"].values; Gsz = G["size"].values; Greg = G[KEY].values; Gday = G["dt"].values
out = {}
for x in cases.values():
    if not x.get("lat") or not x.get("lon") or not x.get("area"): continue
    s = str(x["sale"]); cutd = pd.Timestamp(int(s[:4]), int(s[4:6]), int(s[6:])) - pd.Timedelta(days=35); cm = cutd.year * 12 + cutd.month - 1
    age_t = (cutd.year - x["by"]) if x.get("by") else np.nan
    xbt = float(xb([age_t], [x["area"]], [x.get("floor") if x.get("floor") is not None else np.nan], [x.get("elv") if x.get("elv") is not None else np.nan], [x.get("hh") if x.get("hh") is not None else np.nan])[0])
    reg_t = None
    res = None
    for R in (0.3, 0.5, 1.0):
        nb = np.array(tree.query_ball_point([x["lat"] * 111.0, x["lon"] * KM], R), int)
        if not len(nb): continue
        nb = nb[(Gday[nb] <= np.datetime64(cutd)) & (Gmi[nb] >= cm - 120)]
        if len(nb) < 8: continue
        reg_t = pd.Series(Greg[nb]).mode()[0]
        # 시점 보정: 비교 거래 달 → 기준 시점(같은 시군구 지수)
        tadj = np.array([ix(Greg[j], cm) - ix(Greg[j], Gmi[j]) for j in nb])
        v = Gq[nb] + tadj + xbt
        dkm = np.sqrt(((G["lat"].values[nb] - x["lat"]) * 111.0) ** 2 + ((G["lon"].values[nb] - x["lon"]) * KM) ** 2)
        w = np.exp(-dkm / 0.3) * np.exp(-(cm - Gmi[nb]) / 36.0) * np.exp(-np.abs(np.log(Gsz[nb] / x["area"])) / 0.2)
        ok = np.isfinite(v) & np.isfinite(w)
        if ok.sum() < 8: continue
        v, w = v[ok], w[ok]; o = np.argsort(v); cw = np.cumsum(w[o]); med = v[o][np.searchsorted(cw, cw[-1] / 2)]
        q25 = v[o][np.searchsorted(cw, cw[-1] * 0.25)]; q75 = v[o][np.searchsorted(cw, cw[-1] * 0.75)]
        res = {"est": round(float(np.exp(med) * x["area"])), "R": R, "n": int(ok.sum()), "spread": round(float(q75 - q25), 4), "w": round(float(w.sum()), 3),
               "n2y": int(((cm - Gmi[nb][ok]) <= 24).sum())}
        break
    if res: out[x["id"]] = res
json.dump(out, open("villa-comp.json", "w"))
if APPMODE:   # 앱이 쓸 모델(조건 효과 + 시군구 월 지수, 2019년부터)
    model = {"beta": [round(float(b), 5) for b in beta], "feat": "age/10,(age/10)^2,ageNA,ln(size),ln(size)^2,floor<=0,floor==1,floor>=4", "idx": {str(k): {str(int(m)): round(float(v), 4) for m, v in s_.items() if m >= 2019 * 12 and np.isfinite(v)} for k, s_ in idx.items()}, "gen": pd.Timestamp.now().isoformat()}
    json.dump(model, open("villa-comp-model.json", "w"))
print("완료 사건", len(cases), "추정", len(out), "반경", pd.Series([v["R"] for v in out.values()]).value_counts().to_dict(), flush=True)
