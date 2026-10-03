"""
════════════════════════════════════════════════════════════
부동산 사이클 + 후발주자(과거 이력) 분석 - 2026-10
════════════════════════════════════════════════════════════
사용자 요청(2026-10-03): "2017년부터 올린 과거 데이터로 상승기·하락기를 파악해서 후발주자를 찾는 게 큰 목표.
상승·하락 주기는 약 5년으로 보는데, 지금이 어디쯤인지 예측하려는 용도."

하는 일(GitHub Actions에서 주 1회, analyze-cycle.yml):
 1) 가격지수: house_trades(2017-09~) 전체로 전국·시도·시군구 월별 아파트 가격지수를 만듦.
    같은 단지·같은 평형대(5㎡ 단위)를 하나의 "유닛"으로 보고, 유닛 고정효과 + 월 고정효과를 번갈아 추정
    (two-way fixed effects) - 그 달에 어떤 단지가 많이 거래됐는지(구성 변화)에 덜 흔들리는 지수.
 2) 사이클: 3개월 평균한 지수에서 5%(전국·시도 3%) 이상 되돌림을 고점/저점으로 확정하는 지그재그 방식으로
    상승기·하락기 구간과 전환점을 찾고, "지금"이 어느 구간 몇 개월째인지·고점/저점 대비 얼마인지 계산.
 3) 사이클 위치 → 미래 검증: 과거 각 시점에서 그때까지의 자료(모멘텀·거래량·고점대비 하락폭 등)만으로
    6·12개월 뒤 지수 변화를 예측해 보고, 실제와 비교(앞 기간으로 학습, 뒤 기간으로 채점).
 4) 후발주자 이력: 앱이 정한 대장아파트(leader_follower_cache)를 기준으로, 과거 상승기·하락기마다 같은 동
    단지들이 대장 대비 얼마나(β), 몇 분기 늦게(lag) 따라 움직였는지 단지별로 측정.
    → 과거 시점마다 "대장은 올랐는데 아직 덜 따라온 정도(갭)"로 다음 4분기 초과상승(시군구 대비)을 예측해
      실제로 맞는지 채점하고, 맞는 정도(계수)만큼만 현재 갭에 반영해 "예상 따라잡기"를 냄.
결과는 leader_follower_cache 테이블에 id 'cycle|__summary__' 와 'cycle|<시군구>'로 저장(새 테이블 없음).
"""
import os
import sys
import json
import math
import importlib.util
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

_spec = importlib.util.spec_from_file_location("avm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "train-avm.py"))
avm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(avm)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
HEADERS = avm.HEADERS
START_DATE = 20170901
SIZE_BUCKET_M2 = 5.0
ZIGZAG_REGION = 0.05
ZIGZAG_WIDE = 0.03
MIN_UNITS_PER_MONTH = 5
FWD_HORIZONS = (6, 12)
TRAIN_END_YM = 2022 * 12 + 5      # 2022-06까지 시점으로 학습
TEST_START_YM = 2022 * 12 + 11    # 2022-12 이후 시점으로 채점(학습 목표기간과 겹치지 않게 여유)
MIN_COMPLEX_TRADES = 20
LF_CUTOFF_QUARTERS = None  # main에서 데이터 범위 보고 정함
GAP_HORIZON_Q = 4


def ym_of(deal_date):
    d = deal_date.astype(np.int64)
    return (d // 10000) * 12 + (d // 100 % 100) - 1


def ym_label(ym):
    return f"{ym // 12}-{ym % 12 + 1:02d}"


def q_label(q):
    return f"{q // 4}Q{q % 4 + 1}"


# ── 1) 가격지수 ──
def fe_index(df, unit_col, time_col, iters=12):
    """유닛 고정효과 + 시점 고정효과(가중 교대추정). 반환: 시점별 로그지수(Series, 첫 시점=0), 시점별 셀 수"""
    cell = df.groupby([unit_col, time_col], observed=True)["logp"].agg(["mean", "count"]).reset_index()
    if cell.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    u_codes, u_uni = pd.factorize(cell[unit_col])
    t_codes, t_uni = pd.factorize(cell[time_col])
    y = cell["mean"].to_numpy(float)
    w = cell["count"].to_numpy(float)
    u_eff = np.zeros(len(u_uni))
    t_eff = np.zeros(len(t_uni))
    for _ in range(iters):
        t_eff = np.bincount(t_codes, weights=w * (y - u_eff[u_codes]), minlength=len(t_uni)) / np.maximum(np.bincount(t_codes, weights=w, minlength=len(t_uni)), 1e-9)
        u_eff = np.bincount(u_codes, weights=w * (y - t_eff[t_codes]), minlength=len(u_uni)) / np.maximum(np.bincount(u_codes, weights=w, minlength=len(u_uni)), 1e-9)
    s = pd.Series(t_eff, index=t_uni).sort_index()
    n_cells = pd.Series(np.bincount(t_codes, minlength=len(t_uni)), index=t_uni).sort_index()
    s = s - s.iloc[0]
    return s, n_cells


def smooth_series(s, months):
    full = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1)).interpolate(limit_direction="both")
    return full.rolling(3, center=True, min_periods=1).mean() if months == "center" else full.rolling(3, min_periods=1).mean()


