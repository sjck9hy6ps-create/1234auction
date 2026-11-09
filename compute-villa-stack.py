"""
🏘️ 수도권 빌라 종합 평가 값 계산 (2026-11-07, 사용자: 기준·상수 대신 여러 조건을 종합해 가장 좋은 값을 - 교차 시간 검증 3구간 모두 기존보다 정확)
검증(backtest-villa-stack-cv.py): 점 오차 12.9→11.1%, ±10% 이내 41→46%, 같은 포함률에서 하위 25% 여유폭 10.4→9.4%(3구간 모두).
여기서는 거래 2023~ 전체로 모델(점 보정·하위 10/25% 분위)을 학습하고, 입찰 예정 수도권 빌라 물건마다 같은 특성(건물·동·시군구 추정, 근거 건수, 마지막 거래 경과일, 가격 흩어짐, 층, 연식, 승강기, 세대수)을 만들어
예상매도가(est)와 하위 25%·10% 값을 구해 signal|__villa_stack__에 저장(서버 mode=villaStack). 앱이 건물 거래 3건 미만 단계에서 이 값을 씀(건물 3건 이상은 기존 그대로 - 검증에서 이득 없음).
"""
import os, json, importlib.util
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py"); cyc = load("cyc", "analyze-cycle.py")
avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
N_TRAIN = int(os.environ.get("N_TRAIN", "50000"))
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
SIDO = {"서울특별시": "서울", "서울": "서울", "인천광역시": "인천", "인천": "인천", "경기도": "경기", "경기": "경기"}
EPOCH = pd.Timestamp("2020-01-01")
# 2026-11-09 생활권(반경) 시세 특징 추가(backtest-villa-living-area-cv.py, 3개 시간순 구간 모두 개선: 오차 10.97→10.22%, ±20% 72.5→76.0%, 하위25% 핀볼 약 8% 감소)
RADII = (0.3, 0.7, 1.5)   # km
RAD_COLS = ["r_e_rad300", "r_e_rad700", "r_e_rad1500", "n_rad300", "n_rad700", "n_rad1500", "r_lvl300", "r_lvl700", "r_lvl1500", "rad_disp", "rad_dist"]
COLS = ["r_e_bld", "r_e_dong", "r_e_dongw", "r_e_reg", "n_bld", "n_dong", "n_reg", "age_bld", "age_dong", "disp", "size", "floor", "age", "elv", "grnd", "hh", "lvl_c", "sido", "reg_code", "lbase"] + RAD_COLS
LVL = {"건물3+": 0, "건물1~2+동": 1, "건물1~2": 2, "동5+": 3, "동1~4": 4, "시군구": 5}


