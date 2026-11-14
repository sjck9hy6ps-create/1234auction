"""🏘️ 빌라 '동네 안 상대 조건' 시험(2026-11-14, 측정 전용) - 사용자: 절대 연식이 아니라 그 동네에서 상대적으로 새 건물·승강기가 드문 동네의 승강기 건물이 인기 있을 것
동네 = 법정동(건축물대장 시군구·법정동코드). 신축(사용승인 후 4년 이내)은 제외(앱 규칙). 상대 연식 = 같은 법정동 연립·다세대 건물 중 이 건물보다 오래된 건물의 비율(0=가장 오래됨 ~ 1=가장 새로움).
시험: ① 같은 동·분기 대비 ㎡당 가격(프리미엄) ② 세대당 거래 횟수(회전율) 을 절대 연식과 상대 연식으로 각각 설명해 보고, 옛 동네·새 동네에서 기울기가 어느 쪽 기준으로 더 일정한지 비교
③ 승강기: 동네 승강기 보유 비율이 낮을수록 승강기 건물의 프리미엄·회전율이 큰지"""
import os, json, importlib.util
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("afv", os.path.join(HERE, "analyze-villa-factors.py")); afv = importlib.util.module_from_spec(_s); _s.loader.exec_module(afv)
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
B = afv.fetch_buildings()
for c in ("elv", "emg", "grnd", "hh"): B[c] = pd.to_numeric(B[c], errors="coerce")
B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
B["elvAny"] = (B["elv"].fillna(0) + B["emg"].fillna(0)) > 0
B = B[B["purp"].astype(str).str.contains("다세대|연립", na=False) & B["apr"].between(1960, 2026)].copy()
Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min")).reset_index()
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
out = {"trades": int(len(df)), "buildings": int(df["bld"].nunique()), "neighborhoods": int(df["nb"].nunique())}
# ① 프리미엄: 같은 법정동·분기 대비
D = df.copy(); D["q"] = D["ym"] // 100 * 10 + ((D["ym"] % 100 - 1) // 3); D["lp"] = np.log(D["ppm"])
D = D[D.groupby(["nb", "q"])["lp"].transform("size") >= 8].copy()
D["dev"] = D["lp"] - D.groupby(["nb", "q"])["lp"].transform("median")
D["flg"] = pd.cut(D["floor"], [-9, 0, 1, 2, 3, 4, 99], labels=False); D["szb"] = pd.cut(D["size"], [0, 40, 50, 60, 70, 85, 200], labels=False)
def design(X, extra):
    cols = [np.ones(len(X))]
    for c in ("flg", "szb"):
        for v in sorted(X[c].dropna().unique())[1:]: cols.append((X[c] == v).astype(float).values)
    for e in extra: cols.append(np.asarray(e, float))
    return np.column_stack(cols)
def r2(X, extra):
    A = design(X, extra); y = X["dev"].values; b, *_ = np.linalg.lstsq(A, y, rcond=None); res = y - A @ b
    return 1 - res.var() / y.var(), b
D = D.dropna(subset=["flg", "szb", "rel"]).copy()
ab = [(D["ageA"] <= 10).astype(float), ((D["ageA"] > 10) & (D["ageA"] <= 20)).astype(float), ((D["ageA"] > 20) & (D["ageA"] <= 30)).astype(float)]
res = {}
r0, _ = r2(D, []); rA, _ = r2(D, ab); rR, bR = r2(D, [D["rel"].values]); rAR, _ = r2(D, ab + [D["rel"].values])
res["R2"] = {"층·평형만": round(r0, 4), "+절대연식": round(rA, 4), "+상대연식": round(rR, 4), "+둘다": round(rAR, 4)}
res["상대연식 가장 새로움 vs 가장 오래됨 프리미엄%"] = round((float(np.exp(bR[-1])) - 1) * 100, 1)
# 동네 연식 구성별 기울기: 절대(연) vs 상대(0~1)
D["nbType"] = pd.cut(D["nbMed"], [1900, 1995, 2005, 2030], labels=["옛 동네(중앙 사용승인 1995 이전)", "중간(1996~2005)", "새 동네(2006~)"])
sl = {}
for k, g in D.groupby("nbType", observed=True):
    if len(g) < 3000: continue
    A = design(g, [g["ageA"].values]); b, *_ = np.linalg.lstsq(A, g["dev"].values, rcond=None); sa = (float(np.exp(b[-1])) - 1) * 100
    A2 = design(g, [g["rel"].values]); b2, *_ = np.linalg.lstsq(A2, g["dev"].values, rcond=None); sr = (float(np.exp(b2[-1])) - 1) * 100
    sl[str(k)] = {"n": int(len(g)), "연식 1년당 가격%": round(sa, 2), "상대순위 새로움 쪽 끝까지 가격%": round(sr, 1)}
res["동네 유형별 기울기"] = sl
# 상대 연식 구간별 프리미엄
D["relb"] = pd.cut(D["rel"], [0, .2, .4, .6, .8, 1.0001], labels=["가장 오래된 20%", "20~40", "40~60", "60~80", "가장 새로운 20%"])
t = D.groupby("relb", observed=True)["dev"].agg(["size", "median"]); res["상대연식 구간별 프리미엄"] = {str(k): {"n": int(v["size"]), "premiumPct": round((float(np.exp(v["median"])) - 1) * 100, 1)} for k, v in t.iterrows()}
# 같은 절대 연식(15~25년)인데 동네에서 위치가 다를 때
for lo, hi_ in ((10, 20), (20, 30)):
    G = D[(D["ageA"] > lo) & (D["ageA"] <= hi_)].copy(); G["nbT"] = pd.cut(G["rel"], [0, .33, .66, 1.0001], labels=["동네에서 오래된 편", "중간", "동네에서 새로운 편"])
    t = G.groupby("nbT", observed=True)["dev"].agg(["size", "median"]); res[f"절대연식 {lo+1}~{hi_}년인 건물 중 동네 위치별 프리미엄"] = {str(k): {"n": int(v["size"]), "premiumPct": round((float(np.exp(v["median"])) - 1) * 100, 1)} for k, v in t.iterrows()}
