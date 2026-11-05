"""📈 시장 흐름 연구실(2026-11-05, 사용자 요청) - 세 가지를 한 번에 계산해 서버(signal|__flow_lab__, signal|__flow_forecast__)에 저장

1) 생활권 흐름: 단지마다 반경 안 단지들의 거래를 모아 월별 가격 지수·거래량을 만듦. 단지·크기대별 고정효과(그 단지·크기의 평균 로그가격)를 빼서 단지 구성이 달라져도 흔들리지 않게 하고,
   반경은 "최근 12개월 거래가 충분해질 때까지" 1→2→3→5km로 넓힘(거래가 적은 지방은 자동으로 넓어짐).
2) 보정계수 점검: 실제 거래(2025~)를 "30일 전 시점의 시세로 맞혔나"로 평가 - 시세 = 같은 단지·평형 최근 6개월 거래의 가중 중위값, 여기에 흐름 보정(계수 s·연율 흐름·거래량 믿음도·거래 나이)을 바꿔 가며
   (계수 0·0.3·0.6·1·1.5, 거래량 믿음도 유/무, 불확실(|z|<1) 건너뜀 유/무, 범위, 흐름 측정 단위 단지·법정동·시군구·생활권) 어느 조합이 실제 거래가에 가장 가까운지 비교.
3) 유사 구간 예측(주식 차트처럼): 단지별 생활권의 '지난 24개월 가격·거래량 궤적'을 특징으로, 과거에 비슷했던 (단지, 달)들을 찾아 그 뒤 3개월 가격 변화의 가중평균을 예측으로 씀.
   과거 구간으로 시험(라이브러리는 시험 시작 3개월 전까지만) - 0 변화·추세 지속·그룹 평균과 비교, 현재 시점 예측과 '어느 시기와 닮았나'(유사 달 분포)를 입찰물건마다 저장.
사용: GitHub Actions 'Analyze flow lab' (트리거 파일 .github/triggers/analyze-flow-lab.txt 를 고쳐 올리면 실행). 결과는 로그·아티팩트·서버(signal|__flow_lab__)에 남음."""
import os, re, json, time, math
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cyc)
avm = cyc.avm
SITE_URL = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
T0 = time.time()
def log(*a): print(f"[{(time.time() - T0) / 60:5.1f}분]", *a, flush=True)
REPORT = {"generatedAt": datetime.now(timezone.utc).isoformat()}


def region_cls(r):
    s = str(r or "")[:2]
    return "수도권" if s in ("서울", "경기", "인천") else "지방"


# ───────────── 0. 데이터 ─────────────
log("실거래 불러오는 중")
tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,deal_date,dealing_type,cdeal_type,road_name,main_num,sub_num", extra_filter=f"&deal_date=gte.{cyc.START_DATE}")
if "cdeal_type" in tr.columns:
    tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""]
if "dealing_type" in tr.columns:
    tr = tr[tr["dealing_type"] != "직거래"]
for c in ("price", "size", "deal_date"):
    tr[c] = pd.to_numeric(tr[c], errors="coerce")
tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10)].copy()
tr["deal_date"] = tr["deal_date"].astype(np.int64)
tr["lp"] = np.log(tr["price"] / tr["size"])
tr["cls"] = tr["region"].map(region_cls)
log(f"실거래 {len(tr):,}건")


def _ck(dong, danji, bunji, road, mn, sn):
    mn = 0 if mn is None or (isinstance(mn, float) and np.isnan(mn)) else int(float(mn))
    sn = "" if sn is None or (isinstance(sn, float) and np.isnan(sn)) or str(sn).strip() in ("", "0", "0.0") else str(int(float(sn)))
    return "|".join(str(x) for x in [dong or "", danji or "", bunji or "", road or "", mn, sn]).lower()
