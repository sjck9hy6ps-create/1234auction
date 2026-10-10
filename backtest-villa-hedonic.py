"""
🏘️ 빌라 예상매도가 보정 모델 백테스트 (2026-10-10, 사용자: "건축물대장 기준 연식·평형·층·면적·승강기 등 주요 요인을 직접 비교")
기존 예상(건물→동→시군구, 30일 전까지 자료)을 기준으로 두고, 건축물대장(승강기·지상층수·세대수·사용승인연)·층·면적·연식·그 동의 최근 시세를 넣은
그래디언트 부스팅으로 '기존 예상의 오차(로그 비율)'를 학습해 보정. 학습: 2023~2024 거래, 시험: 2025~ 거래(시간 순서 분리).
결과: 기존 vs 보정 오차·±10%·±20%, 건물 대장 정보가 있는 거래만 따로, 변수 중요도(순열)
"""
import os, json, importlib.util
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py")
avm = bv.avm
N_TRAIN = int(os.environ.get("N_TRAIN", "25000")); N_TEST = int(os.environ.get("N_TEST", "15000"))
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples()}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    c2 = k_new.map(cmap)
    for alt in (k_leg, k_leg0): c2 = c2.where(~c2.isna(), alt.map(cmap))
    df["sg"] = c2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = c2.map(lambda x: x[1] if isinstance(x, tuple) else None)
    bb = df["bunji"].map(vf.bunji_to_bunji); df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
    B = vf.fetch_buildings()
    if len(B):
        for c in ("elv", "emg", "grnd", "hh"): B[c] = pd.to_numeric(B[c], errors="coerce")
        B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
        B["elvAny"] = ((B["elv"].fillna(0) + B["emg"].fillna(0)) > 0).astype(float)
        Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min")).reset_index()
        df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"], suffixes=("", "_b"))
    else:
        for c in ("elv", "grnd", "hh", "apr"): df[c] = np.nan
    df = df.reset_index(drop=True)
    print(f"거래 {len(df):,}건, 대장 연결 {df['elv'].notna().mean() * 100:.1f}%")
    tr_all = df[(df["deal_date"] >= 20230101) & (df["deal_date"] < 20250101)]; te_all = df[df["deal_date"] >= 20250101]
    TR = tr_all.sample(min(N_TRAIN, len(tr_all)), random_state=3); TE = te_all.sample(min(N_TEST, len(te_all)), random_state=7)
    both = pd.concat([TR, TE]); E = bv.estimate(df, both); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    lv = {"건물3+": 0, "건물1~2+동": 1, "건물1~2": 2, "동5+": 3, "동1~4": 4, "시군구": 5}
    # 그 동의 최근 시세(30일 전까지 12개월 ㎡당 중앙값) - 시점 보정용 특성
    def feats(D):
        D = D[D.index.isin(E.index)].copy()
        D["base"] = E.loc[D.index, "est"].values; D["lvl"] = E.loc[D.index, "lvl"].map(lv).values
        D["lb"] = np.log(D["base"] / D["size"])
        D["fl"] = D["floor"].fillna(3).clip(-1, 15)
        D["age"] = (D["deal_date"] // 10000) - D["build_year"].where(D["build_year"].between(1960, 2026))
        D["age_b"] = (D["deal_date"] // 10000) - D["apr"]
        D["ls"] = np.log(D["size"]); D["t"] = D["day"] / 365.0
        D["reg"] = D["region"].astype("category").cat.codes
        D["y"] = np.log(D["price"] / D["base"])
        return D
    Ftr, Fte = feats(TR), feats(TE)
    cols = ["lb", "lvl", "ls", "fl", "age", "age_b", "elv", "grnd", "hh", "t"]
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=5, min_samples_leaf=40, l2_regularization=1.0, random_state=1)
    m.fit(Ftr[cols], Ftr["y"])
    pred = m.predict(Fte[cols]); Fte["est2"] = Fte["base"] * np.exp(pred)
    def stat(G, col):
        e = G[col] / G["price"] - 1; a = e.abs()
        return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "within20Pct": round(float((a <= .2).mean()) * 100, 1),
                "p10": round(float(e.quantile(.1)) * 100, 1), "p90": round(float(e.quantile(.9)) * 100, 1), "biasPct": round(float(e.median()) * 100, 1)}
    out = {"학습 n": int(len(Ftr)), "시험 n": int(len(Fte)), "대장 정보 있는 시험 비율%": round(float(Fte["elv"].notna().mean()) * 100, 1)}
    out["기존"] = stat(Fte, "base"); out["보정"] = stat(Fte, "est2")
    has = Fte[Fte["elv"].notna()]; no = Fte[Fte["elv"].isna()]
    out["대장 있음 - 기존"] = stat(has, "base"); out["대장 있음 - 보정"] = stat(has, "est2")
    out["대장 없음 - 기존"] = stat(no, "base"); out["대장 없음 - 보정"] = stat(no, "est2")
    for l, G in Fte.groupby("lvl"):
        nm = [k for k, v in lv.items() if v == l][0]
        if len(G) >= 50: out["단계 " + nm] = {"기존": stat(G, "base"), "보정": stat(G, "est2")}
    pi = permutation_importance(m, Fte[cols], Fte["y"], n_repeats=3, random_state=1, scoring="neg_mean_absolute_error")
    out["변수 중요도(오차 증가)"] = {c: round(float(v), 4) for c, v in sorted(zip(cols, pi.importances_mean), key=lambda x: -x[1])}
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-villa-hedonic.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
