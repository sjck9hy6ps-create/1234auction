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
    mn = pd.to_numeric(df["main_num"], errors="coerce").fillna(0).astype(int)
    sn = df["sub_num"].astype(str).replace({"nan": "", "None": "", "<NA>": ""})
    sn = sn.where(~sn.str.fullmatch(r"\d+\.0"), sn.str.replace(r"\.0$", "", regex=True))
    ck = (df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|" + mn.astype(str) + "|" + sn).str.lower()
    cc2 = ck.map(cmap)
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