# ── 2) 사이클(지그재그) ──
def zigzag(log_s, threshold):
    """log 지수(Series, 연속 월)에서 threshold(로그) 이상 되돌림으로 확정된 고점/저점 목록(시간순)"""
    idx = list(log_s.index)
    vals = log_s.to_numpy()
    pts = []
    trend = None
    hi_i = lo_i = 0
    for i in range(1, len(vals)):
        if trend in (None, "up"):
            if vals[i] > vals[hi_i]:
                hi_i = i
            if vals[hi_i] - vals[i] >= threshold:
                pts.append({"ym": int(idx[hi_i]), "type": "peak", "level": float(vals[hi_i])})
                trend = "down"
                lo_i = i
                continue
        if trend in (None, "down"):
            if vals[i] < vals[lo_i]:
                lo_i = i
            if vals[i] - vals[lo_i] >= threshold:
                pts.append({"ym": int(idx[lo_i]), "type": "trough", "level": float(vals[lo_i])})
                trend = "up"
                hi_i = i
    return pts


def describe_phase(log_s, pts, vol):
    last_ym = int(log_s.index.max())
    cur = float(log_s.iloc[-1])
    def chg(m):
        if last_ym - m in log_s.index:
            return round((math.exp(cur - float(log_s.loc[last_ym - m])) - 1) * 100, 1)
        return None
    phase = {"asOf": ym_label(last_ym), "mom3": chg(3), "mom6": chg(6), "mom12": chg(12)}
    last_peak = next((p for p in reversed(pts) if p["type"] == "peak"), None)
    last_trough = next((p for p in reversed(pts) if p["type"] == "trough"), None)
    if pts:
        lp = pts[-1]
        phase["phase"] = "상승기" if lp["type"] == "trough" else "하락기"
        phase["since"] = ym_label(lp["ym"])
        phase["monthsInPhase"] = last_ym - lp["ym"]
    else:
        phase["phase"] = "상승기" if (phase["mom12"] or 0) >= 0 else "하락기"
        phase["since"] = None
        phase["monthsInPhase"] = None
    if last_peak:
        phase["fromLastPeakPct"] = round((math.exp(cur - last_peak["level"]) - 1) * 100, 1)
        phase["lastPeak"] = ym_label(last_peak["ym"])
    if last_trough:
        phase["fromLastTroughPct"] = round((math.exp(cur - last_trough["level"]) - 1) * 100, 1)
        phase["lastTrough"] = ym_label(last_trough["ym"])
    if vol is not None and len(vol) >= 24:
        v = vol.reindex(range(int(vol.index.min()), last_ym + 1)).fillna(0)
        recent = float(v.iloc[-6:].mean()); prior = float(v.iloc[-18:-6].mean()); longrun = float(v.mean())
        phase["volume6mVsPrior12mPct"] = round((recent / prior - 1) * 100, 1) if prior > 0 else None
        phase["volume6mVsLongRunPct"] = round((recent / longrun - 1) * 100, 1) if longrun > 0 else None
    return phase


