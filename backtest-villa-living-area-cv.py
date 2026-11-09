"""
🏘️ 수도권 빌라 '생활권 시세' 종합 평가 시험 (2026-11-09, 사용자: 빌라는 같은 건물 거래가 3~4년 안에 거의 없어 생활권에서 시세를 파악해야 한다 - 객관적 거래 자료로)
기존 종합 평가(backtest-villa-stack-cv.py: 건물·동·시군구 추정 + 근거 수·흩어짐·층·연식·승강기 등)에 '반경(걸어서 갈 수 있는 거리) 안 거래로 만든 시세' 특징을 더해서 더 정확해지는지 시간순 교차 검증.
 - 반경 300m / 700m / 1.5km 안, 그 거래 30일 전까지의 거래만 사용(미래 정보 없음)
 - 가중: 최근일수록·면적이 비슷할수록·연식이 비슷할수록·승강기 유무가 같을수록·층 구분이 같을수록 비중↑ (고정 상수 대신 자료의 분산에 맞춘 지수 감쇠, 가중이 약해도 종합 모델이 필요한 만큼만 사용)
 - 생활권 가격 수준: 반경 안 모든 빌라 거래의 ㎡당 중위값 ÷ 기존 추정 ㎡당(그 동네 시세 수준이 기존 추정과 얼마나 다른가)
 - 대장 매칭 품질 표시(거래 건축년도 vs 대장 사용승인연도 차이)도 특징으로 넣어, 매칭이 어긋난 건물에서 종합 모델이 반경 쪽을 더 믿는지 확인
비교: ① 기존 종합(현재 앱에 적용 중) ② 종합 + 생활권 특징. 점 오차(중앙·±10%·±20%·쏠림), 하위 25% 분위(포함률·여유폭·핀볼), 단계별(건물3+/동5+/동1~4/시군구) 점 오차.
측정 전용 - 앱·서버 값 변경 없음. 결과: villa-living-area-cv.json
"""
import os, json, importlib.util
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py")
avm = bv.avm
N_TEST = int(os.environ.get("N_TEST", "40000"))
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
RADII = (0.3, 0.7, 1.5)   # km


def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])