tk = tr[["dong", "danji", "bunji", "road_name", "main_num", "sub_num"]].drop_duplicates()
tk["ckey"] = [_ck(*r_) for r_ in tk[["dong", "danji", "bunji", "road_name", "main_num", "sub_num"]].itertuples(index=False, name=None)]
tr = tr.merge(tk, on=["dong", "danji", "bunji", "road_name", "main_num", "sub_num"], how="left")
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&lat=not.is.null")
cc["ck"] = cc["cache_key"].astype(str).str.lower(); cc = cc.drop_duplicates("ck").set_index("ck")
tr = tr[tr["ckey"].isin(cc.index)].copy()
tr["lat"] = cc["lat"].reindex(tr["ckey"]).values.astype(float); tr["lon"] = cc["lon"].reindex(tr["ckey"]).values.astype(float)
tr = tr.dropna(subset=["lat", "lon"]).drop(columns=["road_name", "main_num", "sub_num", "bunji", "danji", "dealing_type", "cdeal_type"], errors="ignore").copy()
tr["y"] = tr["deal_date"] // 10000; tr["mo"] = (tr["deal_date"] // 100) % 100
tr["m"] = ((tr["y"] - 2017) * 12 + tr["mo"] - 1).astype(int)
NM = int(tr["m"].max()) + 1; NOW_M = NM - 1       # 마지막 달(진행 중일 수 있음)
log(f"좌표 있는 거래 {len(tr):,}건, 단지 {tr['ckey'].nunique():,}곳, 월 {NM}개")
# 단지×크기대 그룹 고정효과
tr["sb"] = (tr["size"] // 10).astype(int)
tr["gkey"] = tr["ckey"] + "|" + tr["sb"].astype(str)
gstat = tr.groupby("gkey")["lp"].agg(["mean", "count"])
gok = gstat[gstat["count"] >= 3].index
tr = tr[tr["gkey"].isin(gok)].copy()
tr["res"] = tr["lp"] - tr["gkey"].map(gstat["mean"])
gcodes, gnames = pd.factorize(tr["gkey"]); G = len(gnames)
tr["g"] = gcodes
gmeta = tr.groupby("g").agg(lat=("lat", "first"), lon=("lon", "first"), ck=("ckey", "first"), cls=("cls", "first"), region=("region", "first"), dong=("dong", "first")).sort_index()
flat = tr["g"].values * NM + tr["m"].values
S = np.bincount(flat, weights=tr["res"].values, minlength=G * NM).reshape(G, NM).astype(np.float32)
Q = np.bincount(flat, weights=tr["res"].values ** 2, minlength=G * NM).reshape(G, NM).astype(np.float32)
N = np.bincount(flat, minlength=G * NM).reshape(G, NM).astype(np.float32)
log(f"그룹 {G:,}개 월별 합계 완성")

# ───────────── 1. 생활권(반경) 지수 ─────────────
from sklearn.neighbors import BallTree
import scipy.sparse as sp
ck_u = gmeta.groupby("ck").agg(lat=("lat", "first"), lon=("lon", "first"), cls=("cls", "first"), region=("region", "first"), dong=("dong", "first"))
C = len(ck_u); ck_idx = {k: i for i, k in enumerate(ck_u.index)}
g2c = np.array([ck_idx[k] for k in gmeta["ck"]])
tree = BallTree(np.radians(gmeta[["lat", "lon"]].values), metric="haversine")
cx_xy = np.radians(ck_u[["lat", "lon"]].values)
RADII = (1.0, 2.0, 3.0, 5.0)
roll = lambda A, w=3: np.stack([A[:, max(0, i - w + 1):i + 1].sum(axis=1) for i in range(A.shape[1])], axis=1)
# 단지별 반경: 최근 12개월 거래가 150건 이상 되는 가장 작은 반경(없으면 5km). 만족한 단지는 다음 반경 계산에서 빼서 큰 반경 계산을 줄임(대도시는 1~2km에서 끝남)
cS, cQ, cN = (np.zeros((C, NM), np.float32) for _ in range(3)); rad_pick = np.full(C, RADII[-1]); remaining = np.arange(C)
for km in RADII:
    if len(remaining) == 0: break
    ind = tree.query_radius(cx_xy[remaining], r=km / 6371.0)
    rows = np.repeat(np.arange(len(remaining)), [len(x) for x in ind]); cols = np.concatenate(ind) if len(remaining) else np.array([], int)
    A = sp.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(remaining), G))
    n12 = np.asarray(A @ N[:, NOW_M - 11:NOW_M + 1]).sum(axis=1)
    done = (n12 >= 150) | (km == RADII[-1])
    if done.any():
        d_idx = np.where(done)[0]; Ad = A[d_idx]
        cS[remaining[d_idx]] = np.asarray(Ad @ S); cQ[remaining[d_idx]] = np.asarray(Ad @ Q); cN[remaining[d_idx]] = np.asarray(Ad @ N); rad_pick[remaining[d_idx]] = km
    log(f"반경 {km}km: 이번에 확정 {int(done.sum()):,}곳 (남은 {int((~done).sum()):,}곳, 이웃 그룹 평균 {len(cols) / max(len(remaining), 1):.0f}개)")
    remaining = remaining[~done]
