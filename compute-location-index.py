"""
📍 입지 지수 계산 (2026-11-09, 사용자: 입지가 가장 중요 - 좌표 기반으로 뽑고, 지도에 반경으로 상위 10곳을 표시. API 호출·비용이 늘지 않게)
(2026-11-14 변경: 순위 = 거래 활발도 = 이웃 격자 포함 최근 12개월 거래 건수. 평당가는 참고로만 저장)
입지 = 시장이 이미 가격으로 매긴 위치의 가치(면적·연식·층이 같다고 보정한 ㎡당 가격). 철저히 실거래 자료만 사용(평판·상급지 같은 주관 개념 없음).
계산(아파트·빌라 따로):
 ① 속성 보정: 같은 법정동·같은 분기 안에서 ㎡당 가격이 면적대·연식대·층 구분에 따라 얼마나 다른지를 자료에서 추정(덧셈 모델) → 모든 거래를 '기준 물건'(면적 60~85㎡·연식 11~20년·4~7층) 가격으로 환산
 ② 시점 보정: 시도별 월 지수로 최근 달 기준으로 맞춤(최근 12개월 거래 사용)
 ③ 좌표 격자(약 350m) 안 거래의 환산 가격 평균을 시군구 평균 쪽으로 당김(표본이 적을수록 더 당김, 당기는 정도는 자료의 격자 간 분산·격자 안 분산으로 계산 - 고정 숫자 없음)
 ④ 이웃 격자(3×3, 약 1km) 가중 평균으로 생활권 수준을 만듦 → 이 값으로 순위
 ⑤ 지하철역까지 거리(transit_features)는 참고 정보로 같이 저장
검증: 12~24개월 전 거래로 만든 격자 값이 최근 12개월 거래의 환산 가격을 시군구 평균보다 얼마나 더 잘 맞히는가(중앙 오차)
출력: location-index.json (앱이 정적 파일로 한 번만 읽음 - API 호출 없음). 형식 cells: [위도*1e4, 경도*1e4, 기준물건 평당가(만원), 거래수, 지하철m(-1 없음), 전국 백분위]
"""
import os, json, importlib.util
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)

LAT_STEP, LON_STEP = 0.0032, 0.0040     # 약 350m × 350m (위도 37도 부근)
MIN_N = 6                               # 격자 최소 거래 수


def keyvars(df):
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    return k_new, k_leg, k_leg0


def lookup(df, mp):
    ks = keyvars(df); out = ks[0].map(mp)
    for alt in ks[1:]: out = out.where(~out.isna(), alt.map(mp))
    return out