def fcls(f):
    f = np.where(np.isnan(f), 3, f)
    return np.where(f <= 0, 0, np.where(f <= 2, 1, np.where(f <= 4, 2, 3)))


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
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
    B["apr"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
    B["elvAny"] = ((B["elv"].fillna(0) + B["emg"].fillna(0)) > 0).astype(float)
    Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min"), nt=("apr", "size")).reset_index()
    df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"], suffixes=("", "_b")).reset_index(drop=True)
    df["by2"] = df["build_year"].where(df["build_year"].between(1960, 2026), df["apr"].where(df["apr"].between(1960, 2026)))
    # 대장 매칭 품질: 거래 건축년도와 대장 사용승인연도 차이(둘 다 있을 때)
    df["link_gap"] = (df["build_year"].where(df["build_year"].between(1960, 2026)) - df["apr"].where(df["apr"].between(1960, 2026))).abs()
    print(f"거래 {len(df):,}건, 좌표 {df['lat'].notna().mean() * 100:.1f}%, 대장(승강기) {df['elv'].notna().mean() * 100:.1f}%, 연식 대조 가능 {df['link_gap'].notna().mean() * 100:.1f}%")

    # 반경 검색용 배열(좌표 있는 거래, 날짜 오름차순 유지)
    G = df[df["lat"].notna()]
    X = np.c_[G["lat"].values * 111.0, G["lon"].values * 111.0 * np.cos(np.radians(37.5))]
    tree = cKDTree(X)
    pos = {i: k for k, i in enumerate(G.index)}   # df 행 → 좌표 배열 위치
    g_day, g_size, g_ppm = G["day"].values, G["size"].values, G["ppm"].values
    g_by, g_elv = G["by2"].values.astype(float), G["elv"].values.astype(float)
    g_fc = fcls(G["floor"].values.astype(float))

    T = df[df["deal_date"] >= 20230101]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    E = bv.estimate(df, T); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    T = T[T.index.isin(E.index)].copy()
    print(f"시험·학습 대상 {len(T):,}건")

    def mk(key):
        return {k: (g["day"].values, g["size"].values, g["ppm"].values, g["by2"].values.astype(float), g["elv"].values.astype(float), fcls(g["floor"].values.astype(float)))
                for k, g in df.groupby(key)}
    GG = {"bld": mk("bld"), "dk": mk("dk"), "region": mk("region")}

    def comp(kc, key, r, days, stol, yb_hard=None, wt=None):
        t = GG[kc].get(key)
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
        # ── 생활권(반경) 특징 ──
        for R in RADII: x[f"e_rad{int(R * 1000)}"] = np.nan; x[f"n_rad{int(R * 1000)}"] = 0; x[f"lvl_rad{int(R * 1000)}"] = np.nan
        x["rad_disp"] = np.nan; x["rad_dist"] = np.nan
        if r.Index in pos:
            k0 = pos[r.Index]; nb = np.array(tree.query_ball_point(X[k0], max(RADII)), dtype=int)
            if len(nb):
                dc = r.day - 30
                ok = (g_day[nb] <= dc) & (g_day[nb] >= dc - 730) & (nb != k0)
                nb = nb[ok]
                if len(nb):
                    dist = np.sqrt(((X[nb] - X[k0]) ** 2).sum(1)); age = dc - g_day[nb]
                    for R in RADII:
                        mR = dist <= R; kk = int(R * 1000)
                        if mR.sum() < 3: continue
                        idx = nb[mR]; dd = dist[mR]; ag = age[mR]
                        # 면적 ±15㎡ 안, 가중 = 최근·면적·연식·승강기·층·거리
                        ms = np.abs(g_size[idx] - r.size) <= 15
                        if ms.sum() >= 3:
                            i2 = idx[ms]; w = np.exp(-ag[ms] / 540.0) * np.exp(-np.abs(g_size[i2] - r.size) / 10.0) * np.exp(-dd[ms] / max(R, 0.3))
                            if np.isfinite(r.by2): w = w * np.where(np.isnan(g_by[i2]), 0.5, np.exp(-np.abs(g_by[i2] - r.by2) / 5.0))
                            if np.isfinite(r.elv): w = w * np.where(np.isnan(g_elv[i2]), 0.65, np.where(g_elv[i2] == r.elv, 1.0, 0.3))
                            tf = fcls(np.array([r.floor], dtype=float))[0]; w = w * np.where(g_fc[i2] == tf, 1.0, 0.5)
                            x[f"e_rad{kk}"] = wmed(g_ppm[i2], w) * r.size; x[f"n_rad{kk}"] = int(ms.sum())
                            if kk == 700: x["rad_disp"] = float(np.std(np.log(g_ppm[i2]))); x["rad_dist"] = float(np.average(dd[ms], weights=w))
                        rec = ag <= 180
                        if rec.sum() >= 5: x[f"lvl_rad{kk}"] = float(np.median(g_ppm[idx][rec]))
        x.update({"size": r.size, "floor": r.floor if np.isfinite(r.floor) else 3.0, "age": (r.deal_date // 10000) - r.by2 if np.isfinite(r.by2) else np.nan,
                  "elv": r.elv, "grnd": r.grnd, "hh": r.hh, "deal_date": r.deal_date, "t": r.day / 365.0, "link_gap": r.link_gap, "nt": r.nt,
                  "sido": 0 if str(r.region).startswith("서울") else (1 if str(r.region).startswith("인천") else 2), "region": r.region})
        rows.append(x)
    D = pd.DataFrame(rows)
    D["reg_code"] = D["region"].astype("category").cat.codes
    for k in ("e_bld", "e_dong", "e_dongw", "e_reg", "e_rad300", "e_rad700", "e_rad1500"): D["r_" + k] = np.log(D[k] / D["base"])
    for kk in ("300", "700", "1500"): D["r_lvl" + kk] = np.log(D["lvl_rad" + kk] * D["size"] / D["base"])
    D["lvl_c"] = D["lvl"].map({"건물3+": 0, "건물1~2+동": 1, "건물1~2": 2, "동5+": 3, "동1~4": 4, "시군구": 5})
    D["y"] = np.log(D["actual"] / D["base"]); D["lbase"] = np.log(D["base"] / D["size"])
    cols0 = ["r_e_bld", "r_e_dong", "r_e_dongw", "r_e_reg", "n_bld", "n_dong", "n_reg", "age_bld", "age_dong", "disp", "size", "floor", "age", "elv", "grnd", "hh", "lvl_c", "sido", "reg_code", "lbase"]
    cols1 = cols0 + ["r_e_rad300", "r_e_rad700", "r_e_rad1500", "n_rad300", "n_rad700", "n_rad1500", "r_lvl300", "r_lvl700", "r_lvl1500", "rad_disp", "rad_dist"]
    cols2 = cols1 + ["link_gap", "nt"]
    print(f"생활권 특징 채워진 비율: 300m {D['e_rad300'].notna().mean() * 100:.0f}%, 700m {D['e_rad700'].notna().mean() * 100:.0f}%, 1.5km {D['e_rad1500'].notna().mean() * 100:.0f}%")
    P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
    def pin(y, qp, q): d = y - qp; return float(np.mean(np.maximum(q * d, (q - 1) * d)))
    def pstat(S, col):
        e = S[col] / S["actual"] - 1; a = e.abs()
        return {"오차%": round(float(a.median()) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "±20%": round(float((a <= .2).mean()) * 100, 1), "쏠림%": round(float(e.median()) * 100, 1), "10%+높음%": round(float((e > .10).mean()) * 100, 1)}
    out = {"folds": {}, "전체": {}}
    FOLDS = [("2023→2024", 20230101, 20240101, 20250101), ("2024→2025", 20240101, 20250101, 20260101), ("2025→2026", 20250101, 20260101, 99999999)]
    allte = []
    for nm, a, b, c in FOLDS:
        TR = D[(D["deal_date"] >= a) & (D["deal_date"] < b)]; TE = D[(D["deal_date"] >= b) & (D["deal_date"] < c)].copy()
        if len(TR) < 3000 or len(TE) < 1000: out["folds"][nm] = {"건너뜀": f"학습 {len(TR)} 시험 {len(TE)}"}; continue
        for tag, cols in (("s0", cols0), ("s1", cols1), ("s2", cols2)):
            TE["est_" + tag] = TE["base"] * np.exp(HistGradientBoostingRegressor(loss="absolute_error", **P).fit(TR[cols], TR["y"]).predict(TE[cols]))
            TE["mq25_" + tag] = HistGradientBoostingRegressor(loss="quantile", quantile=0.25, **P).fit(TR[cols], TR["y"]).predict(TE[cols])
        f = {"학습 n": int(len(TR)), "시험 n": int(len(TE)), "점": {"앱 기존 단계식": pstat(TE, "base"), "① 종합(현재 앱)": pstat(TE, "est_s0"), "② 종합+생활권": pstat(TE, "est_s1"), "③ 종합+생활권+대장 매칭 품질": pstat(TE, "est_s2")},
             "하위25% 핀볼": {"① 종합": round(pin(TE["y"].values, TE["mq25_s0"].values, .25), 5), "② 종합+생활권": round(pin(TE["y"].values, TE["mq25_s1"].values, .25), 5), "③ +매칭 품질": round(pin(TE["y"].values, TE["mq25_s2"].values, .25), 5)},
             "단계별 점 오차%": {l: {"n": int(len(S)), "기존": round(float((S["base"] / S["actual"] - 1).abs().median()) * 100, 2), "①": round(float((S["est_s0"] / S["actual"] - 1).abs().median()) * 100, 2), "②": round(float((S["est_s1"] / S["actual"] - 1).abs().median()) * 100, 2)} for l, S in TE.groupby("lvl") if len(S) >= 150}}
        out["folds"][nm] = f; allte.append(TE)
    if allte:
        A = pd.concat(allte)
        out["전체"] = {"n": int(len(A)), "점": {"앱 기존 단계식": pstat(A, "base"), "① 종합": pstat(A, "est_s0"), "② 종합+생활권": pstat(A, "est_s1"), "③ +매칭 품질": pstat(A, "est_s2")},
                     "단계별": {l: {"n": int(len(S)), "기존": round(float((S["base"] / S["actual"] - 1).abs().median()) * 100, 2), "①": round(float((S["est_s0"] / S["actual"] - 1).abs().median()) * 100, 2), "②": round(float((S["est_s1"] / S["actual"] - 1).abs().median()) * 100, 2)} for l, S in A.groupby("lvl") if len(S) >= 150},
                     "대장 연식 어긋남별(②)": {lab: {"n": int(len(S)), "①": round(float((S["est_s0"] / S["actual"] - 1).abs().median()) * 100, 2), "②": round(float((S["est_s1"] / S["actual"] - 1).abs().median()) * 100, 2)} for lab, S in (("연식 대조 불가", A[A["link_gap"].isna()]), ("0~1년 일치", A[A["link_gap"] <= 1]), ("2~5년 차이", A[(A["link_gap"] > 1) & (A["link_gap"] <= 5)]), ("6년+ 차이", A[A["link_gap"] > 5])) if len(S) >= 150},
                     "생활권 특징 있는 거래만(700m)": {"n": int(A["e_rad700"].notna().sum()), "①": pstat(A[A["e_rad700"].notna()], "est_s0"), "②": pstat(A[A["e_rad700"].notna()], "est_s1")}}
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("villa-living-area-cv.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