REPORT["radiusPick"] = {str(km): int((rad_pick == km).sum()) for km in RADII}; REPORT["complexes"] = C
log("단지별 생활권 반경 선택:", REPORT["radiusPick"])
S3, Q3, N3 = roll(cS), roll(cQ), roll(cN)
with np.errstate(invalid="ignore", divide="ignore"):
    P3 = np.where(N3 >= 10, S3 / N3, np.nan)           # 3개월 가격 지수(로그 잔차 평균)
    VAR3 = np.where(N3 >= 10, Q3 / N3 - P3 ** 2, np.nan)
    V3 = N3.copy()   # 3개월 거래 수

# 다른 단위 지수(보정계수 비교용): 법정동·시군구
def level_index(keys):
    codes, _ = pd.factorize(keys); K = codes.max() + 1
    M = sp.csr_matrix((np.ones(G, np.float32), (codes, np.arange(G))), shape=(K, G))
    s, q, n = M @ S, M @ Q, M @ N
    s3, q3, n3 = roll(np.asarray(s)), roll(np.asarray(q)), roll(np.asarray(n))
    with np.errstate(invalid="ignore", divide="ignore"):
        p3 = np.where(n3 >= 10, s3 / n3, np.nan); v3 = np.where(n3 >= 10, q3 / n3 - p3 ** 2, np.nan)
    return codes, p3, v3, n3
dong_codes, dP3, dVAR3, dN3 = level_index((gmeta["region"].astype(str) + "|" + gmeta["dong"].astype(str)).values)
sgg_codes, sP3, sVAR3, sN3 = level_index(gmeta["region"].astype(str).values)

