"""
════════════════════════════════════════════════════════════
인기(거래활발) 단지 검증 - 수도권 vs 지방 (2026-10)
════════════════════════════════════════════════════════════
사용자 가설(2026-10-04): "수도권은 모두 상향평균화돼 단지 자체 변화가 유의미하고, 지방은 인기 아파트만 거래되는
성향이 커서 같은 기준으로 보기 어렵다. 지방에서 정말 거래가 잘 되는 인기단지를 찾아 그 단지 경매물건 입찰에 집중하고 싶다."
검증(모두 그 시점까지의 자료로 인기 등급을 매기고, 이후 결과와 비교):
 1) 거래 쏠림: 동별 거래 상위 20% 단지가 최근 3년 거래의 몇 %를 차지하나
 2) 동행성: 단지 4분기 변화가 시군구 지수 4분기 변화를 얼마나 따라가나(상관) - 인기 등급별
 3) 등급별 이후 1년 초과수익(단지 − 시군구) - 시군구 상승기/하락기별
 4) 후발주자 신호(대장 대비 갭) 적중 - 인기 등급별
 5) 유동성: 최근 3년 중 거래가 있었던 분기 비율, 같은 분기 내 가격 흩어짐 - 등급별
결과: leader_follower_cache 'cycle|__liquidity__' (요약) + 'pop|<시군구>'(현재 인기 단지 목록·지표)
"""
import os
import sys
import json
import math
import importlib.util
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
avm = cyc.avm

METRO = ("서울", "인천", "경기")
WIN_Q = 12          # 인기 판단 창: 최근 3년(12분기)
FWD_Q = 4           # 이후 1년
MIN_DONG_CPLX = 4   # 동 안 단지가 이 이상일 때만 등급 비교


def tier_of(pct):
    return "상위20%" if pct >= 0.8 else ("중간" if pct >= 0.4 else "하위40%")