def trade_region(addr):
    t = str(addr or "").split()
    if len(t) < 2: return None
    sd = SIDO.get(t[0])
    if not sd: return None
    city = t[1]
    if len(t) >= 3 and city.endswith("시") and t[2].endswith("구"): return f"{sd} {city[:-1]} {t[2]}"
    return f"{sd} {city}"


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
    Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), grnd=("grnd", "max"), hh=("hh", "max"), apr=("apr", "min")).reset_index()
    df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"], suffixes=("", "_b")).reset_index(drop=True)
    df["by2"] = df["build_year"].where(df["build_year"].between(1960, 2026), df["apr"].where(df["apr"].between(1960, 2026)))
    print(f"거래 {len(df):,}건, 대장 승강기 연결 {df['elv'].notna().mean() * 100:.1f}%, 좌표 {df['lat'].notna().mean() * 100:.1f}%")
    # 반경 검색용 배열(좌표 있는 거래)
    Gc = df[df["lat"].notna()]
    KM = 111.0 * np.cos(np.radians(37.5))
    Xc = np.c_[Gc["lat"].values * 111.0, Gc["lon"].values * KM]; tree = cKDTree(Xc)
    cpos = {i: k for k, i in enumerate(Gc.index)}
    g_day, g_size, g_ppm = Gc["day"].values, Gc["size"].values, Gc["ppm"].values
    g_by, g_elv = Gc["by2"].values.astype(float), Gc["elv"].values.astype(float)
    g_fc = fcls(Gc["floor"].values.astype(float))

    def mk(key):
        return {k: (g["day"].values, g["size"].values, g["ppm"].values, g["by2"].values.astype(float), g["elv"].values.astype(float), fcls(g["floor"].values.astype(float)))
                for k, g in df.groupby(key)}
    G = {"bld": mk("bld"), "dk": mk("dk"), "region": mk("region")}
    regcat = pd.Categorical(df["region"]); regmap = {k: i for i, k in enumerate(regcat.categories)}

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

    def featurize(T):
        """T: df와 같은 열(day,size,floor,by2,elv,grnd,hh,bld,dk,region,build_year,price)을 가진 행들 → 특성표(기준 추정 base·단계 포함)"""
        E = bv.estimate(df, T); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
        rows = []
        for r in T.itertuples():
            if r.Index not in E.index: continue
            x = {"i": r.Index, "base": E.loc[r.Index, "est"], "lvl": E.loc[r.Index, "lvl"]}
            c = comp("bld", r.bld, r, 730, 6)
            x["n_bld"] = 0 if c is None else len(c[0]); x["e_bld"] = wmed(c[0], c[1]) * r.size if c else np.nan; x["age_bld"] = float(c[2].min()) if c else np.nan
            c = comp("dk", r.dk, r, 365, 8, 5)
            x["n_dong"] = 0 if c is None else len(c[0]); x["e_dong"] = wmed(c[0], c[1]) * r.size if (c and len(c[0]) >= 3) else np.nan
            x["age_dong"] = float(c[2].min()) if c else np.nan; x["disp"] = float(np.std(np.log(c[0]))) if (c and len(c[0]) >= 3) else np.nan
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
            # ── 생활권(반경) 특징: 그 거래(입찰 기준일) 30일 전까지 반경 안 거래만, 최근·면적·연식·승강기·층·거리 가중 ──
            for R_ in RADII: x[f"e_rad{int(R_ * 1000)}"] = np.nan; x[f"n_rad{int(R_ * 1000)}"] = 0; x[f"lvl_rad{int(R_ * 1000)}"] = np.nan
            x["rad_disp"] = np.nan; x["rad_dist"] = np.nan
            la, lo_ = getattr(r, "lat", np.nan), getattr(r, "lon", np.nan)
            if la is not None and lo_ is not None and np.isfinite(la) and np.isfinite(lo_):
                p0 = np.array([la * 111.0, lo_ * KM]); k0 = cpos.get(r.Index, -1)
                nb = np.array(tree.query_ball_point(p0, max(RADII)), dtype=int)
                if len(nb):
                    dc_ = r.day - 30
                    ok_ = (g_day[nb] <= dc_) & (g_day[nb] >= dc_ - 730) & (nb != k0)
                    nb = nb[ok_]
                    if len(nb):
                        dist = np.sqrt(((Xc[nb] - p0) ** 2).sum(1)); agx = dc_ - g_day[nb]
                        for R_ in RADII:
                            mR = dist <= R_; kk = int(R_ * 1000)
                            if mR.sum() < 3: continue
                            idx_ = nb[mR]; dd_ = dist[mR]; ag_ = agx[mR]
                            ms = np.abs(g_size[idx_] - r.size) <= 15
                            if ms.sum() >= 3:
                                i2 = idx_[ms]; w = np.exp(-ag_[ms] / 540.0) * np.exp(-np.abs(g_size[i2] - r.size) / 10.0) * np.exp(-dd_[ms] / max(R_, 0.3))
                                if np.isfinite(r.by2): w = w * np.where(np.isnan(g_by[i2]), 0.5, np.exp(-np.abs(g_by[i2] - r.by2) / 5.0))
                                if np.isfinite(r.elv): w = w * np.where(np.isnan(g_elv[i2]), 0.65, np.where(g_elv[i2] == r.elv, 1.0, 0.3))
                                tf_ = fcls(np.array([r.floor], dtype=float))[0]; w = w * np.where(g_fc[i2] == tf_, 1.0, 0.5)
                                x[f"e_rad{kk}"] = wmed(g_ppm[i2], w) * r.size; x[f"n_rad{kk}"] = int(ms.sum())
                                if kk == 700: x["rad_disp"] = float(np.std(np.log(g_ppm[i2]))); x["rad_dist"] = float(np.average(dd_[ms], weights=w))
                            rec_ = ag_ <= 180
                            if rec_.sum() >= 5: x[f"lvl_rad{kk}"] = float(np.median(g_ppm[idx_][rec_]))
            dy = (EPOCH + pd.Timedelta(days=int(r.day))).year
            x.update({"size": r.size, "floor": r.floor if np.isfinite(r.floor) else 3.0, "age": dy - r.by2 if np.isfinite(r.by2) else np.nan, "elv": r.elv, "grnd": r.grnd, "hh": r.hh,
                      "sido": 0 if str(r.region).startswith("서울") else (1 if str(r.region).startswith("인천") else 2), "reg_code": regmap.get(r.region, -1)})
            rows.append(x)
        D = pd.DataFrame(rows).set_index("i")
        for k in ("e_bld", "e_dong", "e_dongw", "e_reg", "e_rad300", "e_rad700", "e_rad1500"): D["r_" + k] = np.log(D[k] / D["base"])
        for kk in ("300", "700", "1500"): D["r_lvl" + kk] = np.log(D["lvl_rad" + kk] * D["size"] / D["base"])
        D["lvl_c"] = D["lvl"].map(LVL); D["lbase"] = np.log(D["base"] / D["size"])
        return D

    # ── 학습: 2023~ 거래 표본 ──
    EVAL = os.environ.get("EVAL_APP") == "1"; EVALW = os.environ.get("EVAL_WINBID") == "1"; FITW = os.environ.get("FIT_WINBID") == "1"
    cutoff = 20260101 if EVAL else (20260601 if (EVALW or FITW) else None)
    T = df[(df["deal_date"] >= 20230101) & ((df["deal_date"] < cutoff) if cutoff else True)]
    if len(T) > N_TRAIN: T = T.sample(N_TRAIN, random_state=11)
    D = featurize(T); D["y"] = np.log(T.loc[D.index, "price"] / D["base"])
    print(f"학습 {len(D):,}건")
    P = dict(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=60, l2_regularization=1.0, random_state=1)
    pt = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(D[COLS], D["y"])
    mq = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, **P).fit(D[COLS], D["y"]) for q in (0.1, 0.25)}

    if EVAL:
        return eval_app(df, D, pt, mq, featurize)
    if EVALW:
        return eval_winbid(df, pt, featurize)
    if FITW:   # 낙찰가 모델 다시 학습(2026-11-07): 검증용(2026-06 이전 거래로 학습)과 최종(전체 거래로 학습) 점 보정을 둘 다 만들어 넘김
        T2 = df[(df["deal_date"] >= 20230101)]
        if len(T2) > N_TRAIN: T2 = T2.sample(N_TRAIN, random_state=11)
        D2 = featurize(T2); D2["y"] = np.log(T2.loc[D2.index, "price"] / D2["base"])
        pt_all = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(D2[COLS], D2["y"])
        return eval_winbid(df, pt, featurize, pt_all=pt_all)
    # ── 입찰 물건 ──
    au = requests.get(f"{SITE}/api/auction?kind=auctions", timeout=300).json()
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    L = []
    for a in au:
        if a.get("propType") != "villa": continue
        reg = trade_region(a.get("addr"))
        if not reg or not a.get("dong"): continue
        try: area = float(a.get("pyung") or 0) * 3.305785
        except Exception: area = 0
        if area < 15 or area > 150: continue
        bd = pd.to_datetime(a.get("bidDate"), errors="coerce")
        if pd.notna(bd) and bd < today - pd.Timedelta(days=7): continue
        # 앱과 같은 기준일: 자료는 min(오늘, 입찰일−30일)까지 → 시험 구조(거래일−30일)에 맞춰 day = min(입찰일, 오늘+30일)
        ref = min(bd, today + pd.Timedelta(days=30)) if pd.notna(bd) else today + pd.Timedelta(days=30)
        bunji = str(a.get("bunji") or "")
        try: fl = float(a.get("floor"))
        except Exception: fl = np.nan
        try: by = float(a.get("buildYear")) if a.get("buildYear") else np.nan
        except Exception: by = np.nan
        try: la_ = float(a.get("lat")); lo2 = float(a.get("lon"))
        except Exception: la_ = lo2 = np.nan
        L.append({"id": str(a["id"]), "region": reg, "dong": a["dong"], "bunji": bunji, "size": area, "floor": fl, "build_year": by, "day": int((ref - EPOCH).days), "lat": la_, "lon": lo2})
    Lr = pd.DataFrame(L)
    print(f"입찰 예정 수도권 빌라 {len(Lr):,}건")
    Lr["bld"] = Lr["region"] + "|" + Lr["dong"].astype(str) + "|" + Lr["bunji"]; Lr["dk"] = Lr["region"] + "|" + Lr["dong"].astype(str)
    # 승강기·층수·세대수·사용승인연: 같은 건물(번지) 거래에 붙은 대장 값을 그대로(대장 연결된 거래가 있으면)
    bl = df.dropna(subset=["elv"]).groupby("bld").agg(elv=("elv", "last"), grnd=("grnd", "last"), hh=("hh", "last"), apr=("apr", "last"), byy=("by2", "last"))
    for c in ("elv", "grnd", "hh"): Lr[c] = Lr["bld"].map(bl[c]) if len(bl) else np.nan
    byb = Lr["bld"].map(bl["byy"]) if len(bl) else np.nan
    Lr["by2"] = Lr["build_year"].where(Lr["build_year"].between(1960, 2026), byb)
    Lr["price"] = 0.0
    Lr.index = np.arange(10_000_000, 10_000_000 + len(Lr)); Lr["floor"] = Lr["floor"]
    F = featurize(Lr)
    F["pt"] = pt.predict(F[COLS]); F["q10"] = mq[0.1].predict(F[COLS]); F["q25"] = mq[0.25].predict(F[COLS])
    out = {}
    for i, f in F.iterrows():
        base_ = float(f["base"]); est = base_ * float(np.exp(np.clip(f["pt"], -0.4, 0.4)))
        l25 = min(base_ * float(np.exp(f["q25"])), est); l10 = min(base_ * float(np.exp(f["q10"])), l25)
        id_ = Lr.loc[i, "id"]
        out[id_] = {"est": round(est), "l25": round(l25), "l10": round(l10), "base": round(base_), "lvl": f["lvl"], "n": int(f["n_bld"]), "nd": int(f["n_dong"]),
                  "nr": int(f["n_rad700"]), "rd": (round(float(f["rad_disp"]), 3) if np.isfinite(f["rad_disp"]) else None)}   # 생활권(반경 700m) 비슷한 면적 거래 수·흩어짐(2026-11-09: 거래 2건 이하면 오차 21.8%·하위10% -58.7%)
    now = datetime.now(timezone.utc).isoformat()
    payload = {"generatedAt": now, "ver": 1, "trainN": int(len(D)), "rows": out, "물건수": int(len(Lr)), "적용수": len(out)}
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, ensure_ascii=False)); print(list(out.items())[:3])
    json.dump(payload, open("villa-stack.json", "w", encoding="utf-8"), ensure_ascii=False)
    cyc.upsert_rows([{"id": "signal|__villa_stack__", "payload": cyc.clean_json(payload), "fetched_at": now}]); print("서버 저장: villa_stack")


