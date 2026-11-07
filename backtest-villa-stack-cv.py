"""
🏘️ 수도권 빌라 '종합 평가' 시험 (2026-11-07, 사용자: 기준·상수로 조정하면 오차 편차가 생긴다 - 여러 조건을 종합평가해 가장 좋은 값을 찾아야 한다)
방법: 거래마다 '30일 전까지 자료만'으로 여러 추정(기존 단계식·건물·동 하드·동 가중·시군구)을 만들고, 근거 건수·마지막 거래 경과일·가격 흩어짐·층·연식·승강기·세대수·지역을 함께 넣어
  ① 기존 추정을 얼마나 보정할지(점 추정)  ② 이 물건이 얼마나 틀릴 수 있는지(하위 10/25/50% 분위)를 학습한다.
시간순 분리를 3번 반복(교차 시간 검증): 2023→2024, 2024→2025, 2025→2026 (학습 때 시험 자료를 못 봄). 기존 방식 = 현재 앱처럼 '단계(lvl)×광역' 칸별 분위수.
채점: 점 오차(중앙값·±10%·±20%), 하위 분위 포함률(25% 분위가 실제 가격을 얼마나 덮나)과 평균 여유폭, 핀볼 손실(분위 예측의 정식 점수).
"""
import os, json, importlib.util
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py")
avm = bv.avm
N_TEST = int(os.environ.get("N_TEST", "48000"))
SPLIT = 20260101
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])