def cycle_stats(pts):
    troughs = [p["ym"] for p in pts if p["type"] == "trough"]
    peaks = [p["ym"] for p in pts if p["type"] == "peak"]
    t2t = [b - a for a, b in zip(troughs, troughs[1:])]
    p2p = [b - a for a, b in zip(peaks, peaks[1:])]
    up = []
    down = []
    for a, b in zip(pts, pts[1:]):
        (up if a["type"] == "trough" else down).append(b["ym"] - a["ym"])
    return {"troughToTroughMonths": t2t, "peakToPeakMonths": p2p, "upMonths": up, "downMonths": down}


# ── 3) 사이클 위치 → 미래 검증 ──
def build_region_features(log_s, vol):
    s = log_s
    f = pd.DataFrame(index=s.index)
    f["mom3"] = s - s.shift(3)
    f["mom6"] = s - s.shift(6)
    f["mom12"] = s - s.shift(12)
    f["dd36"] = s - s.rolling(36, min_periods=12).max()
    f["up36"] = s - s.rolling(36, min_periods=12).min()
    v = vol.reindex(s.index).fillna(0)
    f["vol_ratio"] = np.log((v.rolling(6).mean() + 1) / (v.shift(6).rolling(12).mean() + 1))
    for h in FWD_HORIZONS:
        f[f"fwd{h}"] = s.shift(-h) - s
    return f


def validate_forecast(feats):
    cols = ["mom3", "mom6", "mom12", "dd36", "up36", "vol_ratio"]
    out = {}
    for h in FWD_HORIZONS:
        d = feats.dropna(subset=cols + [f"fwd{h}"])
        tr = d[d["ym"] <= TRAIN_END_YM]
        te = d[d["ym"] >= TEST_START_YM]
        if len(tr) < 200 or len(te) < 100:
            continue
        X = np.column_stack([np.ones(len(tr))] + [tr[c].to_numpy() for c in cols])
        beta, *_ = np.linalg.lstsq(X, tr[f"fwd{h}"].to_numpy(), rcond=None)
        Xt = np.column_stack([np.ones(len(te))] + [te[c].to_numpy() for c in cols])
        pred = Xt @ beta
        y = te[f"fwd{h}"].to_numpy()
        mom_pred = te["mom6"].to_numpy() * (h / 6.0) * 0.5
        sig = np.abs(y) > 0.01

        def score(p):
            return {
                "maePct": round(float(np.mean(np.abs(y - p))) * 100, 2),
                "directionHitPct": round(float(np.mean(np.sign(p[sig]) == np.sign(y[sig]))) * 100, 1) if sig.any() else None,
            }
        out[f"{h}m"] = {
            "nTrain": int(len(tr)), "nTest": int(len(te)),
            "naiveZero": score(np.zeros(len(y))),
            "momentumHalf": score(mom_pred),
            "cycleModel": score(pred),
            "coefs": {k: round(float(b), 4) for k, b in zip(["const"] + cols, beta)},
        }
    return out


# ── 4) 후발주자 이력 ──
def complex_quarterly(df):
    """단지별 분기 지수(로그, 평형대 차이 제거) - 유닛(평형대) 평균을 뺀 잔차의 분기 평균"""
    unit_mean = df.groupby("unit", observed=True)["logp"].transform("mean")
    d = df.assign(res=df["logp"] - unit_mean)
    g = d.groupby(["ckey", "q"], observed=True)["res"].agg(["mean", "count"]).reset_index()
    return g


def ols_slope(x, y):
    if len(x) < 4 or np.var(x) <= 1e-9:
        return None
    return float(np.cov(x, y, bias=True)[0, 1] / np.var(x))