def eval_app(df, D, pt, mq, featurize):
    """앱 실제 계산(villaSaleEst, 거래 30일 전 자료)과 같은 거래의 기본 추정·종합 모델·안전장치 적용 값을 실제가와 비교(2026-11-07)."""
    ap = requests.get(f"{SITE}/api/data-coverage?mode=villaBt&name=appasof&nocache=1", timeout=300).json()
    R = pd.DataFrame(ap.get("rows") or [])
    print(f"앱 값 행 {len(R):,} (앱 값 있음 {int((R['app'] > 0).sum()) if len(R) else 0:,})")
    R = R[R["app"] > 0].copy()
    df = df.copy(); df["_k"] = df["dong"].astype(str) + "|" + df["bunji"].astype(str) + "|" + df["deal_date"].astype(int).astype(str) + "|" + df["price"].astype(int).astype(str) + "|" + df["size"].round(0).astype(int).astype(str)
    R["_k"] = R["dong"].astype(str) + "|" + R["bunji"].astype(str) + "|" + R["d"].astype(int).astype(str) + "|" + R["price"].astype(int).astype(str) + "|" + R["area"].round(0).astype(int).astype(str)
    first = df.drop_duplicates("_k").set_index("_k")
    R = R[R["_k"].isin(first.index)].drop_duplicates("_k")
    T = first.loc[R["_k"].values].reset_index(drop=True)
    T.index = np.arange(20_000_000, 20_000_000 + len(T)); R.index = T.index
    print(f"매칭된 거래 {len(T):,}")
    F = featurize(T)
    F["pt"] = pt.predict(F[COLS]); F["q10"] = mq[0.1].predict(F[COLS]); F["q25"] = mq[0.25].predict(F[COLS])
    X = pd.DataFrame({"actual": T.loc[F.index, "price"].values, "app": R.loc[F.index, "app"].values, "base": F["base"].values, "lvl": F["lvl"].values,
                      "stack": (F["base"] * np.exp(np.clip(F["pt"], -0.4, 0.4))).values, "q10": (F["base"] * np.exp(F["q10"])).values, "q25": (F["base"] * np.exp(F["q25"])).values,
                      "floor": T.loc[F.index, "floor"].values, "appLvl": R.loc[F.index, "lvl"].values, "sido": F["sido"].values})
    X["guard"] = np.where(X["floor"] <= 0, X["app"], np.minimum(X["stack"], X["app"] * 1.15))      # 앱에 넣은 안전장치(지하 제외·+15% 상한)
    X["guard_n3"] = np.where(X["lvl"] == "건물3+", X["app"], X["guard"])                           # 건물 3건 이상은 앱 값 유지(실제 적용 방식)
    X["avg"] = np.sqrt(X["app"] * X["stack"])                                                       # 두 값의 기하평균(참고)
    def st(S, col):
        e = S[col] / S["actual"] - 1; a = e.abs()
        return {"n": int(len(S)), "오차%": round(float(a.median()) * 100, 2), "±10%": round(float((a <= .1).mean()) * 100, 1), "±20%": round(float((a <= .2).mean()) * 100, 1), "쏠림%": round(float(e.median()) * 100, 1),
                "높게 틀림 10%초과 비율": round(float((e > .1).mean()) * 100, 1), "낮게 틀림 10%초과 비율": round(float((e < -.1).mean()) * 100, 1)}
    cols = ["app", "base", "stack", "guard", "guard_n3", "avg"]
    out = {"matched": int(len(X)), "from": ap.get("from")}
    out["전체"] = {c: st(X, c) for c in cols}
    for nm, S in (("건물3+ 아님(실제 적용 대상)", X[X["lvl"] != "건물3+"]), ("건물3+", X[X["lvl"] == "건물3+"]), ("지하·반지하", X[X["floor"] <= 0]), ("서울", X[X["sido"] == 0]), ("인천·경기", X[X["sido"] > 0])):
        if len(S) >= 100: out[nm] = {c: st(S, c) for c in cols}
    for l, S in X.groupby("lvl"):
        if len(S) >= 100: out["단계 " + l] = {c: st(S, c) for c in ("app", "base", "stack", "guard")}
    # 두 값이 크게 다를 때 누가 맞나
    X["gap"] = X["stack"] / X["app"] - 1
    for nm, S in (("종합이 앱보다 15%+ 높음", X[X["gap"] > .15]), ("종합이 앱보다 15%+ 낮음", X[X["gap"] < -.15]), ("차이 15% 이내", X[X["gap"].abs() <= .15])):
        if len(S) >= 50: out["차이 " + nm] = {c: st(S, c) for c in ("app", "stack", "guard")}
    # 하위 분위 포함률(실제가가 하위값 이상인 비율): 종합 모델 q25/q10
    out["종합 하위값 포함률%"] = {"q25(목표75)": round(float((X["actual"] >= X["q25"]).mean()) * 100, 1), "q10(목표90)": round(float((X["actual"] >= X["q10"]).mean()) * 100, 1)}
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    now = datetime.now(timezone.utc).isoformat()
    cyc.upsert_rows([{"id": "signal|__villa_bt_appeval__", "payload": cyc.clean_json(dict(out, generatedAt=now)), "fetched_at": now}]); print("서버 저장: appeval")


