"""빌라 예상매도가 과대 원인 진단 자료 뽑기(2026-11-27, 측정 전용·앱 값 불변).
사건(villa-cases-asof 4구간, 그 당시 예상매도가)마다: ① 생활권(반경 500m)·같은 평형대(±5㎡)·비슷한 연식(±5년) 실거래 낙찰 전/후 180일 중앙
② 같은 생활권 전체 거래의 전/후 ㎡당 중앙(시장 변화) ③ 같은 건물 ±3㎡ 전/후 ④ 호별 공시가격(호수 일치→층·면적 근사)과 건물 안 상대 위치."""
import os, re, glob, json, gzip, importlib.util
import numpy as np, pandas as pd, requests
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); avm = bv.avm; vf = load("vf", "villa-features.py") if os.path.exists(os.path.join(HERE, "villa-features.py")) else None
SITE = "https://1234auction.vercel.app"
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
# 1) 사건 합치기
cases = {}
for f in glob.glob("vca-*/villa-cases-asof.json"):
    lg = open(os.path.join(os.path.dirname(f), "export-log.txt"), errors="ignore").read() if os.path.exists(os.path.join(os.path.dirname(f), "export-log.txt")) else ""
    m = re.search(r"(20\d{6})", lg); cut = m.group(1) if m else "0"
    for x in json.load(open(f)):
        if not x.get("est") or not x.get("minbid") or str(x["sale"]) < cut: continue
        o = cases.get(x["id"])
        if o is None or o["_cut"] < cut: cases[x["id"]] = dict(x, _cut=cut)
print("사건", len(cases), flush=True)
bc = {c["id"]: c for c in requests.get(SITE + "/api/auction?kind=bidCases", timeout=300).json()}
# 2) 거래
raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20240101" + FLT)
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
df["dt"] = pd.to_datetime(df["deal_date"].astype(str), format="%Y%m%d", errors="coerce")
df["by"] = pd.to_numeric(df["build_year"], errors="coerce")
print("거래", len(df), "좌표", int(df["lat"].notna().sum()), flush=True)
G = df[df["lat"].notna()].reset_index(drop=True)
KM = 111.0 * np.cos(np.radians(37.5)); tree = cKDTree(np.c_[G["lat"].values * 111.0, G["lon"].values * KM])
Gdt = G["dt"].values; Gsz = G["size"].values; Gppm = G["ppm"].values; Gby = G["by"].values
BLD = {k: g for k, g in df.groupby(["dong", "bunji"])}
# 3) 공시가격
OP = {}
if os.path.exists("official-price.jsonl.gz"):
    with gzip.open("official-price.jsonl.gz", "rt", encoding="utf-8") as fh:
        for ln in fh:
            r = json.loads(ln)
            if r.get("units"): OP[(r["pnu"], r["year"])] = r["units"]
print("공시 건물-연도", len(OP), flush=True)
def bunji_split(b):
    m = re.match(r"^\s*(산)?\s*(\d+)(?:-(\d+))?", str(b or ""))
    return (m.group(2), m.group(3) or "0") if m else (None, None)
def med(a): return float(np.median(a)) if len(a) else None
out = []
for x in cases.values():
    sd = pd.Timestamp(str(x["sale"])); area = float(x.get("area") or 0); o = {"id": x["id"], "sale": x["sale"]}
    if x.get("lat") and x.get("lon") and area > 0:
        idx = np.array(tree.query_ball_point([x["lat"] * 111.0, x["lon"] * KM], 0.5), int)
        if len(idx):
            d = Gdt[idx]; post = (d > np.datetime64(sd)) & (d <= np.datetime64(sd + pd.Timedelta(days=180))); pre = (d <= np.datetime64(sd)) & (d > np.datetime64(sd - pd.Timedelta(days=180)))
            sz = np.abs(Gsz[idx] - area) <= 5; byok = np.ones(len(idx), bool) if not x.get("by") else (np.abs(np.nan_to_num(Gby[idx], nan=-99) - x["by"]) <= 5)
            for nm, msk in (("lvPost", post & sz & byok), ("lvPre", pre & sz & byok), ("lvPostS", post & sz), ("lvPreS", pre & sz)):
                v = Gppm[idx][msk]; o[nm] = round(med(v) * area) if len(v) else None; o["n_" + nm] = int(msk.sum())
            o["mkPost"] = med(Gppm[idx][post]); o["mkPre"] = med(Gppm[idx][pre]); o["n_mk"] = int(post.sum())
    g = BLD.get((x.get("dong"), str(x.get("bunji"))))
    if g is not None and area > 0:
        gg = g[(g["size"] - area).abs() <= 3]
        a1 = gg[(gg["dt"] > sd) & (gg["dt"] <= sd + pd.Timedelta(days=180))]["ppm"].values; a0 = gg[(gg["dt"] <= sd) & (gg["dt"] > sd - pd.Timedelta(days=180))]["ppm"].values
        o["bdPost"] = round(med(a1) * area) if len(a1) else None; o["bdPre"] = round(med(a0) * area) if len(a0) else None
        sgv = g["sg"].dropna(); bjv = g["bj"].dropna(); bun, ji = bunji_split(x.get("bunji"))
        if len(sgv) and len(bjv) and bun:
            pnu = str(sgv.mode()[0]) + str(bjv.mode()[0]) + "1" + bun.zfill(4) + ji.zfill(4); yr = sd.year if sd.month >= 5 else sd.year - 1
            units = None
            for yy in (yr, yr - 1):
                units = OP.get((pnu, yy))
                if units: break
            if units:
                pr = []; me = None; ho = str((bc.get(x["id"]) or {}).get("unitNo") or "")
                hon = re.sub(r"\D", "", ho)[-4:] if ho else ""
                for dong_, f_, ho_, a_, p_ in units:
                    try: a_ = float(a_); p_ = float(p_) / 10000.0
                    except Exception: continue
                    if a_ > 0 and p_ > 0: pr.append((str(f_), re.sub(r"\D", "", str(ho_))[-4:], a_, p_))
                if pr:
                    ppm = np.array([p / a for _, _, a, p in pr]); o["gBldPpm"] = float(np.median(ppm)); o["gN"] = len(pr)
                    exact = [t for t in pr if hon and t[1] == hon and abs(t[2] - area) <= 3]
                    near = exact or [t for t in pr if abs(t[2] - area) <= 3 and str(t[0]).lstrip("-").isdigit() and x.get("floor") is not None and int(str(t[0]).lstrip("-") or 0) * (-1 if str(t[0]).startswith("-") else 1) == int(x["floor"])] or [t for t in pr if abs(t[2] - area) <= 3]
                    if near:
                        t = min(near, key=lambda t: abs(t[2] - area)); o["gUnit"] = t[3]; o["gUnitPpm"] = t[3] / t[2]; o["gExact"] = 1 if exact else 0
                        o["gRel"] = float(np.log(o["gUnitPpm"] / o["gBldPpm"]))
    out.append(o)
json.dump(out, open("villa-overest.json", "w"))
print("완료", len(out), "생활권 후 있음", sum(1 for o in out if o.get("lvPost")), "공시 호 있음", sum(1 for o in out if o.get("gUnit")), "호수 정확", sum(1 for o in out if o.get("gExact")), flush=True)