def follower_history(dfr, region_q, leaders_by_dong, cutoffs):
    """한 시군구의 후발주자 이력 + 시점별 백테스트 표본"""
    cq = complex_quarterly(dfr)
    counts = dfr.groupby("ckey", observed=True).size()
    good = set(counts[counts >= MIN_COMPLEX_TRADES].index)
    series = {}
    for ck, sub in cq[cq["ckey"].isin(good)].groupby("ckey", observed=True):
        s = pd.Series(sub["mean"].to_numpy(), index=sub["q"].to_numpy()).sort_index()
        series[ck] = s
    ck_dong = dfr.drop_duplicates("ckey").set_index("ckey")["dongk"].to_dict()
    ck_name = dfr.drop_duplicates("ckey").set_index("ckey")["danji"].to_dict()
    results = []
    samples = []
    for dongk, leader_name in leaders_by_dong.items():
        lk = next((ck for ck in series if ck_dong.get(ck) == dongk and avm.normalize_complex_name(ck_name.get(ck)) == avm.normalize_complex_name(leader_name)), None)
        if lk is None:
            continue
        L = series[lk]
        for ck, F in series.items():
            if ck == lk or ck_dong.get(ck) != dongk:
                continue
            both = pd.concat([L, F], axis=1, keys=["L", "F"]).dropna()
            if len(both) < 8:
                continue
            full_q = range(int(both.index.min()), int(both.index.max()) + 1)
            bi = both.reindex(full_q).interpolate(limit=2).dropna()
            dL, dF = bi["L"].diff(), bi["F"].diff()
            # lag: 대장 분기변화 → 후발 분기변화 상관이 가장 큰 지연(0~4분기)
            best_lag, best_corr = 0, None
            for lag in range(0, 5):
                x, y = dL.iloc[1:len(dL) - lag].to_numpy(), dF.iloc[1 + lag:].to_numpy()
                if len(x) >= 8 and np.std(x) > 0 and np.std(y) > 0:
                    c = float(np.corrcoef(x, y)[0, 1])
                    if best_corr is None or c > best_corr:
                        best_lag, best_corr = lag, c
            # β: 4분기 변화끼리의 기울기(대장 4분기 변화 대비 후발 4분기 변화)
            L4, F4 = (bi["L"] - bi["L"].shift(4)).dropna(), (bi["F"] - bi["F"].shift(4)).dropna()
            ix = L4.index.intersection(F4.index)
            beta = ols_slope(L4.loc[ix].to_numpy(), F4.loc[ix].to_numpy())
            up_mask = L4.loc[ix] > 0.02
            dn_mask = L4.loc[ix] < -0.02
            beta_up = ols_slope(L4.loc[ix][up_mask].to_numpy(), F4.loc[ix][up_mask].to_numpy()) if up_mask.sum() >= 4 else None
            beta_dn = ols_slope(L4.loc[ix][dn_mask].to_numpy(), F4.loc[ix][dn_mask].to_numpy()) if dn_mask.sum() >= 4 else None
            last_q = int(bi.index.max())
            gap_now = None
            # 백테스트와 같은 규칙: β를 0~1.5로 자름(음수·0 근처 β로 갭이 부풀던 문제 - 2026-10 화면 확인)
            beta_c = None if beta is None else max(0.0, min(1.5, beta))
            if beta_c is not None and last_q - 4 in bi.index:
                gap_now = beta_c * (bi["L"].loc[last_q] - bi["L"].loc[last_q - 4]) - (bi["F"].loc[last_q] - bi["F"].loc[last_q - 4])
            # "실제로 대장을 따라 움직인 단지"만 후발주자로 봄: β 0.3~1.5, 분기 변화 상관 0.2 이상
            is_follower = beta is not None and 0.3 <= beta <= 1.5 and best_corr is not None and best_corr >= 0.2
            results.append({
                "dong": dongk, "danji": ck_name.get(ck), "leader": leader_name,
                "beta": None if beta is None else round(beta, 3), "betaUp": None if beta_up is None else round(beta_up, 3),
                "betaDown": None if beta_dn is None else round(beta_dn, 3),
                "lagQ": best_lag, "corr": None if best_corr is None else round(best_corr, 3),
                "nQuarters": int(len(bi)), "lastQ": q_label(last_q),
                "gapNowPct": None if gap_now is None else round(gap_now * 100, 1),
                "isFollower": bool(is_follower),
            })
            # 백테스트 표본: 컷오프 시점까지 자료로 β·갭 계산 → 다음 4분기 "시군구 대비 초과변화"
            for cq_ in cutoffs:
                hist = bi[bi.index <= cq_]
                if len(hist) < 8 or cq_ - 4 not in hist.index or cq_ + GAP_HORIZON_Q not in bi.index or cq_ not in hist.index:
                    continue
                hL4 = (hist["L"] - hist["L"].shift(4)).dropna(); hF4 = (hist["F"] - hist["F"].shift(4)).dropna()
                hix = hL4.index.intersection(hF4.index)
                hb = ols_slope(hL4.loc[hix].to_numpy(), hF4.loc[hix].to_numpy())
                if hb is None:
                    continue
                hb = max(0.0, min(1.5, hb))
                gap = hb * (hist["L"].loc[cq_] - hist["L"].loc[cq_ - 4]) - (hist["F"].loc[cq_] - hist["F"].loc[cq_ - 4])
                fwdF = bi["F"].loc[cq_ + GAP_HORIZON_Q] - bi["F"].loc[cq_]
                if cq_ in region_q.index and cq_ + GAP_HORIZON_Q in region_q.index:
                    excess = fwdF - (region_q.loc[cq_ + GAP_HORIZON_Q] - region_q.loc[cq_])
                    hcorr = None
                    hdL, hdF = hist["L"].diff().dropna(), hist["F"].diff().dropna()
                    hix2 = hdL.index.intersection(hdF.index)
                    if len(hix2) >= 8 and np.std(hdL.loc[hix2]) > 0 and np.std(hdF.loc[hix2]) > 0:
                        hcorr = float(np.corrcoef(hdL.loc[hix2], hdF.loc[hix2])[0, 1])
                    raw_hb = ols_slope(hL4.loc[hix].to_numpy(), hF4.loc[hix].to_numpy())
                    fol_flag = 1.0 if (raw_hb is not None and 0.3 <= raw_hb <= 1.5 and hcorr is not None and hcorr >= 0.2) else 0.0
                    samples.append((cq_, float(gap), float(excess), float(bi["L"].loc[cq_] - bi["L"].loc[cq_ - 4]), fol_flag))
    return results, samples