def fit_winbid(D, F, T, c2, pt_all, mkX, FAC, Xs, tr, te, mB, featurize):
    """앱이 읽는 villa-winbid.json 새로 만들기(종합 예상매도가 기준). 시험 값(oos·resQ)은 2026-06 이전 학습분으로, 최종 요인표는 전체 사례+전체 거래로 학습한 종합 값으로."""
    act = D["actual"].values
    p_te = D["stack"].values[te] * np.exp(predict_additive(mB, Xs[te], FAC)); e = p_te / act[te] - 1
    oos = {"전체": {"n": int(te.sum()), "medAbsErrPct": round(float(np.median(np.abs(e))) * 100, 2), "within10Pct": round(float((np.abs(e) <= .1).mean()) * 100, 1), "biasPct": round(float(np.median(e)) * 100, 2)}}
    base_c = np.exp(np.median(np.log(act[tr] / D["stack"].values[tr]))) * D["stack"].values[te]; e0 = base_c / act[te] - 1
    oos["상수 비율(기준선)"] = {"medAbsErrPct": round(float(np.median(np.abs(e0))) * 100, 2), "within10Pct": round(float((np.abs(e0) <= .1).mean()) * 100, 1)}
    T2 = pd.DataFrame({"lvl": D["lvl"].values[te], "e": e, "age": Xs["age"].values[te], "fl": Xs["floor"].values[te]})
    g = lambda col, keys=None: {k: dict(n=int(len(G)), medAbsErrPct=round(float(G["e"].abs().median()) * 100, 1), **({"within10Pct": round(float((G["e"].abs() <= .1).mean()) * 100, 1)} if col == "lvl" else {})) for k, G in T2.groupby(col) if len(G) >= 50}
    flr = {k: {"n": int(len(G)), "ratioMed": round(float((G["actual"] / G["stack"]).median()), 3)} for k, G in D.assign(fl2=Xs["floor"]).groupby("fl2") if len(G) >= 80}
    resq = [round(float(np.quantile(np.log(act[te] / p_te), q / 100)), 4) for q in range(1, 100)]
    # 최종: 전체 거래로 학습한 종합 값으로 모든 사례의 예상매도가를 다시 계산해 요인표를 학습
    F2 = F.copy(); F2["stack_all"] = F2["base"] * np.exp(np.clip(pt_all.predict(F2[COLS]), -0.4, 0.4))
    D2 = D.copy(); D2["stack"] = F2["stack_all"].reindex(D2.index).values
    D2 = D2[(D2["stack"] > 0) & (D2["actual"] / D2["stack"]).between(0.25, 1.8)]
    Xf = mkX_for(D2, mkX, D)
    full = fit_additive(Xf, np.log(D2["actual"].values / D2["stack"].values), FAC)
    try: old = json.load(open(os.path.join(HERE, "public", "villa-winbid.json"), encoding="utf-8"))
    except Exception: old = {}
    out = {"n": int(len(D2)), "oos": oos, "byLevel": g("lvl"), "byAge": g("age"), "byFloor": g("fl"), "floorRatio": flr, "floorResale": old.get("floorResale", {}), "ratioMed": round(float((D2["actual"] / D2["stack"]).median()), 3),
           "resQ": resq, "factors": [f for f, _ in FAC], "base": full[0], "eff": {f: {str(k): round(float(v), 4) for k, v in d.items()} for f, d in full[1].items()}, "estBasis": "stack", "generatedAt": datetime.now(timezone.utc).isoformat()}
    print(json.dumps({k: out[k] for k in ("n", "oos", "byLevel", "ratioMed")}, ensure_ascii=False, indent=1))
    json.dump(out, open("villa-winbid.json", "w", encoding="utf-8"), ensure_ascii=False); print("저장 villa-winbid.json")


