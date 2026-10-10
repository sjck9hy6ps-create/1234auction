"""
🏘️ 수도권 빌라 가격 요인 분석 (2026-10-10, 사용자: "빌라는 평형대·연식·승강기 유무가 가격 형성에 가장 중요, 10년 내 건물이 가장 거래가 활발, 구축일수록 마진이 커져야")
 A) 연식별 거래 활발도(세대당 연 거래 횟수)  B) 같은 동·같은 분기 평균 대비 ㎡당 가격 차이: 연식·평형대·승강기·층별  C) 예상매도가 오차를 연식·평형·승강기별로
결과 JSON 출력 → 앱의 빌라 보정과 마진 규칙(최소 2,000만원 + 구축일수록 추가)에 사용
"""
import os, json, importlib.util, re
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py"))
bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
URL = os.environ["SUPABASE_URL"].rstrip("/"); KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}
METRO = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def bunji_to_bunji(b):
    parts = str(b or "").split("-")
    try: m = int(parts[0])
    except Exception: return None
    try: s = int(parts[1]) if len(parts) > 1 else 0
    except Exception: s = 0
    return str(m).zfill(4), str(s or 0).zfill(4)


def fetch_buildings():
    rows, off = [], 0
    sel = "sigungu_cd,bjdong_cd,bun,ji,elv:title_json->rideElvtCnt,emg:title_json->emgenElvtCnt,grnd:title_json->grndFlrCnt,hh:title_json->hhldCnt,apr:title_json->>useAprDay,purp:title_json->>mainPurps"
    flt = "&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)"
    while True:
        r = requests.get(f"{URL}/rest/v1/building_info?select={sel}{flt}", headers={**HDR, "Range-Unit": "items", "Range": f"{off}-{off + 999}"}, timeout=120)
        if r.status_code not in (200, 206):
            print("building_info 오류", r.status_code, r.text[:200]); break
        d = r.json()
        if not d: break
        rows += d; off += 1000
        if off % 50000 == 0: print(f"  건축물대장 {off:,}행", flush=True)
        if len(d) < 1000: break
    print(f"건축물대장 {len(rows):,}건")
    return pd.DataFrame(rows)


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year",
                             extra_filter=f"&deal_date=gte.{bv.START}{METRO}")
    df = bv.prep(raw)
    print(f"빌라 거래 {len(df):,}건")
    # 좌표 캐시에서 법정동 코드 → 건축물대장 연결
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples()}
    print(f"좌표 캐시 {len(cmap):,}건")
    mnum = pd.to_numeric(df["main_num"], errors="coerce")
    snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    # 앱·웜업이 쓰는 키 두 가지: 본번 빈 값→0(buildCacheKey) / 원본 그대로(legacy, 빈 값은 그대로 빈 문자열)
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    cc2 = k_new.map(cmap)
    for alt in (k_leg, k_leg0):
        miss = cc2.isna()
        cc2 = cc2.where(~miss, alt.map(cmap))
    print("키 일치 샘플(좌표 캐시 키):", list(cmap.keys())[:3])
    df["sg"] = cc2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = cc2.map(lambda x: x[1] if isinstance(x, tuple) else None)
    bb = df["bunji"].map(bunji_to_bunji)
    df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
    print(f"좌표·번지 연결 {df['sg'].notna().mean()*100:.1f}% / {df['bun'].notna().mean()*100:.1f}%")
    B = fetch_buildings()
    if len(B):
        for c in ("elv", "emg", "grnd", "hh"): B[c] = pd.to_numeric(B[c], errors="coerce")
        B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
        B["elvAny"] = (B["elv"].fillna(0) + B["emg"].fillna(0)) > 0
        Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min")).reset_index()
        df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"])
    else:
        df["elv"] = np.nan; df["grnd"] = np.nan; df["hh"] = np.nan
    df["dyear"] = df["deal_date"] // 10000
    by = df["build_year"].where(df["build_year"].between(1960, 2026))
    df["age"] = (df["dyear"] - by)
    df["ageb"] = pd.cut(df["age"], [-5, 10, 20, 30, 80], labels=["10년 이내", "11~20년", "21~30년", "31년+"])
    df["sizeb"] = pd.cut(df["size"], [0, 40, 50, 60, 70, 85, 200], labels=["40㎡↓", "40~50", "50~60", "60~70", "70~85", "85㎡↑"])
    print(f"승강기 정보 연결 {df['elv'].notna().mean()*100:.1f}% (승강기 있음 {df['elv'].fillna(False).astype(bool).mean()*100:.1f}%)")
    out = {}
    # A) 활발도
    rec = df[df["deal_date"] >= 20250101]
    out["shareByAge"] = {k: round(float(v) * 100, 1) for k, v in rec["ageb"].value_counts(normalize=True).sort_index().items()}
    X = rec[rec["hh"] > 0].copy()
    if len(X):
        g = X.groupby(["sg", "bj", "bun", "ji"]).agg(n=("price", "size"), hh=("hh", "first"), ageb=("ageb", lambda s: s.mode().iloc[0] if len(s.dropna()) else None)).dropna(subset=["ageb"])
        t = g.groupby("ageb").apply(lambda G: float(G["n"].sum() / G["hh"].sum() / 1.75 * 100))
        out["turnoverPctPerYear"] = {str(k): round(float(v), 2) for k, v in t.items()}
        out["turnoverBuildings"] = int(len(g))
    # B) 같은 동·분기 대비 ㎡당 가격
    D = df[(df["deal_date"] >= 20230101)].copy()
    D["q"] = D["ym"] // 100 * 10 + ((D["ym"] % 100 - 1) // 3)
    D["lp"] = np.log(D["ppm"])
    D["dev"] = D["lp"] - D.groupby(["dk", "q"])["lp"].transform("median")
    D = D[D.groupby(["dk", "q"])["lp"].transform("size") >= 8]
    def tab(col, sub=None):
        S = D if sub is None else sub
        r = S.groupby(col)["dev"].agg(["size", "median"]); r = r[r["size"] >= 300]
        return {str(k): {"n": int(v["size"]), "premiumPct": round((float(np.exp(v["median"])) - 1) * 100, 1)} for k, v in r.iterrows()}
    out["byAge"] = tab("ageb"); out["bySize"] = tab("sizeb")
    D["flg"] = pd.cut(D["floor"], [-9, 0, 1, 2, 3, 4, 99], labels=["지하", "1층", "2층", "3층", "4층", "5층+"])
    out["byFloor"] = tab("flg")
    E = D[D["elv"].notna() & (D["grnd"] >= 4)].copy()
    E["elvb"] = np.where(E["elv"].astype(bool), "승강기 있음", "승강기 없음")
    out["elevator_4F+"] = tab("elvb", E)
    out["elevator_by_floor_4F+"] = {str(k): v for k, v in E.groupby("flg").apply(lambda G: {"n": int(len(G)), "elvPremiumPct": round((float(np.exp(G[G["elv"].astype(bool)]["dev"].median() - G[~G["elv"].astype(bool)]["dev"].median())) - 1) * 100, 1) if G["elv"].astype(bool).sum() > 150 and (~G["elv"].astype(bool)).sum() > 150 else None}).items()}
    out["elevator_by_age_4F+"] = {str(k): v for k, v in E.groupby("ageb").apply(lambda G: {"n": int(len(G)), "elvPremiumPct": round((float(np.exp(G[G["elv"].astype(bool)]["dev"].median() - G[~G["elv"].astype(bool)]["dev"].median())) - 1) * 100, 1) if G["elv"].astype(bool).sum() > 150 and (~G["elv"].astype(bool)).sum() > 150 else None}).items()}
    out["elevatorShareOfTrades"] = round(float(df[df["grnd"] >= 4]["elv"].astype(bool).mean()) * 100, 1) if (df["grnd"] >= 4).any() else None
    print(json.dumps(out, ensure_ascii=False, indent=1))
    # B2) 같은 건물 안에서 본 층별 가격 차이(건물 중앙값 대비) - 승강기 있음/없음 따로 (사용자: 승강기 없으면 2~3층이 로열 → 1층 → 고층, 있으면 1층이 비인기)
    W = df[(df["deal_date"] >= 20230101) & df["elv"].notna() & (df["grnd"] >= 3)].copy()
    W["elvc"] = np.where(W["elv"].astype(bool), 1, -1)
    W["sb"] = (W["size"] / 6).round()
    W["lp"] = np.log(W["ppm"])
    W["bkey"] = W["bld"] + "|" + W["sb"].astype(str)
    cnt = W.groupby("bkey")["lp"].transform("size")
    nfl = W.groupby("bkey")["floor"].transform("nunique")
    W = W[(cnt >= 6) & (nfl >= 3)]
    W["dev"] = W["lp"] - W.groupby("bkey")["lp"].transform("median")
    W["flg"] = pd.cut(W["floor"], [-9, 0, 1, 2, 3, 4, 99], labels=["지하", "1층", "2층", "3층", "4층", "5층+"])
    fp = {}
    for ec, lab in ((1, "승강기 있음"), (-1, "승강기 없음")):
        S = W[W["elvc"] == ec]
        r = S.groupby("flg")["dev"].agg(["size", "median"])
        fp[lab] = {str(k): {"n": int(v["size"]), "pct": round((float(np.exp(v["median"])) - 1) * 100, 1)} for k, v in r.iterrows() if v["size"] >= 200}
    out["withinBuildingFloor"] = fp
    out["withinBuildingFloorN"] = int(len(W))
    print("건물 안 층별 차이:", json.dumps(fp, ensure_ascii=False, indent=1))
    # 층 보정 승수(건물 중앙값 대비) - 학습 구간(2025 이전)으로 만들어 2025~ 시험에서 같은 건물 거래 보정 효과 확인
    Wtr = W[W["deal_date"] < 20250101]
    mult = {}
    for ec in (1, -1):
        S = Wtr[Wtr["elvc"] == ec]
        g = S.groupby(S["floor"].clip(lower=0, upper=5).astype(int))["dev"].agg(["size", "median"])
        mult[ec] = {int(k): float(np.exp(v["median"])) for k, v in g.iterrows() if v["size"] >= 150}
    def floor_adj(ec, f):
        m = mult.get(ec) or {}
        k = int(min(max(f, 0), 5))
        return m.get(k, 1.0)
    df["elvc"] = np.where(df["elv"].isna(), 0, np.where(df["elv"].astype(bool), 1, -1))
    T0 = df[df["deal_date"] >= bv.TEST_FROM]
    if len(T0) > 25000: T0 = T0.sample(25000, random_state=11)
    Eb = bv.estimate(df, T0)
    Ef = bv.estimate(df, T0, floor_adj=floor_adj)
    def ev(E, tadj):
        X = E[(E["q"] == 0.5) & (E["tadj"] == tadj)].copy(); X["err"] = X["est"] / X["actual"] - 1
        return X
    Xb, Xf = ev(Eb, 0), ev(Ef, 1)
    both = Xb.merge(Xf, on="i", suffixes=("_b", "_f"))
    own = both[both["lvl_b"].isin(["건물3+", "건물1~2+동", "건물1~2"])]
    el = df.loc[own["i"].values, "elvc"].values
    for lab, msk in (("같은 건물 거래 있음 전체", np.ones(len(own), bool)), ("승강기 있음", el == 1), ("승강기 없음", el == -1)):
        o = own[msk]
        if len(o) > 200:
            print(f"층 보정(같은 건물) {lab} n={len(o)}: 보통 오차 {o['err_b'].abs().median()*100:.2f}% → {o['err_f'].abs().median()*100:.2f}%  ±10% {100*(o['err_b'].abs()<=.1).mean():.1f}% → {100*(o['err_f'].abs()<=.1).mean():.1f}%")
            out.setdefault("floorAdjTest", {})[lab] = {"n": int(len(o)), "before": round(float(o['err_b'].abs().median()) * 100, 2), "after": round(float(o['err_f'].abs().median()) * 100, 2)}
    out["floorMult"] = {str(k): {str(a): round(b, 3) for a, b in v.items()} for k, v in mult.items()}
    # C) 오차 - 연식·평형·승강기별
    T = df[df["deal_date"] >= bv.TEST_FROM]
    if len(T) > bv.N_TEST: T = T.sample(bv.N_TEST, random_state=7)
    E2 = bv.estimate(df, T)
    E2 = E2[(E2["tadj"] == 0) & (E2["q"] == 0.5)].copy()
    E2["err"] = E2["est"] / E2["actual"] - 1
    for c in ("ageb", "sizeb", "elv", "grnd"): E2[c] = df.loc[E2["i"].values, c].values
    E2["price"] = E2["actual"]
    def er(G):
        a = G["err"].abs()
        return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "p10": round(float(G["err"].quantile(.1)) * 100, 1), "p90": round(float(G["err"].quantile(.9)) * 100, 1),
                "biasPct": round(float(G["err"].median()) * 100, 1), "medPriceMan": round(float(G["price"].median()))}
    res = {"all": er(E2)}
    res["byAge"] = {str(k): er(G) for k, G in E2.groupby("ageb") if len(G) >= 300}
    res["bySize"] = {str(k): er(G) for k, G in E2.groupby("sizeb") if len(G) >= 300}
    Ee = E2[E2["elv"].notna() & (E2["grnd"] >= 4)]
    res["byElevator_4F+"] = {("승강기 있음" if k else "승강기 없음"): er(G) for k, G in Ee.groupby(Ee["elv"].astype(bool)) if len(G) >= 300}
    res["byLevelAge"] = {f"{a}|{l}": er(G) for (a, l), G in E2.groupby(["ageb", "lvl"]) if len(G) >= 300}
    print("오차:", json.dumps(res, ensure_ascii=False, indent=1))
    out["errors"] = res
    json.dump(out, open("villa-factors.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