def analyze_region(dfr, region_q, leaders, cutoffs, seg, out):
    cq = cyc.complex_quarterly(dfr)
    cnt_q = dfr.groupby(["ckey", "q"], observed=True).size()
    disp = dfr.assign(res=dfr["logp"] - dfr.groupby("unit", observed=True)["logp"].transform("mean")) \
        .groupby(["ckey", "q"], observed=True)["res"].std()
    ck_dong = dfr.drop_duplicates("ckey").set_index("ckey")["dongk"].to_dict()
    ck_name = dfr.drop_duplicates("ckey").set_index("ckey")["danji"].to_dict()
    series = {ck: pd.Series(g["mean"].to_numpy(), index=g["q"].to_numpy()).sort_index() for ck, g in cq.groupby("ckey", observed=True)}
    counts = cnt_q.unstack(fill_value=0)  # ckey × q
    lead_key = {}
    for k in series:
        d = ck_dong.get(k); ld = leaders.get(d)
        if ld and avm.normalize_complex_name(ck_name.get(k)) == avm.normalize_complex_name(ld):
            lead_key[d] = k
    filled = {k: v.reindex(range(int(v.index.min()), int(v.index.max()) + 1)).interpolate(limit=2) for k, v in series.items()}
    max_q = int(dfr["q"].max())
    for c in cutoffs + [max_q]:
        win = [q for q in range(c - WIN_Q + 1, c + 1) if q in counts.columns]
        if not win:
            continue
        vol = counts[win].sum(axis=1)
        act = (counts[win] > 0).mean(axis=1)
        vdf = pd.DataFrame({"vol": vol, "act": act})
        vdf["dong"] = [ck_dong.get(k) for k in vdf.index]
        vdf = vdf[vdf["vol"] > 0]
        if c == max_q:
            # 2026-10(사용자: "평형에 따라 인기 단지가 달라질 것 같다") - 실측: 평형대별 상위 20% 단지 중 전체 상위 20%에 없는
            # 비율 소형 21%·중형 26%·대형 61%. 같은 동 안에서 평형대(소형 60㎡ 미만/중형 60~85㎡/대형 85㎡ 초과)별로 따로 등급을 매김.
            w = dfr[dfr["q"].isin(win)]
            if len(w):
                w = w.assign(band=np.where(w["size"] < 60, "소형", np.where(w["size"] <= 85, "중형", "대형")))
                grp = w.groupby([w["ckey"].astype(str), "band"])
                bdf = pd.DataFrame({"vol": grp.size(), "act": grp["q"].nunique() / len(win)}).reset_index()
                bdf.columns = ["ckey", "band", "vol", "act"]
                bdf["dong"] = bdf["ckey"].map(lambda k: ck_dong.get(k))
                for (dong, bnd), g in bdf.groupby(["dong", "band"]):
                    if len(g) < MIN_DONG_CPLX:
                        continue
                    g = g.assign(pct=g["vol"].rank(pct=True, method="average")).sort_values("vol", ascending=False)
                    lst = out["currentBand"].setdefault(dong, {}).setdefault(bnd, [])
                    for _, r in g.iterrows():
                        lst.append({"danji": ck_name.get(r["ckey"]), "tier": tier_of(r["pct"]), "trades3y": int(r["vol"]),
                                    "activeQuarterPct": round(float(r["act"]) * 100), "rankInBand": int((g["vol"] > r["vol"]).sum()) + 1,
                                    "complexesInBand": int(len(g))})
        for dong, g in vdf.groupby("dong"):
            if len(g) < MIN_DONG_CPLX:
                continue
            pct = g["vol"].rank(pct=True, method="average")
            if c == max_q:
                # 현재 인기 단지 목록(화면용)
                top = g.assign(pct=pct).sort_values("vol", ascending=False)
                for ck, r in top.iterrows():
                    out["current"].setdefault(dong, []).append({
                        "danji": ck_name.get(ck), "tier": tier_of(r["pct"]), "trades3y": int(r["vol"]),
                        "activeQuarterPct": round(float(r["act"]) * 100), "rankInDong": int((g["vol"] > r["vol"]).sum()) + 1,
                        "complexesInDong": int(len(g)),
                    })
                # 쏠림
                srt = np.sort(g["vol"].to_numpy())[::-1]
                k = max(1, int(math.ceil(len(srt) * 0.2)))
                out["concentration"].append(float(srt[:k].sum() / srt.sum()))
                continue
            for ck, p in pct.items():
                t = tier_of(p)
                s = series.get(ck)
                # 유동성·흩어짐(창 내부)
                out["liq"].append((t, float(g.loc[ck, "act"]), float(np.nanmean([disp.get((ck, q), np.nan) for q in win[-4:]]))))
                if s is None or c not in s.index and c - 1 not in s.index:
                    continue
                if c + FWD_Q not in region_q.index or c not in region_q.index:
                    continue
                s2 = filled[ck]
                if c not in s2.index or c + FWD_Q not in s2.index or pd.isna(s2.get(c)) or pd.isna(s2.get(c + FWD_Q)):
                    continue
                ex = float((s2[c + FWD_Q] - s2[c]) - (region_q[c + FWD_Q] - region_q[c]))
                reg_mom = float(region_q[c] - region_q[c - 4]) if c - 4 in region_q.index else 0.0
                phase = "상승기" if reg_mom > 0.02 else ("하락기" if reg_mom < -0.02 else "보합")
                out["ret"].append((t, phase, ex))
                # 후발주자 갭(대장 기준) - 등급별 적중
                lk = lead_key.get(dong)
                if lk:
                    if lk != ck:
                        L = filled[lk]
                        if all(q in L.index and not pd.isna(L[q]) for q in (c, c - 4)) and c - 4 in s2.index and not pd.isna(s2.get(c - 4)):
                            hist = pd.concat([L, s2], axis=1, keys=["L", "F"]).dropna()
                            hist = hist[hist.index <= c]
                            l4 = (hist["L"] - hist["L"].shift(4)).dropna(); f4 = (hist["F"] - hist["F"].shift(4)).dropna()
                            ix = l4.index.intersection(f4.index)
                            b = cyc.ols_slope(l4.loc[ix].to_numpy(), f4.loc[ix].to_numpy()) if len(ix) >= 4 else None
                            if b is not None:
                                b = max(0.0, min(1.5, b))
                                gap = b * (L[c] - L[c - 4]) - (s2[c] - s2[c - 4])
                                out["fol"].append((t, float(gap), ex))
    # 동행성(전체 기간): 단지 4분기 변화 vs 시군구 4분기 변화 상관 - 현재 등급 기준
    cur_tier = {}
    for dong, lst in out["current"].items():
        for x in lst:
            cur_tier[(dong, x["danji"])] = x["tier"]
    for ck, s in series.items():
        t = cur_tier.get((ck_dong.get(ck), ck_name.get(ck)))
        if not t:
            continue
        s2 = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1)).interpolate(limit=2)
        a = (s2 - s2.shift(4)).dropna()
        rr = (region_q - region_q.shift(4)).reindex(a.index).dropna()
        ix = a.index.intersection(rr.index)
        if len(ix) >= 8 and np.std(a.loc[ix]) > 0 and np.std(rr.loc[ix]) > 0:
            out["co"].append((t, float(np.corrcoef(a.loc[ix], rr.loc[ix])[0, 1])))


