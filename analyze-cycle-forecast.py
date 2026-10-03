"""
════════════════════════════════════════════════════════════
사이클 → 6개월 뒤 가격변화 예측 검증 (수도권/지방 분리) - 2026-10
════════════════════════════════════════════════════════════
사용자 기준(2026-10-03): "수도권과 지방 아파트는 같은 기준으로 보기 어렵다. 수도권은 전세가율과 대장그룹 선행,
지방은 전세가율과 미분양이 중요해 보이고, 거래량은 모두 기본."
analyze-cycle.py의 1차 시도(가격 모멘텀만으로 전국 한 모델)는 '변화 없음' 예측보다 못했음 → 이 스크립트는
  - 수도권(서울·인천·경기)과 지방을 따로 학습/검증
  - 지표: 공통(가격 모멘텀·거래량) + 전세가율(전세/매매 비율과 그 변화, 전세가 흐름)
          + 수도권: 대장그룹 선행(대장 단지 지수 변화 − 나머지 단지 지수 변화)
          + 지방: 미분양(전년 대비 증감, 5년 평균 대비 수준)
  - 걷기식(walk-forward) 검증: 2021~2025년 각 해를, 그 해 시작 전까지 결과가 확정된 자료로만 학습해 예측
  - 지표 묶음을 하나씩 더해 보며(기본 → +전세 → +지역지표 → 전체) 실제로 나아지는지 비교
결과는 leader_follower_cache 'cycle|__forecast__'에 저장하고 요약을 출력함.
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

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
avm = cyc.avm

SITE_URL = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
H = 6
METRO = ("서울", "인천", "경기")
TEST_YEARS = [2021, 2022, 2023, 2024, 2025]
RIDGE_LAMBDA = 3.0


def prep_units(df, value_col):
    df = df.copy()
    df["logp"] = np.log(df[value_col] / df["size"] * 3.305785)
    df["ym"] = cyc.ym_of(df["deal_date"])
    df["q"] = df["ym"] // 3
    df["dongk"] = df["dong"].astype(str).str.split().str[-1]
    df["ckey"] = df["region"].astype(str) + "|" + df["dongk"] + "|" + df["danji"].astype(str)
    df["unit"] = df["ckey"] + "|" + (df["size"] / cyc.SIZE_BUCKET_M2).round().astype(int).astype(str)
    return df


def region_index(sub):
    s, n = cyc.fe_index(sub, "unit", "ym")
    s = s[n.reindex(s.index).fillna(0) >= cyc.MIN_UNITS_PER_MONTH]
    if len(s) < 24:
        return None
    return cyc.smooth_series(s, "trail")


def jeonse_ratio_by_q(sale_r, rent_r):
    """시군구 분기별 전세가율 - 같은 유닛(단지·평형)의 같은 분기 매매·전세 평단가 중앙값 비율의 중앙값"""
    a = sale_r.groupby(["unit", "q"], observed=True)["logp"].median()
    b = rent_r.groupby(["unit", "q"], observed=True)["logp"].median()
    j = pd.concat([a, b], axis=1, keys=["s", "j"]).dropna()
    if j.empty:
        return pd.Series(dtype=float)
    r = np.exp(j["j"] - j["s"])
    out = r.groupby(level="q").median()
    cnt = r.groupby(level="q").size()
    return out[cnt >= 5]


def fetch_unsold(region):
    try:
        r = requests.get(f"{SITE_URL}/api/data-coverage", params={"mode": "unsoldHistory", "region": region}, timeout=60)
        if r.status_code != 200:
            return None
        ser = r.json().get("series") or []
        if len(ser) < 24:
            return None
        s = pd.Series({(int(p[:4]) * 12 + int(p[4:6]) - 1): float(v) for p, v in ser}).sort_index()
        return s
    except Exception:
        return None


def build_features(region, sale_r, rent_r, leaders, is_metro):
    I = region_index(sale_r)
    if I is None:
        return None
    f = pd.DataFrame(index=I.index)
    f["mom3"] = I - I.shift(3)
    f["mom6"] = I - I.shift(6)
    f["mom12"] = I - I.shift(12)
    vol = sale_r.groupby("ym").size().reindex(I.index).fillna(0)
    f["vol_ratio"] = np.log((vol.rolling(6).mean() + 1) / (vol.shift(6).rolling(12).mean() + 1))
    f["vol_long"] = np.log((vol.rolling(6).mean() + 1) / (vol.expanding(24).mean() + 1))
    # 전세
    if rent_r is not None and len(rent_r) > 500:
        J = region_index(rent_r)
        if J is not None:
            f["j_mom6"] = (J - J.shift(6)).reindex(f.index)
        jr = jeonse_ratio_by_q(sale_r, rent_r)
        if len(jr) >= 8:
            jr_m = pd.Series({ym: jr.get(ym // 3 - 1, np.nan) for ym in f.index})  # 직전 완료 분기 값(미래정보 차단)
            f["jr_level"] = jr_m
            f["jr_chg"] = jr_m - jr_m.shift(12)
    # 수도권: 대장그룹 선행
    if is_metro and leaders:
        lead_keys = {f"{region}|{d}|{n}" for d, n in leaders.items()}
        is_lead = sale_r["ckey"].isin(lead_keys)
        if is_lead.sum() > 300 and (~is_lead).sum() > 300:
            L = region_index(sale_r[is_lead]); R = region_index(sale_r[~is_lead])
            if L is not None and R is not None:
                lg = (L - L.shift(6)) - (R - R.shift(6))
                f["lead_gap6"] = lg.reindex(f.index)
                f["lead_gap3"] = ((L - L.shift(3)) - (R - R.shift(3))).reindex(f.index)
    # 지방: 미분양
    if not is_metro:
        U = fetch_unsold(region)
        if U is not None:
            U = U.reindex(range(int(U.index.min()), int(U.index.max()) + 1)).interpolate(limit=2)
            u = U.shift(1)  # 미분양 통계는 한 달 늦게 발표 - 그 시점에 알 수 있던 값만 씀
            f["uns_yoy"] = (np.log(u + 10) - np.log(u.shift(12) + 10)).reindex(f.index)
            f["uns_rel"] = (np.log(u + 10) - np.log(u.rolling(60, min_periods=24).mean() + 10)).reindex(f.index)
    f["fwd"] = I.shift(-H) - I
    f["ym"] = f.index
    f["region"] = region
    return f


FEATURE_SETS = {
    "기본(가격·거래량)": ["mom3", "mom6", "mom12", "vol_ratio", "vol_long"],
    "+전세가율": ["mom3", "mom6", "mom12", "vol_ratio", "vol_long", "jr_level", "jr_chg", "j_mom6"],
}
SEG_EXTRA = {"metro": ["lead_gap6", "lead_gap3"], "local": ["uns_yoy", "uns_rel"]}


def ridge_fit(X, y, lam):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    b = np.linalg.solve(A, Z.T @ (y - y.mean()))
    return mu, sd, b, y.mean()


def ridge_pred(model, X):
    mu, sd, b, c = model
    return ((X - mu) / sd) @ b + c


def scores(y, p):
    sig = np.abs(y) > 0.01
    big_dn_true = y < -0.02
    big_dn_pred = p < -0.02
    prec = float(np.mean(big_dn_true[big_dn_pred])) if big_dn_pred.any() else None
    rec = float(np.mean(big_dn_pred[big_dn_true])) if big_dn_true.any() else None
    return {
        "n": int(len(y)),
        "maePct": round(float(np.mean(np.abs(y - p))) * 100, 2),
        "directionHitPct": round(float(np.mean(np.sign(p[sig]) == np.sign(y[sig]))) * 100, 1) if sig.any() else None,
        "bigDropPrecisionPct": None if prec is None else round(prec * 100, 1),
        "bigDropRecallPct": None if rec is None else round(rec * 100, 1),
    }


def walk_forward(feats, cols):
    d = feats.dropna(subset=cols + ["fwd"])
    ys, ps, yrs = [], [], []
    for Y in TEST_YEARS:
        start = Y * 12
        tr = d[d["ym"] + H < start]
        te = d[(d["ym"] >= start) & (d["ym"] < start + 12)]
        if len(tr) < 150 or len(te) < 30:
            continue
        m = ridge_fit(tr[cols].to_numpy(float), tr["fwd"].to_numpy(float), RIDGE_LAMBDA)
        ys.append(te["fwd"].to_numpy(float)); ps.append(ridge_pred(m, te[cols].to_numpy(float))); yrs.append(np.full(len(te), Y))
    if not ys:
        return None, None
    y, p, yr = np.concatenate(ys), np.concatenate(ps), np.concatenate(yrs)
    res = scores(y, p)
    res["byYear"] = {int(Y): scores(y[yr == Y], p[yr == Y]) for Y in sorted(set(yr))}
    return res, (y, p)


def baselines(feats, cols):
    d = feats.dropna(subset=cols + ["fwd"])
    d = d[d["ym"] >= TEST_YEARS[0] * 12]
    d = d[d["ym"] < (TEST_YEARS[-1] + 1) * 12]
    y = d["fwd"].to_numpy(float)
    return {"변화없음": scores(y, np.zeros(len(y))), "최근6개월흐름×0.5": scores(y, d["mom6"].to_numpy(float) * 0.5)}


def main():
    now = datetime.now(timezone.utc).isoformat()
    print("🔮 사이클 예측 검증(수도권/지방 분리) 시작", now)
    sale = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type",
                              extra_filter=f"&deal_date=gte.{cyc.START_DATE}")
    sale = sale[sale["dealing_type"] != "직거래"] if "dealing_type" in sale.columns else sale
    for c in ("price", "size", "floor", "deal_date"):
        sale[c] = pd.to_numeric(sale[c], errors="coerce")
    sale = sale.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"])
    sale = sale[(sale["price"] > 0) & (sale["size"] > 10) & (sale["floor"].fillna(5) >= 2)]
    sale = prep_units(sale, "price")
    rent = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deposit,size,floor,deal_date",
                              extra_filter=f"&deal_date=gte.{cyc.START_DATE}&monthly_rent=eq.0")
    for c in ("deposit", "size", "floor", "deal_date"):
        rent[c] = pd.to_numeric(rent[c], errors="coerce")
    rent = rent.dropna(subset=["deposit", "size", "deal_date", "region", "dong", "danji"])
    rent = rent[(rent["deposit"] > 0) & (rent["size"] > 10) & (rent["floor"].fillna(5) >= 2)]
    rent = prep_units(rent, "deposit")
    print(f"  매매 {len(sale):,}건, 전세 {len(rent):,}건 (전세 {cyc.ym_label(int(rent['ym'].min()))}~)")
    last_full = int(sale["ym"].max()) - 1
    sale = sale[sale["ym"] <= last_full]
    rent = rent[rent["ym"] <= last_full]
    leaders = cyc.fetch_leaders()

    rows = {"metro": [], "local": []}
    rent_by_region = dict(tuple(rent.groupby("region")))
    regions = sorted(sale["region"].unique())
    for i, region in enumerate(regions):
        seg = "metro" if str(region).startswith(METRO) else "local"
        f = build_features(region, sale[sale["region"] == region], rent_by_region.get(region), leaders.get(region, {}), seg == "metro")
        if f is not None:
            rows[seg].append(f)
        if (i + 1) % 25 == 0:
            print(f"  지역 {i + 1}/{len(regions)}")

    out = {"generatedAt": now, "horizonMonths": H, "testYears": TEST_YEARS, "segments": {}}
    for seg, lst in rows.items():
        feats = pd.concat(lst, ignore_index=True)
        segname = "수도권" if seg == "metro" else "지방"
        res = {"regions": len(lst)}
        base_cols = FEATURE_SETS["기본(가격·거래량)"]
        res["baselines"] = baselines(feats, base_cols)
        sets = dict(FEATURE_SETS)
        sets["+지역지표(" + ("대장그룹 선행" if seg == "metro" else "미분양") + ")"] = base_cols + SEG_EXTRA[seg]
        sets["전체"] = FEATURE_SETS["+전세가율"] + SEG_EXTRA[seg]
        coverage = {c: round(float(feats[c].notna().mean()) * 100, 1) for c in set(sum(sets.values(), [])) if c in feats.columns}
        res["featureCoveragePct"] = coverage
        res["models"] = {}
        for name, cols in sets.items():
            cols = [c for c in cols if c in feats.columns]
            r, _ = walk_forward(feats, cols)
            res["models"][name] = r
            print(f"  [{segname}] {name}: {json.dumps({k: v for k, v in (r or {}).items() if k != 'byYear'}, ensure_ascii=False)}")
        # 같은 표본(전체 지표가 다 있는 행)에서 다시 비교 - 지표별 결측 차이로 표본이 달라지는 효과 제거
        full_cols = [c for c in sets["전체"] if c in feats.columns]
        common = feats.dropna(subset=full_cols + ["fwd"])
        res["sameSample"] = {"baselines": baselines(common, full_cols)}
        for name, cols in sets.items():
            cols = [c for c in cols if c in feats.columns]
            r, _ = walk_forward(common, cols)
            res["sameSample"][name] = None if r is None else {k: v for k, v in r.items() if k != "byYear"}
        print(f"  [{segname}] 같은표본 비교: {json.dumps(res['sameSample'], ensure_ascii=False)}")
        print(f"  [{segname}] 기준선: {json.dumps(res['baselines'], ensure_ascii=False)}")
        out["segments"][segname] = res

    cyc.upsert_rows([{"id": "cycle|__forecast__", "payload": cyc.clean_json(out), "fetched_at": now}])
    print("✅ 저장 완료")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 사이클 예측 검증(수도권/지방)\n\n```\n" + json.dumps(out["segments"], ensure_ascii=False, indent=1)[:60000] + "\n```\n")


if __name__ == "__main__":
    main()
