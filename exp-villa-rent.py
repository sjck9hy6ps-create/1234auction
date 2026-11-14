"""🏘️ 빌라 전월세 수요 시험(2026-11-14, 측정 전용; 앞부분은 exp-villa-relative와 같은 준비) - 빌라 '동네 안 상대 조건' 시험(2026-11-14, 측정 전용) - 사용자: 절대 연식이 아니라 그 동네에서 상대적으로 새 건물·승강기가 드문 동네의 승강기 건물이 인기 있을 것
동네 = 법정동(건축물대장 시군구·법정동코드). 신축(사용승인 후 4년 이내)은 제외(앱 규칙). 상대 연식 = 같은 법정동 연립·다세대 건물 중 이 건물보다 오래된 건물의 비율(0=가장 오래됨 ~ 1=가장 새로움).
시험: ① 같은 동·분기 대비 ㎡당 가격(프리미엄) ② 세대당 거래 횟수(회전율) 을 절대 연식과 상대 연식으로 각각 설명해 보고, 옛 동네·새 동네에서 기울기가 어느 쪽 기준으로 더 일정한지 비교
③ 승강기: 동네 승강기 보유 비율이 낮을수록 승강기 건물의 프리미엄·회전율이 큰지"""
import os, json, importlib.util
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(HERE, "analyze-villa-factors.py"), encoding="utf-8").read().replace('bc:title_json->bcRat"', 'bc:title_json->bcRat,pk1:title_json->indrAutoUtcnt,pk2:title_json->oudrAutoUtcnt,pk3:title_json->indrMechUtcnt,pk4:title_json->oudrMechUtcnt,st:title_json->>strct,hs:title_json->hhldSum,hgt:title_json->heit"')
assert "pk1:title_json" in _src
afv = importlib.util.module_from_spec(importlib.util.spec_from_loader("afv", loader=None)); afv.__file__ = os.path.join(HERE, "analyze-villa-factors.py"); exec(compile(_src, "analyze-villa-factors.py", "exec"), afv.__dict__)
bv = afv.bv; avm = afv.avm
raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.20230101{afv.METRO}")
df = bv.prep(raw); print(f"빌라 거래 {len(df):,}건")
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples()}
mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
cc2 = k_new.map(cmap)
for alt in (k_leg, k_leg0):
    miss = cc2.isna(); cc2 = cc2.where(~miss, alt.map(cmap))
df["sg"] = cc2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = cc2.map(lambda x: x[1] if isinstance(x, tuple) else None)
bb = df["bunji"].map(afv.bunji_to_bunji); df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
tf = avm.fetch_all_rows("transit_features", cols="cache_key,dist_subway_m", order_col="cache_key"); tmap = {r.cache_key: r.dist_subway_m for r in tf.itertuples() if pd.notna(r.dist_subway_m)}
t2 = k_new.map(tmap)
for alt in (k_leg, k_leg0):
    t2 = t2.where(t2.notna(), alt.map(tmap))