# ───────────── 2. 보정계수 점검 ─────────────
def backtest_coeff():
    rng = np.random.default_rng(7)
    # 대상 거래: 2025-01 이후, 같은 단지·크기(±3㎡)의 앞선 거래가 30일 전 기준 6개월 안에 3건 이상
    tt = tr[tr["m"] >= (2025 - 2017) * 12].copy()
    tt = tt.sample(n=min(len(tt), 40000), random_state=7)
    by_c = {k: g_.sort_values("deal_date") for k, g_ in tr[tr["m"] >= (2024 - 2017) * 12].groupby("ckey")}
    def ord_(d):
        d = np.asarray(d, dtype=np.int64); y = d // 10000; m = (d // 100) % 100; dd = d % 100; y = y - (m <= 2); era = y // 400; yoe = y - era * 400
        mp = np.where(m > 2, m - 3, m + 9); doy = (153 * mp + 2) // 5 + dd - 1; doe = yoe * 365 + yoe // 4 - yoe // 100 + doy; return era * 146097 + doe - 719468
    recs = []
    for r in tt.itertuples(index=False):
        g_ = by_c.get(r.ckey)
        if g_ is None: continue
        o_all = g_["_o"].values if "_o" in g_.columns else None
        if o_all is None:
            g_ = g_.assign(_o=ord_(g_["deal_date"].values)); by_c[r.ckey] = g_; o_all = g_["_o"].values
        to = int(ord_([r.deal_date])[0]); cut = to - 30
        sel = (o_all < cut) & (o_all >= cut - 183) & (np.abs(g_["size"].values - r.size) <= 3)
        if sel.sum() < 3: continue
        ages = (cut - o_all[sel]) / 30.4; prices = (g_["price"].values[sel]).astype(float)
        cm = max(3, min(NM - 1, ((r.y - 2017) * 12 + r.mo - 1) - 2))   # 거래 달의 2개월 전 달까지 완결된 자료만(30일 전 시점의 보수적 근사)
        ci = ck_idx.get(r.ckey)
        if ci is None: continue
        recs.append((r.price, r.cls, prices, ages, cm, ci, int(r.g), int(dong_codes[int(r.g)]), int(sgg_codes[int(r.g)])))
    log(f"보정계수 점검 대상 {len(recs):,}건")
    def est_base(prices, ages, cls, fac=None):
        p = prices * (fac if fac is not None else 1.0)
        if cls == "수도권" and False: pass
        w = 0.5 ** (ages / (1.0 if cls == "수도권" else 2.0))
        o = np.argsort(p); pp, ww = p[o], w[o]; c_ = (np.cumsum(ww) - 0.5 * ww) / ww.sum(); return float(np.interp(0.5, c_, pp))
    def flow_at(level, cm, ci, gi, di, si):
        if level == "radius": P, V, Nn = P3[ci], VAR3[ci], N3[ci]
        elif level == "dong": P, V, Nn = dP3[di], dVAR3[di], dN3[di]
        elif level == "sgg": P, V, Nn = sP3[si], sVAR3[si], sN3[si]
        else: return None
        a, b = P[cm], P[cm - 3]
        if not (np.isfinite(a) and np.isfinite(b)): return None
        na, nb = Nn[cm], Nn[cm - 3]
        se = math.sqrt(max(V[cm], 1e-6) / max(na, 1) + max(V[cm - 3], 1e-6) / max(nb, 1)) if np.isfinite(V[cm]) and np.isfinite(V[cm - 3]) else 0.05
        vol = math.log((na + 1) / (nb + 1))
        return {"rate": (a - b) / 0.25, "z": (a - b) / max(se, 0.003), "vol": vol}
    def gate(rate, vol):
        if rate > 0: return 1.0 if vol >= 0.2 else (0.75 if vol > -0.2 else 0.4)
        return 1.0 if vol <= -0.2 else (0.75 if vol < 0.2 else 0.5)
    levels = ("radius", "dong", "sgg")
    results = {}
    grid = [(s_, gt, zt, cl) for s_ in (0.0, 0.6, 1.0, 1.5, 2.0, 3.0, 4.0) for gt in (False, True) for zt in (False, True) for cl in ((0.95, 1.08), (0.90, 1.15))]
    err = {(lv, gp): [] for lv in levels for gp in grid}; base_err = []; meta = []
    for (price, cls, prices, ages, cm, ci, gi, di, si) in recs:
        b0 = est_base(prices, ages, cls); base_err.append(math.log(b0 / price)); meta.append(cls)
        for lv in levels:
            f = flow_at(lv, cm, ci, gi, di, si)
            for gp in grid:
                s_, gt, zt, cl = gp
                if f is None or s_ == 0 or (zt and abs(f["z"]) < 1.0):
                    err[(lv, gp)].append(math.log(b0 / price)); continue
                gg = gate(f["rate"], f["vol"]) if gt else 1.0
                fac = np.clip(np.exp(s_ * f["rate"] * gg * ages / 12.0), cl[0], cl[1])
                err[(lv, gp)].append(math.log(est_base(prices, ages, cls, fac) / price))
    meta = np.array(meta); base_err = np.array(base_err)
    def stat(e, mk=None):
        e = np.asarray(e); e = e if mk is None else e[mk]
        return {"n": int(len(e)), "medAbs%": round(float(np.median(np.abs(e))) * 100, 3), "bias%": round(float(np.median(e)) * 100, 3), "in5%": round(float((np.abs(e) <= 0.05).mean()) * 100, 1)}
    out = {"n": len(recs), "보정 없음": {"전체": stat(base_err), "수도권": stat(base_err, meta == "수도권"), "지방": stat(base_err, meta == "지방")}, "단위별 최적": {}, "단위별_계수별": {}}
    for lv in levels:
        rows = []
        for gp in grid:
            e = np.array(err[(lv, gp)]); rows.append({"계수": gp[0], "거래량믿음도": gp[1], "불확실건너뜀": gp[2], "범위": list(gp[3]), "전체": stat(e), "수도권": stat(e, meta == "수도권"), "지방": stat(e, meta == "지방")})
        rows.sort(key=lambda r: r["전체"]["medAbs%"])
        out["단위별 최적"][lv] = rows[:3]
        # 계수별 최선(다른 설정은 최선으로)
        byS = {}
        for r in rows:
            if r["계수"] not in byS: byS[r["계수"]] = r
        out["단위별_계수별"][lv] = {str(k): v["전체"] for k, v in sorted(byS.items())}
    return out