def validate_followers(samples):
    if len(samples) < 200:
        return None, None
    arr = np.array(samples, dtype=float)
    gap, ex = arr[:, 1], arr[:, 2]
    k = ols_slope(gap, ex)
    corr = float(np.corrcoef(gap, ex)[0, 1])
    big = gap > 0.03
    neg = gap < -0.03
    res = {
        "n": int(len(arr)),
        "corr": round(corr, 3),
        "catchupCoef": None if k is None else round(k, 3),
        "gapPositiveHitPct": round(float(np.mean(ex[big] > 0)) * 100, 1) if big.any() else None,
        "gapPositiveN": int(big.sum()),
        "gapPositiveAvgExcessPct": round(float(np.mean(ex[big])) * 100, 2) if big.any() else None,
        "gapNegativeAvgExcessPct": round(float(np.mean(ex[neg])) * 100, 2) if neg.any() else None,
        "allAvgExcessPct": round(float(np.mean(ex)) * 100, 2),
        "byCutoff": {},
    }
    for c in sorted(set(arr[:, 0].astype(int))):
        m = arr[:, 0].astype(int) == c
        g, e = gap[m], ex[m]
        if m.sum() >= 30:
            res["byCutoff"][q_label(c)] = {"n": int(m.sum()), "corr": round(float(np.corrcoef(g, e)[0, 1]), 3) if np.std(g) > 0 else None,
                                           "gapPositiveHitPct": round(float(np.mean(e[g > 0.03] > 0)) * 100, 1) if (g > 0.03).any() else None}
    return res, (k if k is not None else 0.0)


def fetch_leaders():
    """leader_follower_cache의 아파트 순위 결과에서 시군구별 {dong: 대장단지}"""
    url = f"{SUPABASE_URL}/rest/v1/leader_follower_cache?select=id,payload&id=like.*%7Capt"
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    out = {}
    for row in r.json():
        region = row["id"].rsplit("|", 1)[0]
        p = row.get("payload") or {}
        d = {}
        for l in p.get("leaders") or []:
            if l.get("dong") and l.get("danji"):
                d[str(l["dong"]).split()[-1]] = l["danji"]
        if d:
            out[region] = d
    print(f"  대장아파트 목록: {len(out)}개 시군구")
    return out