def fcls(f):
    f = np.where(np.isnan(f), 3, f)
    return np.where(f <= 0, 0, np.where(f <= 2, 1, np.where(f <= 4, 2, 3)))


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
    for c in ("elv", "emg", "grnd", "hh"): B[c] = pd.to_numeric(B.get(c), errors="coerce")
    B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
    B["elvAny"] = ((B["elv"].fillna(0) + B["emg"].fillna(0)) > 0).astype(float)
    Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min")).reset_index()
    df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"], suffixes=("", "_b")).reset_index(drop=True)
    df["by2"] = df["build_year"].where(df["build_year"].between(1960, 2026), df["apr"].where(df["apr"].between(1960, 2026)))
    print(f"거래 {len(df):,}건, 대장 연결(승강기) {df['elv'].notna().mean() * 100:.1f}%")
    T = df[df["deal_date"] >= 20230101]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    E = bv.estimate(df, T); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    T = T[T.index.isin(E.index)].copy()
    print(f"시험·학습 대상 {len(T):,}건")

    def mk(key):
        return {k: (g["day"].values, g["size"].values, g["ppm"].values, g["by2"].values.astype(float), g["elv"].values.astype(float), fcls(g["floor"].values.astype(float)))
                for k, g in df.groupby(key)}
    G = {"bld": mk("bld"), "dk": mk("dk"), "region": mk("region")}

    def comp(kc, key, r, days, stol, yb_hard=None, wt=None):
        t = G[kc].get(key)
        if t is None: return None
        d, sz, pp, yy, ee, ff = t; dc = r.day - 30
        hi = np.searchsorted(d, dc, side="right"); lo = np.searchsorted(d, dc - days, side="left")
        if hi <= lo: return None
        s = sz[lo:hi]; m = np.abs(s - r.size) <= stol
        if yb_hard is not None and np.isfinite(r.by2): m &= (np.isnan(yy[lo:hi]) | (np.abs(yy[lo:hi] - r.by2) <= yb_hard))
        if not m.any(): return None
        age = dc - d[lo:hi][m]; w = np.exp(-age / (wt or 365.0)) * np.exp(-np.abs(s[m] - r.size) / 10.0)
        return pp[lo:hi][m], w, age, yy[lo:hi][m], ee[lo:hi][m], ff[lo:hi][m]

    rows = []
    for r in T.itertuples():
        x = {"i": r.Index, "actual": r.price, "base": E.loc[r.Index, "est"], "lvl": E.loc[r.Index, "lvl"]}
        c = comp("bld", r.bld, r, 730, 6)
        x["n_bld"] = 0 if c is None else len(c[0]); x["e_bld"] = wmed(c[0], c[1]) * r.size if c else np.nan
        x["age_bld"] = float(c[2].min()) if c else np.nan
        c = comp("dk", r.dk, r, 365, 8, 5)
        x["n_dong"] = 0 if c is None else len(c[0]); x["e_dong"] = wmed(c[0], c[1]) * r.size if (c and len(c[0]) >= 3) else np.nan
        x["age_dong"] = float(c[2].min()) if c else np.nan
        x["disp"] = float(np.std(np.log(c[0]))) if (c and len(c[0]) >= 3) else np.nan
        c = comp("dk", r.dk, r, 730, 15, None, 540)
        if c and len(c[0]) >= 3:
            p, w, age, yy, ee, ff = c; w = w.copy()
            if np.isfinite(r.by2): w = w * np.where(np.isnan(yy), 0.5, np.exp(-np.abs(yy - r.by2) / 5.0))
            if np.isfinite(r.elv): w = w * np.where(np.isnan(ee), 0.65, np.where(ee == r.elv, 1.0, 0.3))
            tf = fcls(np.array([r.floor], dtype=float))[0]; w = w * np.where(ff == tf, 1.0, 0.5)
            x["e_dongw"] = wmed(p, w) * r.size
        else: x["e_dongw"] = np.nan
        c = comp("region", r.region, r, 365, 8)
        x["n_reg"] = 0 if c is None else len(c[0]); x["e_reg"] = wmed(c[0], c[1]) * r.size if c else np.nan
        x.update({"size": r.size, "floor": r.floor if np.isfinite(r.floor) else 3.0, "age": (r.deal_date // 10000) - r.by2 if np.isfinite(r.by2) else np.nan,
                  "elv": r.elv, "grnd": r.grnd, "hh": r.hh, "deal_date": r.deal_date, "t": r.day / 365.0,
                  "sido": 0 if str(r.region).startswith("서울") else (1 if str(r.region).startswith("인천") else 2), "region": r.region})
        rows.append(x)
    D = pd.DataFrame(rows)
    D["reg_code"] = D["region"].astype("category").cat.codes
    for k in ("e_bld", "e_dong", "e_dongw", "e_reg"): D["r_" + k] = np.log(D[k] / D["base"])
    D["lvl_c"] = D["lvl"].map({"건물3+": 0, "건물1~2+동": 1, "건물1~2": 2, "동5+": 3, "동1~4": 4, "시군구": 5})
    D["y"] = np.log(D["actual"] / D["base"])
    D["lbase"] = np.log(D["base"] / D["size"])
    cols = ["r_e_bld", "r_e_dong", "r_e_dongw", "r_e_reg", "n_bld", "n_dong", "n_reg", "age_bld", "age_dong", "disp", "size", "floor", "age", "elv", "grnd", "hh", "lvl_c", "sido", "reg_code", "lbase"]
    P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
    def pin(y, qp, q): d = y - qp; return float(np.mean(np.maximum(q * d, (q - 1) * d)))
    def pstat(S, col):
        e = S[col] / S["actual"] - 1; a = e.abs()
        return {"오차%": round(float(a.median()) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "±20%": round(float((a <= .2).mean()) * 100, 1), "쏠림%": round(float(e.median()) * 100, 1)}
    out = {"folds": {}}
    FOLDS = [("2023→2024", 20230101, 20240101, 20250101), ("2024→2025", 20240101, 20250101, 20260101), ("2025→2026", 20250101, 20260101, 99999999)]
    for nm, a, b, c in FOLDS:
        TR = D[(D["deal_date"] >= a) & (D["deal_date"] < b)]; TE = D[(D["deal_date"] >= b) & (D["deal_date"] < c)].copy()
        if len(TR) < 3000 or len(TE) < 1000: out["folds"][nm] = {"건너뜀": f"학습 {len(TR)} 시험 {len(TE)}"}; continue
        pt = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols], TR["y"]); TE["est_stack"] = TE["base"] * np.exp(pt.predict(TE[cols]))
        for q in (0.1, 0.25):
            TE[f"mq{int(q * 100)}"] = HistGradientBoostingRegressor(loss="quantile", quantile=q, **P).fit(TR[cols], TR["y"]).predict(TE[cols])
        cell = TR.groupby(["lvl_c", "sido"])["y"].quantile([0.1, 0.25]).unstack(); gcell = TR.groupby("lvl_c")["y"].quantile([0.1, 0.25]).unstack()
        for q in (0.1, 0.25):
            TE[f"cq{int(q * 100)}"] = [float(cell.loc[(r.lvl_c, r.sido), q]) if (r.lvl_c, r.sido) in cell.index else float(gcell.loc[r.lvl_c, q]) for r in TE.itertuples()]
        f = {"학습 n": int(len(TR)), "시험 n": int(len(TE)), "점": {"기존": pstat(TE, "base"), "종합": pstat(TE, "est_stack")}, "분위": {}}
        for q in (0.1, 0.25):
            k = int(q * 100)
            f["분위"][f"하위{k}%"] = {nm2: {"포함률%": round(float((TE["y"] >= TE[col]).mean()) * 100, 1), "여유폭%": round(float(-(np.exp(TE[col]) - 1).mean()) * 100, 2), "핀볼": round(pin(TE["y"].values, TE[col].values, q), 5)} for nm2, col in (("기존", f"cq{k}"), ("종합", f"mq{k}"))}
        # 같은 포함률로 맞춘 여유폭: 종합 모델 분위에 상수를 더해 기존 포함률과 같게 맞춘 뒤 비교(공정 비교)
        for q in (0.1, 0.25):
            k = int(q * 100); target = float((TE["y"] >= TE[f"cq{k}"]).mean())
            sh = float(np.quantile(TE["y"] - TE[f"mq{k}"], 1 - target))
            f["분위"][f"하위{k}%"]["종합(포함률을 기존에 맞춤)"] = {"여유폭%": round(float(-(np.exp(TE[f"mq{k}"] + sh) - 1).mean()) * 100, 2), "핀볼": round(pin(TE["y"].values, (TE[f"mq{k}"] + sh).values, q), 5)}
        f["단계별 점 오차%"] = {l: {"n": int(len(S)), "기존": round(float((S["base"] / S["actual"] - 1).abs().median()) * 100, 2), "종합": round(float((S["est_stack"] / S["actual"] - 1).abs().median()) * 100, 2)} for l, S in TE.groupby("lvl") if len(S) >= 100}
        out["folds"][nm] = f
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-villa-stack-cv.json", "w"), ensure_ascii=False, indent=1)
    try:
        from datetime import datetime, timezone
        cyc = load("cyc", "analyze-cycle.py"); now = datetime.now(timezone.utc).isoformat()
        cyc.upsert_rows([{"id": "signal|__villa_bt_stackcv__", "payload": cyc.clean_json(dict(out, generatedAt=now)), "fetched_at": now}]); print("서버 저장: stackcv")
    except Exception as e:
        print("서버 저장 실패:", e)


if __name__ == "__main__":
    main()