def classes(df, kind):
    size = df["size"].values
    sz = np.where(size < 40, 0, np.where(size < 50, 1, np.where(size < 60, 2, np.where(size < 85, 3, np.where(size < 102, 4, 5)))))
    age = (df["deal_date"] // 10000 - df["build_year"]).values
    ag = np.where(np.isnan(age), 2, np.where(age <= 5, 0, np.where(age <= 10, 1, np.where(age <= 20, 2, np.where(age <= 30, 3, 4)))))
    fl = df["floor"].values
    fc = np.where(np.isnan(fl), 3, np.where(fl <= 0, 0, np.where(fl == 1, 1, np.where(fl <= 3, 2, np.where(fl <= 7, 3, 4)))))
    return sz, ag, fc


def run(kind, trades_table, cols, cutoff_old, cut_recent, cmap, tmap, kapt=None):
    raw = avm.fetch_all_rows(trades_table, cols=cols, extra_filter=f"&deal_date=gte.{cutoff_old}")
    df = raw.copy()
    if "cdeal_type" in df.columns: df = df[df["cdeal_type"].fillna("").astype(str).str.strip() == ""]
    df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("price", "size", "floor", "deal_date", "build_year"): df[c] = pd.to_numeric(df[c], errors="coerce")
    lo_s, hi_s = (20, 250) if kind == "apt" else (15, 150)
    df = df.dropna(subset=["price", "size", "deal_date"])
    df = df[(df["price"] > 0) & (df["size"] >= lo_s) & (df["size"] <= hi_s)].copy()
    co = lookup(df, cmap)
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    df = df[df["lat"].notna() & df["lon"].notna() & df["lat"].between(33, 39) & df["lon"].between(124, 132)].copy()
    tr = lookup(df, tmap)
    df["sub"] = pd.to_numeric(tr, errors="coerce") if tr.notna().any() else np.nan
    df["region"] = df["region"].astype(str); df["sido"] = df["region"].str.split().str[0]
    df["lp"] = np.log(df["price"] / df["size"])
    df["q"] = df["deal_date"] // 10000 * 4 + ((df["deal_date"] // 100 % 100) - 1) // 3
    df["ym"] = df["deal_date"] // 100
    print(f"[{kind}] 좌표 있는 거래 {len(df):,}건")
    # ① 속성 보정 (같은 법정동·분기 안 편차로 면적대·연식대·층 효과를 덧셈 모델로 추정)
    df["sz"], df["ag"], df["fc"] = classes(df, kind)
    grp = df["region"] + "|" + df["dong"].astype(str) + "|" + df["q"].astype(str)
    dev = df["lp"] - df.groupby(grp)["lp"].transform("median")
    ok = (df.groupby(grp)["lp"].transform("size") >= 5).values
    eff = {c: {} for c in ("sz", "ag", "fc")}; pred = np.zeros(len(df))
    for _ in range(4):
        for c in ("sz", "ag", "fc"):
            cur = df[c].map(eff[c]).fillna(0).values
            r = (dev.values - (pred - cur))[ok]
            g = pd.Series(r).groupby(df[c].values[ok]).median().to_dict(); eff[c] = g
            pred = pred - cur + df[c].map(g).fillna(0).values
    refc = {"sz": 3, "ag": 2, "fc": 3}
    ref = sum(eff[c].get(refc[c], 0.0) for c in eff)
    df["adj"] = df["lp"] - pred + ref          # 기준 물건 환산 ln(㎡당 만원)
    print(f"[{kind}] 속성 효과(기준 물건=60~85㎡·11~20년·4~7층): " + json.dumps({c: {int(k): round(float(v), 3) for k, v in eff[c].items()} for c in eff}, ensure_ascii=False))
    # ② 시점 보정(시도별 월 지수 → 최근 달 기준)
    last_ym = int(df["ym"].max())
    mi = df.groupby(["sido", "ym"])["adj"].median().unstack("ym").T.sort_index().rolling(3, min_periods=1, center=True).mean().T
    target = mi.iloc[:, -3:].mean(axis=1)
    mi_d = mi.stack().to_dict()
    idx = pd.Series(list(zip(df["sido"], df["ym"])))
    cur = idx.map(mi_d).values
    tgt = df["sido"].map(target.to_dict()).values
    df["adj2"] = df["adj"] - np.where(np.isnan(cur), 0, cur) + np.where(np.isnan(tgt), 0, tgt)
    # 격자
    df["gi"] = np.floor(df["lat"] / LAT_STEP).astype(int); df["gj"] = np.floor(df["lon"] / LON_STEP).astype(int)

    def level_table(S):
        """S: 거래들 → 격자별 [n, 평균 환산값, 평균 위도·경도, 지하철] 과 시군구 평균, 경험적 베이즈로 당긴 값"""
        g = S.groupby(["gi", "gj"]).agg(n=("adj2", "size"), m=("adj2", "mean"), v=("adj2", "var"), lat=("lat", "mean"), lon=("lon", "mean"), sub=("sub", "median"), region=("region", lambda s: s.mode().iloc[0])).reset_index()
        par = S.groupby("region")["adj2"].mean(); g["par"] = g["region"].map(par).fillna(S["adj2"].mean())
        gg = g[g["n"] >= 3]
        sw2 = float((gg["v"].fillna(0) * (gg["n"] - 1)).sum() / max((gg["n"] - 1).sum(), 1))      # 격자 안 흩어짐(분산)
        sb2 = float(max(np.var(gg["m"] - gg["par"]) - np.mean(sw2 / gg["n"]), 1e-4))               # 격자끼리 진짜 차이(분산)
        k = sw2 / sb2
        g["sh"] = (g["n"] * g["m"] + k * g["par"]) / (g["n"] + k)
        return g, k, sw2, sb2

    # ④ 이웃 격자 평균(3×3)
    def smooth(g):
        d = {(r.gi, r.gj): (r.sh, r.n) for r in g.itertuples()}
        out = []
        for r in g.itertuples():
            num = den = 0.0
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    v = d.get((r.gi + di, r.gj + dj))
                    if v: w = v[1] * (2.0 if (di == 0 and dj == 0) else 1.0); num += w * v[0]; den += w
            out.append(num / den if den else r.sh)
        return np.array(out)

    # 검증: 12~24개월 전 격자 값 → 최근 12개월 환산 가격
    old = df[df["deal_date"] < cut_recent]; rec = df[df["deal_date"] >= cut_recent]
    meta = {}
    if len(old) > 5000 and len(rec) > 3000:
        go, ko, _, _ = level_table(old); go = go[go["n"] >= MIN_N].copy(); go["sm"] = smooth(go)
        mp = {(r.gi, r.gj): r.sm for r in go.itertuples()}
        par_old = old.groupby("region")["adj2"].mean()
        R = rec.copy(); R["pc"] = [mp.get((a, b), np.nan) for a, b in zip(R["gi"], R["gj"])]; R["pr"] = R["region"].map(par_old)
        R = R[R["pc"].notna() & R["pr"].notna()]
        e_cell = (R["adj2"] - R["pc"]).abs(); e_reg = (R["adj2"] - R["pr"]).abs()
        meta["검증"] = {"n": int(len(R)), "시군구 평균만 쓸 때 중앙 오차%": round(float(np.expm1(e_reg.median())) * 100, 2), "격자 입지 값 쓸 때 중앙 오차%": round(float(np.expm1(e_cell.median())) * 100, 2),
                      "오차 줄어든 비율%": round(float((e_cell < e_reg).mean()) * 100, 1)}
        print(f"[{kind}] 검증: {meta['검증']}")
    # 최근 12개월로 최종
    g, k, sw2, sb2 = level_table(rec)
    nall = {(r.gi, r.gj): int(r.n) for r in g.itertuples()}      # 모든 격자의 최근 12개월 거래 수(6건 미만 격자도 이웃 합계에는 포함)
    g = g[g["n"] >= MIN_N].copy(); g["sm"] = smooth(g)
    g["ppy"] = np.exp(g["sm"]) * 3.305785       # 만원/평(참고용)
    # 2026-11-14(사용자: 평단가 말고 거래가 얼마나 잘 이루어지는지로 입지 순위) - 점수 = 이 격자와 둘레 8격자(약 1km)의 최근 12개월 거래 건수 합
    g["act"] = [sum(nall.get((gi + di, gj + dj), 0) for di in (-1, 0, 1) for dj in (-1, 0, 1)) for gi, gj in zip(g["gi"], g["gj"])]
    g["pct"] = g["act"].rank(pct=True) * 100
    extra = {}
    if kind == "apt" and kapt is not None:
        # 2026-11-14(사용자: 아파트는 회전율) - 점수 = (이 격자+둘레 8격자의 최근 12개월 거래 합계) ÷ (그 안 단지들 세대수 합계). 세대수(K-apt)를 아는 단지만 분자·분모에 넣음
        R2 = rec.copy(); R2["nm"] = R2["danji"].map(avm.normalize_complex_name)
        R2 = R2.merge(kapt.rename(columns={"dong": "dong", "_name_norm": "nm"})[["region", "dong", "nm", "households"]], on=["region", "dong", "nm"], how="left")
        # 2026-11-14 세대수 연결 보완: 이름이 정확히 같지 않은 단지를 같은 법정동 안에서 이름 닮은 정도로 연결(괄호·'아파트·단지·마을' 같은 말 빼고 비교 → 같거나 한쪽이 다른 쪽을 포함하거나 85% 이상 닮고, 후보가 하나일 때만)
        import re, difflib
        def core(x):
            x = re.sub(r"\([^)]*\)", "", str(x or "")); x = re.sub(r"[^0-9A-Za-z가-힣]", "", x)
            for w in ("아파트", "단지", "마을"): x = x.replace(w, "")
            return x
        kg = {}
        for rg_, dg_, nn_, hh_ in zip(kapt["region"], kapt["dong"], kapt["_name_norm"], kapt["households"]): kg.setdefault((rg_, dg_), []).append((core(nn_), hh_))
        un = R2[R2["households"].isna()][["region", "dong", "nm"]].drop_duplicates()
        fz = {}; nfz = 0
        for r in un.itertuples():
            c0 = core(r.nm); cand = kg.get((r.region, r.dong))
            if not cand or len(c0) < 2: continue
            hit = [h for (kn, h) in cand if kn and (kn == c0 or ((len(kn) >= 3 and len(c0) >= 3) and (kn in c0 or c0 in kn)) or difflib.SequenceMatcher(None, kn, c0).ratio() >= 0.85)]
            if len(hit) == 1: fz[(r.region, r.dong, r.nm)] = hit[0]; nfz += 1
        print(f"[{kind}] 이름 닮은 정도로 새로 연결한 단지 {nfz:,}곳 / 이름이 안 맞던 단지 {len(un):,}곳")
        if fz:
            key = list(zip(R2["region"], R2["dong"], R2["nm"]))
            add = pd.Series([fz.get(k, np.nan) for k in key], index=R2.index)
            R2["households"] = R2["households"].where(R2["households"].notna(), add)
        known = R2["households"].notna() & (R2["households"] > 0)
        try:
            un2 = R2[~known]; kd = set(kapt["dong"].astype(str)); 
            print(f"[{kind}] 연결 안 된 거래 {len(un2):,}건 중 동 자체가 K-apt에 없는 거래 {int((~un2['dong'].astype(str).isin(kd)).sum()):,}건 · 상위 안 맞는 단지: " + ", ".join(f"{a}/{b}({c})" for (a, b), c in un2.groupby(['dong', 'nm']).size().sort_values(ascending=False).head(12).items()))
        except Exception as e: print("진단 실패", e)
        print(f"[{kind}] 최근 12개월 거래 {len(R2):,}건 중 세대수 아는 단지 거래 {int(known.sum()):,}건 ({known.mean() * 100:.1f}%)")
        K = R2[known].copy(); K["cid"] = K["region"] + "|" + K["dong"].astype(str) + "|" + K["nm"]
        cx = K.groupby("cid").agg(t=("lat", "size"), hh=("households", "first"), lat=("lat", "mean"), lon=("lon", "mean")).reset_index()
        cx["gi"] = np.floor(cx["lat"] / LAT_STEP).astype(int); cx["gj"] = np.floor(cx["lon"] / LON_STEP).astype(int)
        cg = cx.groupby(["gi", "gj"]).agg(t=("t", "sum"), hh=("hh", "sum")).to_dict("index")
        def nb(gi, gj):
            t = h = 0
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    v = cg.get((gi + di, gj + dj))
                    if v: t += v["t"]; h += v["hh"]
            return t, h
        res = [nb(a, b) for a, b in zip(g["gi"], g["gj"])]
        g["kt"] = [r[0] for r in res]; g["kh"] = [r[1] for r in res]
        g["cov"] = np.where(g["act"] > 0, g["kt"] / g["act"].clip(lower=1) * 100, 0)
        MIN_HH, MIN_COV = 500, 50.0
        g["turn"] = np.where(g["kh"] > 0, g["kt"] / g["kh"].clip(lower=1) * 100, np.nan)    # 연간 회전율 %
        ok = g["turn"].notna() & (g["kh"] >= MIN_HH) & (g["cov"] >= MIN_COV)
        print(f"[{kind}] 회전율 계산 가능 격자 {int(ok.sum()):,}/{len(g):,} (세대수 합 {MIN_HH}세대 이상·세대수 아는 거래 {MIN_COV:.0f}% 이상) · 회전율 분포 10/50/90%: {np.percentile(g.loc[ok, 'turn'], [10, 50, 90]).round(1)}")
        g = g[ok].copy(); g["pct"] = g["turn"].rank(pct=True) * 100
        extra = {"metric": "turnover", "minHouseholds": MIN_HH, "minCoverage": MIN_COV, "covered": round(float(known.mean()) * 100, 1)}
    meta.update({"k": round(float(k), 2), "격자 안 분산": round(sw2, 4), "격자 간 분산": round(sb2, 4), "격자 수": int(len(g)), "거래 수": int(len(rec))})
    print(f"[{kind}] 격자 {len(g):,}곳, k={k:.2f}, 평당 기준가 분포(만원) 10/50/90%: {np.percentile(g['ppy'], [10, 50, 90]).round(0)}")
    if extra:
        cells = [[int(round(r.lat * 1e4)), int(round(r.lon * 1e4)), int(round(r.turn * 10)), int(r.n), (int(r.sub) if pd.notna(r.sub) else -1), int(round(r.pct)), int(round(r.ppy)), int(r.kt), int(r.kh), int(round(r.cov))] for r in g.itertuples()]
        meta.update(extra)
    else:
        cells = [[int(round(r.lat * 1e4)), int(round(r.lon * 1e4)), int(r.act), int(r.n), (int(r.sub) if pd.notna(r.sub) else -1), int(round(r.pct)), int(round(r.ppy))] for r in g.itertuples()]
        meta["metric"] = "trades"
    return cells, meta


def main():
    now = datetime.now(timezone.utc); today = now.date()
    cut_recent = int((today - timedelta(days=365)).strftime("%Y%m%d")); cutoff_old = int((today - timedelta(days=730)).strftime("%Y%m%d"))
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id")
    cmap = {r.cache_key: (float(r.lat), float(r.lon)) for r in cc.itertuples() if r.lat and r.lon}
    tf = avm.fetch_all_rows("transit_features", cols="cache_key,dist_subway_m", order_col="cache_key")
    tmap = {r.cache_key: r.dist_subway_m for r in tf.itertuples() if pd.notna(r.dist_subway_m)}
    print(f"좌표 {len(cmap):,}건, 역거리 {len(tmap):,}건")
    kapt = avm.build_kapt_lookup()
    out = {"generatedAt": now.isoformat(), "ver": 3, "step": [LAT_STEP, LON_STEP], "note": "cells=[위도*1e4, 경도*1e4, 거래 활발도(이 격자+둘레 8격자 약 1km의 최근 12개월 거래 건수), 이 격자 거래 수, 지하철m(-1 없음), 전국 백분위(활발도), 기준 물건 평당가(만원, 참고)]", "types": {}}
    for kind, table, cols in (("apt", "house_trades", "region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year,cdeal_type"),
                              ("villa", "villa_trades", "region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year")):
        cells, meta = run(kind, table, cols, cutoff_old, cut_recent, cmap, tmap, kapt if kind == 'apt' else None)
        out["types"][kind] = {"cells": cells, "meta": meta}
    txt = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    open("location-index.json", "w", encoding="utf-8").write(txt)
    print(f"location-index.json {len(txt) / 1e6:.2f}MB")


if __name__ == "__main__":
    main()