def upsert_rows(rows):
    url = f"{SUPABASE_URL}/rest/v1/leader_follower_cache?on_conflict=id"
    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    for i in range(0, len(rows), 20):
        r = requests.post(url, headers=headers, data=json.dumps(rows[i:i + 20], ensure_ascii=False, allow_nan=False), timeout=120)
        if r.status_code >= 300:
            print(f"  ERROR 저장 실패: {r.status_code} {r.text[:300]}", file=sys.stderr)
            r.raise_for_status()


def clean_json(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_json(v) for v in o]
    if isinstance(o, (np.floating,)):
        return clean_json(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


def series_payload(log_s):
    return [[ym_label(int(k)), round(math.exp(float(v)) * 100, 2)] for k, v in log_s.items()]


def main():
    now = datetime.now(timezone.utc).isoformat()
    print("🏠 부동산 사이클·후발주자 분석 시작", now)
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type",
                             extra_filter=f"&deal_date=gte.{START_DATE}")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "floor", "deal_date"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"])
    df = df[(df["price"] > 0) & (df["size"] > 10) & (df["floor"].fillna(5) >= 2)]
    df["logp"] = np.log(df["price"] / df["size"] * 3.305785)
    df["ym"] = ym_of(df["deal_date"])
    df["q"] = df["ym"] // 3
    df["dongk"] = df["dong"].astype(str).str.split().str[-1]
    df["ckey"] = df["region"].astype(str) + "|" + df["dongk"] + "|" + df["danji"].astype(str)
    df["unit"] = df["ckey"] + "|" + (df["size"] / SIZE_BUCKET_M2).round().astype(int).astype(str)
    df["sido"] = df["region"].astype(str).str.split().str[0]
    df = df.reset_index(drop=True)
    print(f"  분석 대상 {len(df)}건 ({ym_label(int(df['ym'].min()))} ~ {ym_label(int(df['ym'].max()))})")
    last_full_ym = int(df["ym"].max()) - 1  # 마지막 달은 신고 덜 들어옴 - 그 전 달까지만 지수에 씀
    df_idx = df[df["ym"] <= last_full_ym]

    summary = {"generatedAt": now, "dataFrom": ym_label(int(df["ym"].min())), "dataTo": ym_label(last_full_ym)}

    # 전국·시도
    def analyze_level(sub, threshold):
        s, n = fe_index(sub, "unit", "ym")
        s = s[n.reindex(s.index).fillna(0) >= MIN_UNITS_PER_MONTH]
        if len(s) < 24:
            return None, None, None
        sm = smooth_series(s, "center")
        pts = zigzag(sm, threshold)
        vol = sub.groupby("ym").size()
        trail = smooth_series(s, "trail")
        return trail, pts, vol

    nat_s, nat_pts, nat_vol = analyze_level(df_idx, ZIGZAG_WIDE)
    summary["national"] = {"index": series_payload(nat_s), "turningPoints": [{**p, "ym": ym_label(p["ym"]), "level": round(math.exp(p["level"]) * 100, 2)} for p in nat_pts],
                           "phase": describe_phase(nat_s, nat_pts, nat_vol), "cycle": cycle_stats(nat_pts)}
    print("  전국:", summary["national"]["phase"])
    summary["sido"] = {}
    for sido, sub in df_idx.groupby("sido"):
        s, pts, vol = analyze_level(sub, ZIGZAG_WIDE)
        if s is None:
            continue
        summary["sido"][sido] = {"index": series_payload(s), "turningPoints": [{**p, "ym": ym_label(p["ym"]), "level": round(math.exp(p["level"]) * 100, 2)} for p in pts],
                                 "phase": describe_phase(s, pts, vol), "cycle": cycle_stats(pts)}

    # 시군구 + 검증 표본
    leaders = fetch_leaders()
    max_q = int(df["q"].max())
    cutoffs = [q for q in range(int(df["q"].min()) + 12, max_q - GAP_HORIZON_Q) if q % 2 == 0]
    feat_rows = []
    region_rows = []
    all_samples = []
    regions = sorted(df["region"].dropna().unique())
    for i, region in enumerate(regions):
        dfr = df[df["region"] == region]
        dfr_idx = dfr[dfr["ym"] <= last_full_ym]
        s, n = fe_index(dfr_idx, "unit", "ym")
        s = s[n.reindex(s.index).fillna(0) >= MIN_UNITS_PER_MONTH]
        if len(s) < 36:
            continue
        sm = smooth_series(s, "center")
        trail = smooth_series(s, "trail")
        pts = zigzag(sm, ZIGZAG_REGION)
        vol = dfr_idx.groupby("ym").size()
        f = build_region_features(trail, vol)
        f["ym"] = f.index
        f["region"] = region
        feat_rows.append(f)
        region_q = trail.groupby(trail.index // 3).mean()
        fol, samples = follower_history(dfr, region_q, leaders.get(region, {}), cutoffs)
        all_samples.extend(samples)
        region_rows.append({"region": region, "index": series_payload(trail),
                            "turningPoints": [{**p, "ym": ym_label(p["ym"]), "level": round(math.exp(p["level"]) * 100, 2)} for p in pts],
                            "phase": describe_phase(trail, pts, vol), "cycle": cycle_stats(pts), "followers": fol})
        if (i + 1) % 25 == 0:
            print(f"  시군구 {i + 1}/{len(regions)} 처리")

    feats = pd.concat(feat_rows, ignore_index=True)
    summary["forecastValidation"] = validate_forecast(feats)
    print("  사이클 위치→미래 검증:", json.dumps(summary["forecastValidation"], ensure_ascii=False)[:1500])
    fv, k = validate_followers(all_samples)
    summary["followerValidation"] = fv
    fol_only = [x for x in all_samples if len(x) > 4 and x[4] == 1.0]
    fv2, k2 = validate_followers(fol_only)
    summary["followerValidationStrict"] = fv2
    print("  후발주자(β 0.3~1.5·상관 0.2↑)만 검증:", json.dumps(fv2, ensure_ascii=False)[:800])
    if fv2 and fv2.get("corr", 0) > 0.05 and k2:
        k = k2  # 화면엔 실제 후발주자만 쓰므로 그 집합에서 추정한 계수를 씀
    print("  후발주자 이력 검증:", json.dumps(fv, ensure_ascii=False)[:1500])
    k_use = max(0.0, min(1.0, k or 0.0)) if fv and fv.get("corr", 0) > 0.05 else 0.0
    summary["followerCatchupCoefUsed"] = k_use
    # 현재 시점 국가 단위 사이클 모델 예측(6·12개월)
    summary["currentForecast"] = {}
    for h in FWD_HORIZONS:
        v = summary["forecastValidation"].get(f"{h}m")
        if not v:
            continue
        coefs = v["coefs"]
        latest = feats.sort_values("ym").groupby("region").tail(1)
        cols = ["mom3", "mom6", "mom12", "dd36", "up36", "vol_ratio"]
        lat = latest.dropna(subset=cols)
        pred = coefs["const"] + sum(coefs[c] * lat[c] for c in cols)
        summary["currentForecast"][f"{h}m"] = dict(zip(lat["region"], [round((math.exp(float(p)) - 1) * 100, 1) for p in pred]))

    rows = []
    for rr in region_rows:
        for fo in rr["followers"]:
            if fo.get("gapNowPct") is not None and fo.get("isFollower"):
                fo["expectedCatchupPct"] = round(fo["gapNowPct"] * k_use, 1)
        rr["forecast"] = {h: summary["currentForecast"].get(h, {}).get(rr["region"]) for h in ("6m", "12m")}
        rows.append({"id": f"cycle|{rr['region']}", "payload": clean_json(rr), "fetched_at": now})
    rows.append({"id": "cycle|__summary__", "payload": clean_json(summary), "fetched_at": now})
    upsert_rows(rows)
    print(f"✅ 저장 완료: 시군구 {len(region_rows)}곳 + 요약")

    md = ["## 부동산 사이클·후발주자 분석", "",
          f"- 자료: {summary['dataFrom']} ~ {summary['dataTo']}, 거래 {len(df):,}건",
          f"- 전국 국면: {summary['national']['phase']}",
          f"- 전국 전환점: {summary['national']['turningPoints']}",
          f"- 사이클 위치→미래 검증: {json.dumps(summary['forecastValidation'], ensure_ascii=False)}",
          f"- 후발주자 이력 검증: {json.dumps(fv, ensure_ascii=False)}",
          f"- 반영 계수: {k_use}"]
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