def mkX_for(D2, mkX, D):
    """mkX는 바깥 D를 쓰므로 같은 열(예상매도가만 다름)로 요인 키를 다시 만든다 - lb(최저가÷예상매도가)만 바뀜"""
    X = mkX(D["stack"]).reindex(D2.index)
    X["lb"] = np.clip(np.floor(np.log(D2["minbid"] / D2["stack"]) / 0.05), -24, 9).astype(int).astype(str)
    return X


def fails_from_ratio(minb, appr):
    if not appr or not minb or appr <= 0: return None
    r = minb / appr
    for k, lim in enumerate((0.9, 0.72, 0.58, 0.47, 0.38, 0.31, 0.25)):
        if r >= lim: return k
    return 6


def fit_additive(X, y, factors, iters=6):
    base = float(np.median(y)); eff = {f: {} for f, _ in factors}; pred = np.full(len(y), base)
    for _ in range(iters):
        for f, k in factors:
            cur = X[f].map(eff[f]).fillna(0).values; r = y - (pred - cur)
            g = pd.DataFrame({"k": X[f].values, "r": r}).groupby("k")["r"].agg(["median", "count"])
            new = (g["median"] * g["count"] / (g["count"] + k)).to_dict(); eff[f] = new
            pred = pred - cur + X[f].map(new).fillna(0).values
    return base, eff


