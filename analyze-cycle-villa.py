"""
🏘️ 빌라 사이클 분석 (2026-11-10, 수정 요청: 빌라 시세 사이클을 빌라 기준으로 변경)
기존 analyze-cycle.py는 아파트(house_trades)로 가격지수·상승/하락기를 만들어, 빌라 상세에서 📈 사이클을 눌러도 아파트 흐름이 나왔음.
여기서는 같은 방법(지수 → 3개월 평균 → 5%(전국·시도 3%) 되돌림으로 고점/저점 → 현재 국면 → 6·12개월 뒤 예측 검증)을 villa_trades(연립·다세대)로 한다.
빌라는 같은 건물 반복 거래가 드물어 아파트처럼 '단지×평형' 고정효과를 쓸 수 없으므로, 비교 단위를 '같은 법정동 × 면적대(10㎡) × 연식대(5년) × 승강기 없는 저층 구분 없이'로 묶는다
(건물 구성이 달라도 같은 조건끼리만 비교하는 2중 고정효과 지수). 지하(0층 이하)는 뺌.
결과는 leader_follower_cache 'cyclev|__summary__'(전국·시도 요약) 와 'cyclev|<시군구>'(지수·국면·사이클·6/12개월 예측)로 저장 - 후발주자(단지 대장 기반)는 빌라에 해당 없음.
"""
import os, json, math, importlib.util
from datetime import datetime, timezone
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_s); _s.loader.exec_module(cyc)
avm = cyc.avm
START_DATE = 20170901


def main():
    now = datetime.now(timezone.utc).isoformat()
    print("🏘️ 빌라 사이클 분석 시작", now)
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{START_DATE}")
    df = raw[raw["dealing_type"].fillna("") != "직거래"].copy()
    for c in ("price", "size", "floor", "deal_date", "build_year"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong"])
    df = df[(df["price"] > 0) & (df["size"] >= 15) & (df["size"] <= 150) & (df["floor"].fillna(2) >= 1)]
    df["logp"] = np.log(df["price"] / df["size"] * 3.305785)
    df["ym"] = cyc.ym_of(df["deal_date"]); df["q"] = df["ym"] // 3
    df["dongk"] = df["dong"].astype(str).str.split().str[-1]
    age = (df["deal_date"] // 10000 - df["build_year"]).clip(0, 60)
    df["ageb"] = np.where(age.isna(), -1, (age // 5)).astype(int)
    df["unit"] = df["region"].astype(str) + "|" + df["dongk"] + "|" + (df["size"] / 10.0).round().astype(int).astype(str) + "|" + df["ageb"].astype(str)
    df["sido"] = df["region"].astype(str).str.split().str[0]
    df = df.reset_index(drop=True)
    print(f"  빌라 거래 {len(df):,}건 ({cyc.ym_label(int(df['ym'].min()))} ~ {cyc.ym_label(int(df['ym'].max()))})")
    last_full_ym = int(df["ym"].max()) - 1
    df_idx = df[df["ym"] <= last_full_ym]

    def analyze_level(sub, threshold):
        s, n = cyc.fe_index(sub, "unit", "ym")
        s = s[n.reindex(s.index).fillna(0) >= cyc.MIN_UNITS_PER_MONTH]
        if len(s) < 24: return None, None, None
        sm = cyc.smooth_series(s, "center"); pts = cyc.zigzag(sm, threshold)
        return cyc.smooth_series(s, "trail"), pts, sub.groupby("ym").size()

    pack = lambda s, pts, vol: {"index": cyc.series_payload(s), "turningPoints": [{**p, "ym": cyc.ym_label(p["ym"]), "level": round(math.exp(p["level"]) * 100, 2)} for p in pts],
                                "phase": cyc.describe_phase(s, pts, vol), "cycle": cyc.cycle_stats(pts)}
    summary = {"generatedAt": now, "dataFrom": cyc.ym_label(int(df["ym"].min())), "dataTo": cyc.ym_label(last_full_ym), "segment": "villa"}
    # 전국(수도권만 있어도 전체 합산)·시도
    s, pts, vol = analyze_level(df_idx, cyc.ZIGZAG_WIDE)
    summary["national"] = pack(s, pts, vol) if s is not None else None
    print("  전체:", summary["national"] and summary["national"]["phase"])
    summary["sido"] = {}
    for sido, sub in df_idx.groupby("sido"):
        s, pts, vol = analyze_level(sub, cyc.ZIGZAG_WIDE)
        if s is not None: summary["sido"][sido] = pack(s, pts, vol)
    # 시군구
    feat_rows, region_rows = [], []
    for i, region in enumerate(sorted(df["region"].dropna().unique())):
        dfr = df_idx[df_idx["region"] == region]
        s, n = cyc.fe_index(dfr, "unit", "ym")
        s = s[n.reindex(s.index).fillna(0) >= cyc.MIN_UNITS_PER_MONTH]
        if len(s) < 36: continue
        sm = cyc.smooth_series(s, "center"); trail = cyc.smooth_series(s, "trail"); pts = cyc.zigzag(sm, cyc.ZIGZAG_REGION)
        vol = dfr.groupby("ym").size()
        f = cyc.build_region_features(trail, vol); f["ym"] = f.index; f["region"] = region; feat_rows.append(f)
        rr = {"region": region, "segment": "villa", **pack(trail, pts, vol), "followers": []}
        region_rows.append(rr)
    print(f"  시군구 {len(region_rows)}곳")
    feats = pd.concat(feat_rows, ignore_index=True)
    summary["forecastValidation"] = cyc.validate_forecast(feats)
    print("  사이클 위치→미래 검증:", json.dumps(summary["forecastValidation"], ensure_ascii=False)[:1200])
    summary["currentForecast"] = {}
    for h in cyc.FWD_HORIZONS:
        v = summary["forecastValidation"].get(f"{h}m")
        if not v: continue
        coefs = v["coefs"]; latest = feats.sort_values("ym").groupby("region").tail(1)
        cols = ["mom3", "mom6", "mom12", "dd36", "up36", "vol_ratio"]; lat = latest.dropna(subset=cols)
        pred = coefs["const"] + sum(coefs[c] * lat[c] for c in cols)
        summary["currentForecast"][f"{h}m"] = dict(zip(lat["region"], [round((math.exp(float(p)) - 1) * 100, 1) for p in pred]))
    rows = []
    for rr in region_rows:
        rr["forecast"] = {h: summary["currentForecast"].get(h, {}).get(rr["region"]) for h in ("6m", "12m")}
        rows.append({"id": f"cyclev|{rr['region']}", "payload": cyc.clean_json(rr), "fetched_at": now})
    rows.append({"id": "cyclev|__summary__", "payload": cyc.clean_json(summary), "fetched_at": now})
    cyc.upsert_rows(rows)
    print(f"✅ 저장 완료: 빌라 시군구 {len(region_rows)}곳 + 요약")


if __name__ == "__main__":
    main()