df["subm"] = t2
B = afv.fetch_buildings()
for c in ("elv", "emg", "grnd", "hh"): B[c] = pd.to_numeric(B[c], errors="coerce")
B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
B["elvAny"] = (B["elv"].fillna(0) + B["emg"].fillna(0)) > 0
for c in ("pk1", "pk2", "pk3", "pk4", "plat", "tot", "vl", "bc", "hgt"): B[c] = pd.to_numeric(B[c], errors="coerce")
print("대장 건물 용도 상위:", B["purp"].astype(str).value_counts().head(8).to_dict())
B = B[B["purp"].astype(str).str.contains("공동주택|다세대|연립", na=False) & B["apr"].between(1960, 2026) & (B["hh"].fillna(0) <= 80) & (B["grnd"].fillna(0) <= 7)].copy()
B["pk"] = B[["pk1", "pk2", "pk3", "pk4"]].fillna(0).sum(axis=1)
Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min"), pk=("pk", "max"), plat=("plat", "max"), tot=("tot", "max"), vl=("vl", "max"), bc=("bc", "max"), st=("st", "first")).reset_index()
print(f"연립·다세대 대장 건물 {len(Bg):,}곳")
# 동네(법정동)별 상대 연식·승강기 비율
Bg["nb"] = Bg["sigungu_cd"].astype(str) + "|" + Bg["bjdong_cd"].astype(str)
sz = Bg.groupby("nb")["apr"].transform("size")
Bg["rel"] = Bg.groupby("nb")["apr"].rank(pct=True, method="average")          # 1에 가까울수록 새 건물(사용승인 연도가 큰 쪽)
Bg["nbMed"] = Bg.groupby("nb")["apr"].transform("median"); Bg["nbN"] = sz
hi = Bg[Bg["grnd"] >= 4]
es = hi.groupby("nb")["elv"].agg(["mean", "size"]).rename(columns={"mean": "elvShare", "size": "nHigh"})
Bg = Bg.merge(es, how="left", left_on="nb", right_index=True)
Bg = Bg[Bg["nbN"] >= 15]
df = df.merge(Bg, how="inner", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"])
df["dyear"] = df["deal_date"] // 10000; df["ageA"] = df["dyear"] - df["apr"]
df = df[df["ageA"] >= 5].copy()   # 신축(4년 이내) 제외
print(f"분석 거래 {len(df):,}건, 건물 {df['bld'].nunique():,}곳, 동네 {df['nb'].nunique():,}곳")

out = {"trades": int(len(df)), "buildings": int(df["bld"].nunique())}
# ── 전월세 자료
rr = avm.fetch_all_rows("villa_rent", cols="region,dong,bunji,size,deposit,monthly_rent,floor,deal_date,build_year", extra_filter=f"&deal_date=gte.20240701{afv.METRO}")
for c in ("size", "deposit", "monthly_rent", "deal_date"): rr[c] = pd.to_numeric(rr[c], errors="coerce")
rr = rr[(rr["deposit"] >= 0) & (rr["size"] >= 15) & (rr["size"] <= 150)].dropna(subset=["deal_date"]).copy()
rr["bld"] = rr["region"].astype(str) + "|" + rr["dong"].astype(str) + "|" + rr["bunji"].astype(str)
rr["jeonse"] = rr["monthly_rent"].fillna(0) == 0
last = int(rr["deal_date"].max()); print(f"전월세 {len(rr):,}건 ({int(rr['deal_date'].min())}~{last})")
out["rentRows"] = int(len(rr)); out["rentLast"] = last
W2_from = 20250101
def months_between(a, b): return (b // 10000 - a // 10000) * 12 + (b // 100 % 100 - a // 100 % 100) + 1
yrs2 = months_between(W2_from, last) / 12.0; yrs1 = 6 / 12.0
# ── 건물 표(매매 거래가 있는 건물)
Bt = df.groupby("bld").agg(sg=("sg", "first"), bj=("bj", "first"), nb=("nb", "first"), rel=("rel", "first"), nbMed=("nbMed", "first"), apr=("apr", "first"), elv=("elv", "first"), grnd=("grnd", "first"), hh=("hh", "first"), elvShare=("elvShare", "first")).reset_index()
Bt = Bt[Bt["hh"] >= 4].copy(); Bt["ageN"] = 2026 - Bt["apr"]; Bt = Bt[Bt["ageN"] >= 5]
sale2 = df[df["deal_date"] >= W2_from].groupby("bld").size().rename("sale2"); Bt = Bt.merge(sale2, how="left", left_on="bld", right_index=True); Bt["sale2"] = Bt["sale2"].fillna(0)
r2c = rr[rr["deal_date"] >= W2_from].groupby("bld").size().rename("rent2"); j2c = rr[(rr["deal_date"] >= W2_from) & rr["jeonse"]].groupby("bld").size().rename("jeo2")
r1c = rr[rr["deal_date"] < 20250101].groupby("bld").size().rename("rent1")
for s_ in (r2c, j2c, r1c): Bt = Bt.merge(s_, how="left", left_on="bld", right_index=True)
for c in ("rent2", "jeo2", "rent1"): Bt[c] = Bt[c].fillna(0)
Bt["saleTurn"] = Bt["sale2"] / Bt["hh"] / yrs2 * 100; Bt["rentTurn"] = Bt["rent2"] / Bt["hh"] / yrs2 * 100; Bt["rentTurn1"] = Bt["rent1"] / Bt["hh"] / yrs1 * 100
Bt["wolsePct"] = np.where(Bt["rent2"] >= 3, (Bt["rent2"] - Bt["jeo2"]) / Bt["rent2"] * 100, np.nan)
print(f"건물 {len(Bt):,}곳, 평균 매매 회전율 {Bt['saleTurn'].mean():.2f}% / 전월세 회전율 {Bt['rentTurn'].mean():.2f}%")
def pooled(G, a, b): return round(float(G[a].sum() / G["hh"].sum() / (yrs2 if a != "rent1" else yrs1) * 100), 2)
# 같은 동 안에서 전월세가 활발한 건물이 매매도 활발한가(동 평균 대비 5분위)
Bt["rentRank"] = Bt.groupby("nb")["rentTurn"].rank(pct=True)
Bt["rentRb"] = pd.cut(Bt["rentRank"], [0, .2, .4, .6, .8, 1.0001], labels=["동네에서 전월세 가장 적은 20%", "20~40", "40~60", "60~80", "가장 활발한 20%"])
out["saleTurnByRentRank(같은 동 안)"] = {str(k): {"건물": int(len(G)), "매매 연 회전율%": pooled(G, "sale2", "hh"), "전월세 연 회전율%": pooled(G, "rent2", "hh")} for k, G in Bt.groupby("rentRb", observed=True)}
# 앞선 시기(2024-07~12)의 전월세 → 이후(2025~) 매매 회전율(미래를 맞히나)
Bt["rentRank1"] = Bt.groupby("nb")["rentTurn1"].rank(pct=True); Bt["rentR1b"] = pd.cut(Bt["rentRank1"], [0, .2, .4, .6, .8, 1.0001], labels=["가장 적은 20%", "20~40", "40~60", "60~80", "가장 활발한 20%"])
out["앞선 6개월 전월세 활발도 → 이후 매매 회전율"] = {str(k): {"건물": int(len(G)), "이후 매매 연 회전율%": pooled(G, "sale2", "hh")} for k, G in Bt.groupby("rentR1b", observed=True)}
# 전월세 회전율이 상대 연식·절대 연식 중 어느 쪽으로 더 일관되게 설명되나(동네 유형별)
Bt["nbType"] = pd.cut(Bt["nbMed"], [1900, 1995, 2005, 2030], labels=["옛 동네", "중간", "새 동네"])
Bt["relb"] = pd.cut(Bt["rel"], [0, .2, .4, .6, .8, 1.0001], labels=["가장 오래된 20%", "20~40", "40~60", "60~80", "가장 새로운 20%"]); Bt["ageb"] = pd.cut(Bt["ageN"], [4, 10, 20, 30, 80], labels=["5~10년", "11~20년", "21~30년", "31년+"])
out["전월세 회전율: 절대연식 x 동네유형"] = {str(k): {str(a): {"건물": int(len(H)), "전월세 연 회전율%": pooled(H, "rent2", "hh")} for a, H in G.groupby("ageb", observed=True) if len(H) >= 200} for k, G in Bt.groupby("nbType", observed=True)}
out["전월세 회전율: 상대연식 x 동네유형"] = {str(k): {str(a): {"건물": int(len(H)), "전월세 연 회전율%": pooled(H, "rent2", "hh")} for a, H in G.groupby("relb", observed=True) if len(H) >= 200} for k, G in Bt.groupby("nbType", observed=True)}
# 승강기
Bt["shb"] = pd.cut(Bt["elvShare"], [-.01, .15, .4, .7, 1.01], labels=["동네 승강기 건물 15% 이하", "15~40%", "40~70%", "70% 초과"])
ev = {}
for k, G in Bt[Bt["grnd"] >= 4].groupby("shb", observed=True):
    a, b_ = G[G["elv"].astype(bool)], G[~G["elv"].astype(bool)]
    if len(a) >= 100 and len(b_) >= 100: ev[str(k)] = {"승강기 있음": {"건물": int(len(a)), "전월세 회전율%": pooled(a, "rent2", "hh"), "매매 회전율%": pooled(a, "sale2", "hh")}, "없음": {"건물": int(len(b_)), "전월세 회전율%": pooled(b_, "rent2", "hh"), "매매 회전율%": pooled(b_, "sale2", "hh")}}
out["승강기: 동네 승강기 비율별 전월세·매매 회전율"] = ev
# 월세 비중(월세가 많은 건물 = 임대 수요가 월세로 몰림)과 전세가율
Bt["wb"] = pd.cut(Bt["wolsePct"], [-1, 20, 40, 60, 80, 101], labels=["월세 20% 이하", "20~40", "40~60", "60~80", "80% 초과"])
out["월세 비중별 매매 회전율"] = {str(k): {"건물": int(len(G)), "매매 연 회전율%": pooled(G, "sale2", "hh")} for k, G in Bt.groupby("wb", observed=True) if len(G) >= 300}
# 전세가율(같은 건물 최근 순수 전세 ㎡당 보증금 ÷ 매매 ㎡당 가격, 2025~)
jj = rr[(rr["deal_date"] >= W2_from) & rr["jeonse"] & (rr["deposit"] > 0)].copy(); jj["ppm"] = jj["deposit"] / jj["size"]
sm = df[df["deal_date"] >= W2_from].groupby("bld")["ppm"].median().rename("salePpm"); jm = jj.groupby("bld").agg(jPpm=("ppm", "median"), jn=("ppm", "size"))
Bt = Bt.merge(sm, how="left", left_on="bld", right_index=True).merge(jm, how="left", left_on="bld", right_index=True)
Bt["jr"] = Bt["jPpm"] / Bt["salePpm"] * 100
Bt["jrb"] = pd.cut(Bt["jr"].where(Bt["jn"] >= 2), [0, 50, 60, 70, 80, 90, 300], labels=["50% 이하", "50~60", "60~70", "70~80", "80~90", "90% 초과"])
out["전세가율별 매매 회전율"] = {str(k): {"건물": int(len(G)), "매매 연 회전율%": pooled(G, "sale2", "hh")} for k, G in Bt.groupby("jrb", observed=True) if len(G) >= 300}
# 가격 프리미엄과의 관계: 건물별 같은 동·분기 대비 중앙 프리미엄(2023~)
D = df.copy(); D["q"] = D["ym"] // 100 * 10 + ((D["ym"] % 100 - 1) // 3); D["lp"] = np.log(D["ppm"]); D = D[D.groupby(["nb", "q"])["lp"].transform("size") >= 8].copy()
D["dev"] = D["lp"] - D.groupby(["nb", "q"])["lp"].transform("median"); bp = D.groupby("bld")["dev"].agg(["median", "size"]).rename(columns={"median": "prem", "size": "pn"})
Bt = Bt.merge(bp, how="left", left_on="bld", right_index=True)
Bt["rentAbsb"] = pd.cut(Bt["rentTurn"], [-.01, 1, 3, 6, 10, 1000], labels=["1% 미만", "1~3%", "3~6%", "6~10%", "10% 초과"])
pt = {}
for k, G in Bt[Bt["pn"] >= 2].groupby("rentAbsb", observed=True):
    if len(G) >= 300: pt[str(k)] = {"건물": int(len(G)), "동네 대비 프리미엄%": round((float(np.exp(G["prem"].median())) - 1) * 100, 1), "매매 연 회전율%": pooled(G, "sale2", "hh")}
out["전월세 회전율 구간별 가격 프리미엄·매매 회전율"] = pt
G = Bt[Bt["pn"] >= 2].dropna(subset=["jr"]); G = G[G["jn"] >= 2]
out["전세가율별 프리미엄"] = {str(k): {"건물": int(len(H)), "동네 대비 프리미엄%": round((float(np.exp(H["prem"].median())) - 1) * 100, 1)} for k, H in G.groupby("jrb", observed=True) if len(H) >= 300}
# 추가 설명력: 건물 단위 프리미엄을 (절대연식 구간+상대연식+승강기) 만으로 vs 전월세 지표를 더해서
M = Bt[(Bt["pn"] >= 2)].dropna(subset=["rel", "ageN"]).copy()
def fit(cols):
    A = np.column_stack([np.ones(len(M))] + cols); y = M["prem"].values; b, *_ = np.linalg.lstsq(A, y, rcond=None); return 1 - (y - A @ b).var() / y.var()
base = [(M["ageN"] <= 10).astype(float).values, ((M["ageN"] > 10) & (M["ageN"] <= 20)).astype(float).values, ((M["ageN"] > 20) & (M["ageN"] <= 30)).astype(float).values, M["rel"].values, M["elv"].astype(float).fillna(0).values]
r_base = fit(base); lr = np.log1p(M["rentTurn"].values)
out["건물 프리미엄 설명력"] = {"기본(연식·상대연식·승강기)": round(r_base, 4), "+전월세 회전율": round(fit(base + [lr]), 4), "+전월세 회전율+동네 안 전월세 순위": round(fit(base + [lr, M["rentRank"].values]), 4)}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
json.dump(out, open("villa-rent.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