try:
    REPORT["coeff"] = backtest_coeff()
    for lv, rows in REPORT["coeff"]["단위별 최적"].items():
        log(f"보정계수 점검 [{lv}] 최적:", json.dumps(rows[0], ensure_ascii=False))
    log("보정 없음:", json.dumps(REPORT["coeff"]["보정 없음"], ensure_ascii=False))
except Exception as e:
    import traceback; traceback.print_exc(); REPORT["coeff"] = {"error": str(e)}; log("보정계수 점검 실패:", e)

# ───────────── 3. 유사 구간 예측 ─────────────
def build_features(t_idx):
    """각 단지의 t달 특징: 가격 궤적(현재 − k개월 전, k=3,6,9,12,18,24) + 거래량 궤적(로그비 k=3,6,12,24). 값이 하나라도 없으면 NaN 행"""
    feats = []
    for k in (3, 6, 9, 12, 18, 24):
        feats.append(P3[:, t_idx] - P3[:, t_idx - k])
    for k in (3, 6, 12, 24):
        feats.append(np.log((V3[:, t_idx] + 1) / (V3[:, t_idx - k] + 1)))
    return np.stack(feats, axis=1)
def fwd(t_idx):      # 앞으로 3개월 가격 변화(로그)
    return P3[:, t_idx + 3] - P3[:, t_idx]
