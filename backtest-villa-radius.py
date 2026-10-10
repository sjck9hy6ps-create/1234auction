"""
🏘️ 빌라 예상매도가: '행정구역(건물→동→시군구)' vs '반경(가까운 거래)' 백테스트 (2026-10-10)
사용자: "빌라는 단지거래가 없고 같은 평형·연식도 없음. 지역을 넓히는 건 의미 없고 반경이 중요 - 그 동네에서 비슷한 금액·평형 매물을 보게 됨"
방법: 거래마다 '그 거래 30일 전까지 자료만'으로 예측해 실제가와 비교. 좌표는 좌표 캐시(complex_coords)와 건물 키로 연결.
  기준선: 기존 방식(건물 24개월 → 같은 동 12개월 → 시군구)
  반경 방식: 반경 300/500/1000m + 면적 ±8㎡ / ±15㎡, 거리·면적·연식·시점 가중(커널), 반경 넓혀가기(300→500→1000→1500m)
결과: 방식별 적용 가능 비율·오차·±10%·±20%·상하위 10%·편향, 기존 단계별(건물3+ 등) 하위집단, 건물 거래가 없는 경우만 따로
"""
import os, json, importlib.util
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py"))
bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
N_TEST = int(os.environ.get("N_TEST", "15000"))
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def wq(v, w, q=0.5):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return float(v[min(np.searchsorted(c, q), len(v) - 1)])


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year",
                             extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw)
    print(f"빌라 거래 {len(df):,}건")
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    co = k_new.map(cmap)
    for alt in (k_leg, k_leg0):
        co = co.where(~co.isna(), alt.map(cmap))
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    print(f"좌표 연결 {df['lat'].notna().mean() * 100:.1f}%")
    D = df[df["lat"].notna()].reset_index()  # 'index' = df 원래 행 번호
    X = np.c_[D["lat"].values * 111.0, D["lon"].values * 111.0 * np.cos(np.radians(37.5))]
    tree = cKDTree(X)
    day, size, ppm, by = D["day"].values, D["size"].values, D["ppm"].values, D["build_year"].values.astype(float)
    T = D[D["deal_date"] >= bv.TEST_FROM]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    print(f"시험 {len(T):,}건")
    # 기준선(기존 방식) - 같은 시험 표본
    Tdf = df.loc[T["index"].values]
    E = bv.estimate(df, Tdf)
    E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    res = {}  # 방식 → [(원래행, est)]
    methods = ["r300_8", "r500_8", "r1000_8", "r500_15", "kernel", "adaptive"]
    out = {m: {} for m in methods}
    for rr in T.itertuples():
        i = rr.Index  # D 내 위치
        dc = rr.day - 30
        nb = np.array(tree.query_ball_point(X[i], 1.5), dtype=int)
        nb = nb[(nb != i)]
        if not len(nb): continue
        ok = (day[nb] <= dc) & (day[nb] > dc - 365)
        nb = nb[ok]
        if not len(nb): continue
        dist = np.linalg.norm(X[nb] - X[i], axis=1) * 1000
        dsz = np.abs(size[nb] - rr.size)
        age = (dc - day[nb])
        dby = np.abs(by[nb] - rr.build_year) if np.isfinite(rr.build_year) else np.full(len(nb), np.nan)
        wt = np.exp(-age / 365.0) * np.exp(-dsz / 10.0)

        def fixed(R, tol):
            m = (dist <= R) & (dsz <= tol)
            return wq(ppm[nb][m], wt[m]) * rr.size if m.sum() >= 5 else None
        out["r300_8"][rr.index] = fixed(300, 8)
        out["r500_8"][rr.index] = fixed(500, 8)
        out["r1000_8"][rr.index] = fixed(1000, 8)
        out["r500_15"][rr.index] = fixed(500, 15)
        # 커널: 거리·면적·연식 모두 연속 가중
        kw = wt * np.exp(-dist / 400.0) * np.where(np.isnan(dby), 0.8, np.exp(-dby / 10.0))
        mk = dsz <= 25
        out["kernel"][rr.index] = wq(ppm[nb][mk], kw[mk]) * rr.size if mk.sum() >= 5 else None
        est = None
        for R in (300, 500, 1000, 1500):
            m = (dist <= R) & (dsz <= 10)
            if m.sum() >= 5:
                est = wq(ppm[nb][m], wt[m]) * rr.size; break
        out["adaptive"][rr.index] = est
    # 평가 (out의 키 = df 원래 행 번호)
    rows = [(m, int(o), est) for m in methods for o, est in out[m].items()]
    R = pd.DataFrame(rows, columns=["m", "orig", "est"])
    R["actual"] = df.loc[R["orig"].values, "price"].values
    lvl = E["lvl"].to_dict(); basest = E["est"].to_dict()
    R["lvl"] = R["orig"].map(lvl)
    B = pd.DataFrame({"orig": list(basest.keys()), "est": list(basest.values())})
    B["m"] = "기존(건물→동→시군구)"; B["actual"] = df.loc[B["orig"].values, "price"].values; B["lvl"] = B["orig"].map(lvl)
    A = pd.concat([R, B], ignore_index=True)
    A["covered"] = A["est"].notna()
    summ = {}
    def stat(G):
        G = G[G["est"].notna()]
        if len(G) < 30: return None
        e = G["est"] / G["actual"] - 1; a = e.abs()
        return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "within20Pct": round(float((a <= .2).mean()) * 100, 1),
                "p10": round(float(e.quantile(.1)) * 100, 1), "p90": round(float(e.quantile(.9)) * 100, 1), "biasPct": round(float(e.median()) * 100, 1)}
    tot = len(T)
    for m, G in A.groupby("m"):
        summ[m] = {"전체": {**(stat(G) or {}), "적용비율%": round(float(G["est"].notna().sum()) / tot * 100, 1)}}
        for l, GG in G.groupby("lvl"):
            s = stat(GG)
            if s: summ[m][l] = s
        weak = G[G["lvl"].isin(["건물1~2", "동5+", "동1~4", "시군구", "건물1~2+동"])]
        s = stat(weak)
        if s: summ[m]["건물 근거 약한 경우"] = s
    # 하이브리드: 건물3+ 이면 기존, 아니면 반경 adaptive(없으면 기존)
    ad = out["adaptive"]; hy = []
    for orig in T["index"].astype(int):
        if orig not in basest: continue
        e = basest[orig] if lvl.get(orig) == "건물3+" else (ad.get(orig) or basest[orig])
        hy.append((orig, e, lvl.get(orig)))
    H = pd.DataFrame(hy, columns=["orig", "est", "lvl"]); H["actual"] = df.loc[H["orig"].values, "price"].values
    summ["하이브리드(건물3+ 기존, 나머지 반경)"] = {"전체": stat(H), "건물 근거 약한 경우": stat(H[H["lvl"] != "건물3+"])}
    txt = json.dumps(summ, ensure_ascii=False, indent=1)
    print(txt)
    json.dump(summ, open("backtest-villa-radius.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