out["premium"] = res
# ② 회전율(건물 단위): 2025~ 거래 / 세대수
R = df[(df["deal_date"] >= 20250101) & (df["hh"] >= 4)]
g = R.groupby("bld").agg(n=("price", "size"), hh=("hh", "first"), ageA=("ageA", "median"), rel=("rel", "first"), nbMed=("nbMed", "first"), elv=("elv", "first"), grnd=("grnd", "first"), elvShare=("elvShare", "first")).reset_index()
# 거래 0건 건물도 포함해야 편향이 없음: 대장 건물 중 같은 동네 건물 전체로 회전율 계산(거래 없는 건물은 0)
Z = Bg[(Bg["hh"] >= 4)].copy(); cnt = df[df["deal_date"] >= 20250101].groupby(["sg", "bj", "bun", "ji"]).size().rename("n").reset_index()
Z = Z.merge(cnt, how="left", left_on=["sigungu_cd", "bjdong_cd", "bun", "ji"], right_on=["sg", "bj", "bun", "ji"]); Z["n"] = Z["n"].fillna(0)
Z["ageN"] = 2026 - Z["apr"]; Z = Z[Z["ageN"] >= 5]; Z["turn"] = Z["n"] / Z["hh"] / 1.75 * 100
Z["relb"] = pd.cut(Z["rel"], [0, .2, .4, .6, .8, 1.0001], labels=["가장 오래된 20%", "20~40", "40~60", "60~80", "가장 새로운 20%"])
Z["ageb"] = pd.cut(Z["ageN"], [4, 10, 20, 30, 80], labels=["5~10년", "11~20년", "21~30년", "31년+"])
tt = Z.groupby("relb", observed=True).apply(lambda G: {"건물": int(len(G)), "연 회전율%": round(float(G["n"].sum() / G["hh"].sum() / 1.75 * 100), 2)}); out["turnoverByRel"] = {str(k): v for k, v in tt.items()}
tt = Z.groupby("ageb", observed=True).apply(lambda G: {"건물": int(len(G)), "연 회전율%": round(float(G["n"].sum() / G["hh"].sum() / 1.75 * 100), 2)}); out["turnoverByAge"] = {str(k): v for k, v in tt.items()}
Z["nbType"] = pd.cut(Z["nbMed"], [1900, 1995, 2005, 2030], labels=["옛 동네", "중간", "새 동네"])
mat = {}
for k, G in Z.groupby("nbType", observed=True):
    mat[str(k)] = {str(r): {"건물": int(len(H)), "연 회전율%": round(float(H["n"].sum() / H["hh"].sum() / 1.75 * 100), 2)} for r, H in G.groupby("relb", observed=True) if len(H) >= 200}
out["turnoverByNbTypeRel"] = mat
mat2 = {}
for k, G in Z.groupby("nbType", observed=True):
    mat2[str(k)] = {str(r): {"건물": int(len(H)), "연 회전율%": round(float(H["n"].sum() / H["hh"].sum() / 1.75 * 100), 2)} for r, H in G.groupby("ageb", observed=True) if len(H) >= 200}
out["turnoverByNbTypeAge"] = mat2
# ③ 승강기: 동네 승강기 비율별 승강기 건물 효과(4층 이상)
E = D[(D["grnd"] >= 4) & D["elvShare"].notna() & (D["nHigh"] >= 8)].copy(); E["elvF"] = E["elv"].astype(bool)
E["shb"] = pd.cut(E["elvShare"], [-.01, .15, .4, .7, 1.01], labels=["동네 승강기 건물 15% 이하", "15~40%", "40~70%", "70% 초과"])
ev = {}
for k, g in E.groupby("shb", observed=True):
    a, b_ = g[g["elvF"]], g[~g["elvF"]]
    if len(a) >= 300 and len(b_) >= 300: ev[str(k)] = {"승강기 있음 n": int(len(a)), "없음 n": int(len(b_)), "승강기 건물 프리미엄%": round((float(np.exp(a["dev"].median() - b_["dev"].median())) - 1) * 100, 1)}
out["elevatorPremiumByNbShare"] = ev
Zh = Z[(Z["grnd"] >= 4)].copy(); Zh["shb"] = pd.cut(Zh["elvShare"], [-.01, .15, .4, .7, 1.01], labels=["15% 이하", "15~40%", "40~70%", "70% 초과"]); ev2 = {}
for k, G in Zh.groupby("shb", observed=True):
    a, b_ = G[G["elv"].astype(bool)], G[~G["elv"].astype(bool)]
    if len(a) >= 100 and len(b_) >= 100: ev2[str(k)] = {"승강기 있음": {"건물": int(len(a)), "연 회전율%": round(float(a["n"].sum() / a["hh"].sum() / 1.75 * 100), 2)}, "없음": {"건물": int(len(b_)), "연 회전율%": round(float(b_["n"].sum() / b_["hh"].sum() / 1.75 * 100), 2)}}
out["elevatorTurnoverByNbShare"] = ev2
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(out, open("villa-relative.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