try:
    from sklearn.neighbors import NearestNeighbors
    cls_arr = (ck_u["cls"].values)
    t_lo = 30; t_test_lo = NOW_M - 14; t_test_hi = NOW_M - 3          # 시험 달: 결과가 이미 나온 최근 12개월
    lib_hi = t_test_lo - 3                                              # 라이브러리: 시험 시작 3개월 전까지만(결과를 알 수 있는 것만)
    rng = np.random.default_rng(11)
    def collect(ts, cap, want_fwd=True):
        X, Y, TT, CI = [], [], [], []
        for t in ts:
            f = build_features(t); y = fwd(t) if want_fwd else np.zeros(C)
            ok = np.isfinite(f).all(axis=1) & (np.isfinite(y) if want_fwd else True)
            idx = np.where(ok)[0]
            if len(idx) > cap: idx = rng.choice(idx, cap, replace=False)
            X.append(f[idx]); Y.append(y[idx]); TT.append(np.full(len(idx), t)); CI.append(idx)
        return (np.vstack(X), np.concatenate(Y), np.concatenate(TT), np.concatenate(CI)) if X else (None,) * 4
    K = 40
    def run_bt(test_lo, gap, tag):
        """시험 달 12개월(test_lo..test_lo+11), 라이브러리는 시험 시작 gap개월 전까지(gap=12면 같은 단지의 최근 12개월 흔적을 제외한 진짜 과거 구간)"""
        hi = test_lo - gap
        LX, LY, LT, LC = collect(range(t_lo, hi + 1), max(1, 160000 // max(hi - t_lo + 1, 1)))
        QX, QY, QT, QC = collect(range(test_lo, test_lo + 12), max(1, 60000 // 12))
        mu, sd = LX.mean(axis=0), LX.std(axis=0) + 1e-6; Lz, Qz = (LX - mu) / sd, (QX - mu) / sd
        res = {}
        for cl in ("수도권", "지방", "전체"):
            lm = (cls_arr[LC] == cl) if cl != "전체" else np.ones(len(LC), bool); qm = (cls_arr[QC] == cl) if cl != "전체" else np.ones(len(QC), bool)
            if lm.sum() < 500 or qm.sum() < 200: continue
            nn = NearestNeighbors(n_neighbors=K).fit(Lz[lm]); dist, ind = nn.kneighbors(Qz[qm])
            w = 1.0 / (dist + 0.3); pred = (LY[lm][ind] * w).sum(axis=1) / w.sum(axis=1); y = QY[qm]
            mom = QX[qm][:, 0]; grp = np.full(len(y), float(np.median(LY[lm])))
            m_ = lambda p_: {"MAE%": round(float(np.mean(np.abs(p_ - y))) * 100, 3), "방향적중%": round(float((np.sign(p_) == np.sign(y))[np.abs(y) > 0.005].mean()) * 100, 1), "상관": round(float(np.corrcoef(p_, y)[0, 1]), 3) if np.std(p_) > 0 else None}
            slope = float((pred * y).sum() / max((pred * pred).sum(), 1e-9))     # 예측을 얼마나 줄여 써야 맞는지(원점 회귀)
            r = {"n": int(qm.sum()), "유사구간 예측": m_(pred), "줄여 쓴 예측": m_(pred * min(max(slope, 0), 1)), "변화 없음(0)": m_(np.zeros(len(y))), "추세 지속": m_(mom), "과거 평균": m_(grp), "줄이는 비율": round(slope, 3), "라이브러리 마지막 달": int(hi)}
            qs = np.quantile(pred, [0, 0.2, 0.4, 0.6, 0.8, 1.0]); r["예측 5분위별 실제 중앙값%"] = [round(float(np.median(y[(pred >= qs[i]) & (pred <= qs[i + 1])])) * 100, 2) for i in range(5)]
            r["예측 5분위별 예측 중앙값%"] = [round(float(np.median(pred[(pred >= qs[i]) & (pred <= qs[i + 1])])) * 100, 2) for i in range(5)]
            res[cl] = r; log(f"유사 구간 예측 시험 [{tag}·{cl}]:", json.dumps(r, ensure_ascii=False))
        return res
    bt = {}
    for tag, test_lo, gap in (("최근1년·간격3", NOW_M - 14, 3), ("최근1년·간격12", NOW_M - 14, 12), ("그 전 1년·간격12", NOW_M - 26, 12), ("그 전 1년·간격3", NOW_M - 26, 3)):
        try: bt[tag] = run_bt(test_lo, gap, tag)
        except Exception as e: log("시험 건너뜀", tag, e)
    # 줄이는 비율: 간격12 시험 두 해 평균(클래스별)
    shrink = {}
    for cl in ("수도권", "지방"):
        v = [bt[t][cl]["줄이는 비율"] for t in ("최근1년·간격12", "그 전 1년·간격12") if t in bt and cl in bt[t]]
        shrink[cl] = round(float(min(max(np.mean(v), 0.0), 1.0)), 3) if v else 0.5
    log("줄이는 비율(간격12 두 해 평균):", shrink)
    t_test_lo = NOW_M - 14; lib_hi = t_test_lo - 12
    REPORT["analog"] = {"backtest": bt, "libraryMonths": [int(lib_hi), t_lo], "testMonths": [int(t_test_lo), int(t_test_lo + 11)], "K": K, "shrink": shrink}
    # 현재 예측: 라이브러리 = 결과가 나온 모든 달(t ≤ NOW_M-3)
    hi2 = NOW_M - 1 - 12      # 지금 달에서 12개월 넘게 지난 구간만(같은 단지의 최근 흔적 제외 - 진짜 과거 구간과 비교)
    LX2, LY2, LT2, LC2 = collect(range(t_lo, hi2 + 1), max(1, 220000 // max(hi2 - t_lo + 1, 1)))
    mu2, sd2 = LX2.mean(axis=0), LX2.std(axis=0) + 1e-6; Lz2 = (LX2 - mu2) / sd2
    tnow = NOW_M - 1                       # 마지막 완결 달(진행 중인 달 제외)
    Fx = build_features(tnow); okc = np.isfinite(Fx).all(axis=1); ci_ok = np.where(okc)[0]
    log(f"현재 특징을 가진 단지 {len(ci_ok):,}곳 / {C:,}곳")
    cur = {}
    for cl in ("수도권", "지방"):
        lm = (cls_arr[LC2] == cl); cm_ = ci_ok[cls_arr[ci_ok] == cl]
        if lm.sum() < 500 or len(cm_) == 0: continue
        nn = NearestNeighbors(n_neighbors=K).fit(Lz2[lm]); dist, ind = nn.kneighbors((Fx[cm_] - mu2) / sd2)
        w = 1.0 / (dist + 0.3); pred = (LY2[lm][ind] * w).sum(axis=1) / w.sum(axis=1); spread = np.sqrt(((LY2[lm][ind] - pred[:, None]) ** 2 * w).sum(axis=1) / w.sum(axis=1))
        tl = LT2[lm][ind]
        for j, ci in enumerate(cm_):
            mo = np.array(tl[j]); ym = (2017 + mo // 12) * 100 + mo % 12 + 1; cnt = pd.Series(ym).value_counts().head(3)
            cur[int(ci)] = {"fc3": round(float(pred[j]), 4), "fc3s": round(float(pred[j]) * shrink.get(cl, 0.5), 4), "sd": round(float(spread[j]), 4), "analog": [[int(k_), int(v_)] for k_, v_ in cnt.items()], "dist": round(float(dist[j].mean()), 3)}
    # 시군구별 요약(현재 예측 평균, 유사 시기 분포)
    sg = {}
    for ci, v in cur.items():
        rg = ck_u["region"].iloc[ci]; d = sg.setdefault(rg, {"fc": [], "ym": {}, "n": 0}); d["fc"].append(v["fc3"]); d["n"] += 1
        for k_, c_ in v["analog"]: d["ym"][k_] = d["ym"].get(k_, 0) + c_
    REPORT["analog"]["bySigungu"] = {rg: {"n": d["n"], "fc3Median%": round(float(np.median(d["fc"])) * 100, 2), "analogTop": sorted(d["ym"].items(), key=lambda x: -x[1])[:4]} for rg, d in sg.items() if d["n"] >= 15}
    allym = {}
    for v in cur.values():
        for k_, c_ in v["analog"]: allym[k_] = allym.get(k_, 0) + c_
    REPORT["analog"]["currentAnalogMonths"] = sorted(allym.items(), key=lambda x: -x[1])[:12]
    log("현재와 닮은 시기(상위):", REPORT["analog"]["currentAnalogMonths"])
    # 입찰물건에 연결(단지 좌표 가장 가까운 곳 200m 안)
    try:
        auc = requests.get(f"{SITE_URL}/api/auction", timeout=120).json()
        cxt = BallTree(cx_xy, metric="haversine"); items = {}
        def rad_flow(ci, cm):    # 생활권 가격 흐름(앱이 시세 보정에 씀): 연율 변화·확실도 z·거래량 변화
            a_, b_ = P3[ci, cm], P3[ci, cm - 3]
            if not (np.isfinite(a_) and np.isfinite(b_)): return None
            na, nb = N3[ci, cm], N3[ci, cm - 3]; va, vb = VAR3[ci, cm], VAR3[ci, cm - 3]
            se = math.sqrt(max(va, 1e-6) / max(na, 1) + max(vb, 1e-6) / max(nb, 1)) if np.isfinite(va) and np.isfinite(vb) else 0.05
            return {"rate": round(float((a_ - b_) / 0.25), 4), "z": round(float((a_ - b_) / max(se, 0.003)), 2), "vol": round(float(math.log((na + 1) / (nb + 1))), 3)}
        for a in auc:
            if a.get("propType") != "apt" or not a.get("lat") or not a.get("lon"): continue
            d_, i_ = cxt.query(np.radians([[float(a["lat"]), float(a["lon"])]]), k=1)
            if d_[0][0] * 6371.0 > 0.2: continue
            ci = int(i_[0][0]); v = cur.get(ci)
            if not v: continue
            items[str(a["id"])] = {**v, "rate3": round(float(P3[ci, tnow] - P3[ci, tnow - 3]), 4), "vol3": round(float(np.log((V3[ci, tnow] + 1) / (V3[ci, tnow - 3] + 1))), 3), "km": float(rad_pick[ci]), "rf": rad_flow(ci, tnow), "n12": int(cN[ci, NOW_M - 11:NOW_M + 1].sum())}
        REPORT["analog"]["auctionsMatched"] = len(items); log(f"입찰물건 {len(items):,}건에 연결")
        cyc.upsert_rows([{"id": "signal|__flow_forecast__", "payload": cyc.clean_json({"generatedAt": REPORT["generatedAt"], "month": int(tnow), "items": items}), "fetched_at": REPORT["generatedAt"]}])
    except Exception as e:
        log("입찰물건 연결 건너뜀:", e)
except Exception as e:
    import traceback; traceback.print_exc(); REPORT["analog"] = {"error": str(e)}; log("유사 구간 예측 실패:", e)

# ───────────── 저장 ─────────────
try:
    cyc.upsert_rows([{"id": "signal|__flow_lab__", "payload": cyc.clean_json(REPORT), "fetched_at": REPORT["generatedAt"]}])
    json.dump(REPORT, open("flow-lab-report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 흐름 연구실\n```json\n" + json.dumps({k: v for k, v in REPORT.items() if k != "analog"}, ensure_ascii=False, indent=1)[:6000] + "\n```\n")
    log("저장 완료")
except Exception as e:
    log("저장 실패:", e)