def summarize(acc):
    s = {}
    conc = np.array(acc["concentration"])
    if len(conc):
        s["top20ShareOfTradesMedianPct"] = round(float(np.median(conc)) * 100, 1)
    def by(lst, keyf, valf):
        d = {}
        for x in lst:
            d.setdefault(keyf(x), []).append(valf(x))
        return d
    s["coMovementCorrByTier"] = {k: {"n": len(v), "median": round(float(np.median(v)), 3)} for k, v in by(acc["co"], lambda x: x[0], lambda x: x[1]).items()}
    r = {}
    for (t, ph), v in by(acc["ret"], lambda x: (x[0], x[1]), lambda x: x[2]).items():
        v = np.array(v)
        r.setdefault(t, {})[ph] = {"n": int(len(v)), "avgExcess1yPct": round(float(v.mean()) * 100, 2), "beatRegionPct": round(float((v > 0).mean()) * 100, 1)}
    for t, v in by(acc["ret"], lambda x: x[0], lambda x: x[2]).items():
        v = np.array(v)
        r.setdefault(t, {})["전체"] = {"n": int(len(v)), "avgExcess1yPct": round(float(v.mean()) * 100, 2), "beatRegionPct": round(float((v > 0).mean()) * 100, 1)}
    s["excessReturnByTier"] = r
    f = {}
    for t, v in by(acc["fol"], lambda x: x[0], lambda x: (x[1], x[2])).items():
        a = np.array(v)
        big = a[:, 0] > 0.03
        f[t] = {"n": int(len(a)), "corr": round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 3) if len(a) > 10 else None,
                "gapPositiveHitPct": round(float((a[big, 1] > 0).mean()) * 100, 1) if big.any() else None,
                "gapPositiveAvgExcessPct": round(float(a[big, 1].mean()) * 100, 2) if big.any() else None}
    s["followerSignalByTier"] = f
    l = {}
    for t, v in by(acc["liq"], lambda x: x[0], lambda x: (x[1], x[2])).items():
        a = np.array(v, dtype=float)
        l[t] = {"n": int(len(a)), "activeQuarterPctMedian": round(float(np.nanmedian(a[:, 0])) * 100),
                "priceDispersionMedian": round(float(np.nanmedian(a[:, 1])), 3)}
    s["liquidityByTier"] = l
    return s


def main():
    now = datetime.now(timezone.utc).isoformat()
    print("🏃 인기(거래활발) 단지 검증 시작", now)
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type",
                             extra_filter=f"&deal_date=gte.{cyc.START_DATE}")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "floor", "deal_date"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"])
    df = df[(df["price"] > 0) & (df["size"] > 10) & (df["floor"].fillna(5) >= 2)]
    df["logp"] = np.log(df["price"] / df["size"] * 3.305785)
    df["ym"] = cyc.ym_of(df["deal_date"])
    df["q"] = df["ym"] // 3
    df["dongk"] = df["dong"].astype(str).str.split().str[-1]
    df["ckey"] = df["region"].astype(str) + "|" + df["dongk"] + "|" + df["danji"].astype(str)
    df["unit"] = df["ckey"] + "|" + (df["size"] / cyc.SIZE_BUCKET_M2).round().astype(int).astype(str)
    last_full_q = int(df["q"].max()) - 1   # 마지막 분기는 신고 지연으로 덜 들어옴
    df = df[df["q"] <= last_full_q].reset_index(drop=True)
    print(f"  {len(df):,}건")
    leaders = cyc.fetch_leaders()
    cutoffs = [q for q in range(int(df["q"].min()) + WIN_Q, last_full_q - FWD_Q + 1) if q % 2 == 0]
    current_only = os.environ.get("CURRENT_ONLY") == "1"  # 현재 인기 목록만 갱신(검증 생략 - 빠름)
    if current_only:
        cutoffs = []
    acc = {seg: {"concentration": [], "co": [], "ret": [], "fol": [], "liq": [], "current": {}, "currentBand": {}} for seg in ("수도권", "지방")}
    rows = []
    regions = sorted(df["region"].unique())
    for i, region in enumerate(regions):
        seg = "수도권" if str(region).startswith(METRO) else "지방"
        dfr = df[df["region"] == region]
        s, n = cyc.fe_index(dfr, "unit", "ym")
        s = s[n.reindex(s.index).fillna(0) >= cyc.MIN_UNITS_PER_MONTH]
        if len(s) < 36:
            continue
        trail = cyc.smooth_series(s, "trail")
        region_q = trail.groupby(trail.index // 3).mean()
        out = {"concentration": [], "co": [], "ret": [], "fol": [], "liq": [], "current": {}, "currentBand": {}}
        analyze_region(dfr, region_q, leaders.get(region, {}), cutoffs, seg, out)
        for k in ("concentration", "co", "ret", "fol", "liq"):
            acc[seg][k].extend(out[k])
        rows.append({"id": f"pop|{region}", "payload": cyc.clean_json({"region": region, "segment": seg, "asOfQuarter": cyc.q_label(last_full_q), "byDong": out["current"], "byDongBand": out["currentBand"]}), "fetched_at": now})
        if (i + 1) % 25 == 0:
            print(f"  지역 {i + 1}/{len(regions)}")
    summary = {"generatedAt": now, "windowQuarters": WIN_Q, "fwdQuarters": FWD_Q, "segments": {seg: summarize(a) for seg, a in acc.items()}}
    for seg, sm in summary["segments"].items():
        print(f"  [{seg}] {json.dumps(sm, ensure_ascii=False)}")
    if not current_only:
        rows.append({"id": "cycle|__liquidity__", "payload": cyc.clean_json(summary), "fetched_at": now})
    cyc.upsert_rows(rows)
    print(f"✅ 저장 완료 (시군구 {len(rows) - 1}곳)")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 인기 단지 검증\n\n```\n" + json.dumps(summary["segments"], ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