def predict_additive(m, X, factors):
    base, eff = m; p = np.full(len(X), base)
    for f, _ in factors: p = p + X[f].map(eff[f]).fillna(0).values
    return p


def eval_winbid(df, pt, featurize, pt_all=None):
    """빌라 예상 낙찰가 채점(2026-11-07): 낙찰사례(수도권 빌라, 2024~)의 낙찰가를 ① 예전 예상매도가(시험용 기본 추정) 기준 모델 ② 같은 모델에 종합 예상매도가를 넣은 것(앱이 지금 하는 일) ③ 종합 값으로 다시 학습한 모델로 예측.
    학습 = 2026-06 이전 사례, 시험 = 2026-06~(학습에 안 쓴 구간). 종합 모델(점 보정)도 2026-06 이전 거래로만 학습해 시험 구간 정보가 새지 않게 함."""
    cases = pd.DataFrame(requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json())
    c = cases[cases["propertyType"].astype(str).str.contains("다세대|연립|도시형", na=False)].copy()
    c["actual"] = pd.to_numeric(c["finalBidPrice"], errors="coerce") / 10000.0; c["minbid"] = pd.to_numeric(c["minBidPrice"], errors="coerce") / 10000.0
    c["appr"] = pd.to_numeric(c["appraisalPrice"], errors="coerce") / 10000.0; c["area"] = pd.to_numeric(c["areaM2"], errors="coerce"); c["fl"] = pd.to_numeric(c["floor"], errors="coerce")
    c = c[(c["actual"] > 0) & (c["minbid"] > 0) & c["area"].between(15, 150) & c["saleDate"].astype(str).str.match(r"^\d{4}-\d\d-\d\d$", na=False)]
    c["region"] = c["addrJibun"].map(trade_region); c = c.dropna(subset=["region", "dong", "bunji"])
    c["dong"] = c["dong"].astype(str).str.strip().str.split().str[-1]; c["bunji"] = c["bunji"].astype(str).str.strip()
    c["sale"] = c["saleDate"].str.replace("-", "").astype(int); c = c[c["sale"] >= 20240101]
    c = c[c["region"].isin(set(df["region"].unique()))]
    byb = df.dropna(subset=["build_year"]).groupby(["region", "dong", "bunji"])["build_year"].agg(lambda s: s.mode().iloc[0]).to_dict()
    T = pd.DataFrame({"region": c["region"].values, "dong": c["dong"].values, "bunji": c["bunji"].values, "size": c["area"].values, "floor": c["fl"].values, "price": c["actual"].values,
                      "day": (pd.to_datetime(c["sale"].astype(str), format="%Y%m%d") - EPOCH).dt.days.values,
                      "lat": pd.to_numeric(c.get("lat"), errors="coerce").values, "lon": pd.to_numeric(c.get("lon"), errors="coerce").values})
    T["build_year"] = [byb.get((r, d, b), np.nan) for r, d, b in zip(T["region"], T["dong"], T["bunji"])]
    T["by2"] = T["build_year"]; T["bld"] = T["region"] + "|" + T["dong"] + "|" + T["bunji"]; T["dk"] = T["region"] + "|" + T["dong"]
    bl = df.dropna(subset=["elv"]).groupby("bld").agg(elv=("elv", "last"), grnd=("grnd", "last"), hh=("hh", "last"))
    for col in ("elv", "grnd", "hh"): T[col] = T["bld"].map(bl[col]) if len(bl) else np.nan
    T.index = c.index + 30_000_000
    F = featurize(T); F["stack"] = F["base"] * np.exp(np.clip(pt.predict(F[COLS]), -0.4, 0.4))
    c2 = c.loc[F.index - 30_000_000].copy(); c2.index = F.index
    D = c2.join(F[["base", "stack", "lvl", "sido"]]); D["by"] = T["build_year"].reindex(D.index)
    D = D[(D["base"] > 0) & (D["stack"] > 0)]
    D = D[(D["actual"] / D["base"]).between(0.25, 1.8) & (D["actual"] / D["stack"]).between(0.25, 1.8)].copy()
    D["fails"] = [fails_from_ratio(m_, a_) for m_, a_ in zip(D["minbid"], D["appr"])]
    FAC = [("lb", 10), ("fails", 120), ("region", 120), ("size", 30), ("floor", 30), ("age", 60), ("lvl", 60), ("season", 300)]
    def mkX(est):
        X = pd.DataFrame(index=D.index)
        X["lb"] = np.clip(np.floor(np.log(D["minbid"] / est) / 0.05), -24, 9).astype(int).astype(str)
        X["fails"] = D["fails"].map(lambda v: "?" if v is None or pd.isna(v) else str(min(int(v), 4)))
        X["region"] = D["region"].values
        X["size"] = D["area"].map(lambda a: "40↓" if a < 40 else ("40~60" if a < 60 else ("60~85" if a < 85 else "85↑"))).values
        X["floor"] = D["fl"].map(lambda f: "지하" if f <= 0 else ("1층" if f == 1 else ("2~3층" if f <= 3 else "4층+"))).values
        X["age"] = D["by"].map(lambda b: "?" if pd.isna(b) else ("~10년" if 2026 - b <= 10 else ("11~20" if 2026 - b <= 20 else ("21~30" if 2026 - b <= 30 else "31+")))).values
        X["lvl"] = D["lvl"].values
        X["season"] = D["sale"].map(lambda d: "겨울" if (d // 100) % 100 in (12, 1, 2) else ("봄" if (d // 100) % 100 <= 5 else ("여름" if (d // 100) % 100 <= 8 else "가을"))).values
        return X
    Xb, Xs = mkX(D["base"]), mkX(D["stack"])
    tr = (D["sale"] < 20260601).values; te = ~tr
    print(f"학습 {tr.sum():,} / 시험(2026-06~) {te.sum():,}")
    act = D["actual"].values
    mA = fit_additive(Xb[tr], np.log(act[tr] / D["base"].values[tr]), FAC)
    mB = fit_additive(Xs[tr], np.log(act[tr] / D["stack"].values[tr]), FAC)
    if pt_all is not None:
        return fit_winbid(D, F, T, c2, pt_all, mkX, FAC, Xs, tr, te, mB, featurize)
    pr = {"① 예전 예상매도가+예전 모델": D["base"].values * np.exp(predict_additive(mA, Xb, FAC)),
          "② 종합 예상매도가+예전 모델(앱 지금)": D["stack"].values * np.exp(predict_additive(mA, Xs, FAC)),
          "③ 종합 예상매도가+다시 학습": D["stack"].values * np.exp(predict_additive(mB, Xs, FAC)),
          "(기준) 예상매도가 자체×0.755": D["stack"].values * 0.755}
    def st(mask):
        o = {}
        for k, p in pr.items():
            e = p[mask] / act[mask] - 1; o[k] = {"n": int(mask.sum()), "오차%": round(float(np.median(np.abs(e))) * 100, 2), "±10%": round(float((np.abs(e) <= .1).mean()) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 2),
                                                "높게 예상 10%+": round(float((e > .10).mean()) * 100, 1), "낮게 예상 10%+": round(float((e < -.10).mean()) * 100, 1),
                                                "예상가 이하 낙찰%": round(float((act[mask] <= p[mask]).mean()) * 100, 1)}
        return o
    out = {"학습 n": int(tr.sum()), "시험 n": int(te.sum()), "전체": st(te)}
    out["서울"] = st(te & (D["sido"].values == 0)); out["인천·경기"] = st(te & (D["sido"].values > 0))
    for l in sorted(set(D["lvl"].values[te])):
        m_ = te & (D["lvl"].values == l)
        if m_.sum() >= 60: out["단계 " + l] = st(m_)
    out["낙찰가÷예상매도가 중앙"] = {"예전": round(float(np.median(act[te] / D["base"].values[te])), 3), "종합": round(float(np.median(act[te] / D["stack"].values[te])), 3)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    now = datetime.now(timezone.utc).isoformat()
    cyc.upsert_rows([{"id": "signal|__villa_bt_winbideval__", "payload": cyc.clean_json(dict(out, generatedAt=now)), "fetched_at": now}]); print("서버 저장: winbideval")


if __name__ == "__main__":
    main()
