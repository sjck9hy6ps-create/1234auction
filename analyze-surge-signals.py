"""
══════════════════════════════════════════════════
🔥 급등·돈되는지역 신호 적중률 검증 (2026-10)
══════════════════════════════════════════════════
사용자 요청(2026-10-04): "급등, 돈되는 지역도 신뢰도를 높여서 사용하고 싶어."
앱의 세 가지 지역 신호를 과거 매달(2021-07 ~ 2025-09) 그 시점 자료만으로 다시 뽑고, 이후 6개월·1년 동안 그 동의
가격이 같은 시도의 다른 동들보다 더 올랐는지 확인함.
 - 돈되는 지역(priceMomentum): 최근 40일×6구간, 단지별 기준가 대비 상대지수(mix-shift 보정)가 3번 이상 오르며 상승률 상위
 - 거래 급등(topDongs): 최근 6개월 거래 건수 상위
 - 신고가(newHighDongs): 최근 240일 동안 단지·평형 신고가 거래 건수 상위
결과 지표(시도별·전체): 상위 N개 동이 이후 시도 중앙값보다 더 오른 비율(적중률), 평균 초과 상승률(%p)
결과: leader_follower_cache 'signal|__surge_backtest__'
"""
import os
import json
import importlib.util
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
avm = cyc.avm

SIDOS = [s.strip() for s in os.environ.get("SIDOS", "부산,광주,전남,대전,대구,울산,경남").split(",") if s.strip()]
TOP_N = int(os.environ.get("TOP_N", "20"))
BUCKET_DAYS = 40


def sido_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith(("전남광주", "광주", "전남")):
        return "전남광주"
    return s


def load(sido):
    # region은 "부산 해운대구"처럼 시도 접두어로 시작 - 전남은 통합 이후 "전남광주 ..."도 함께 잡힘
    return avm.fetch_all_rows("house_trades", cols="id,region,dong,danji,price,size,deal_date,dealing_type",
                              extra_filter=f"&deal_date=gte.20170101&region=like.{sido}*")


def main():
    now = datetime.now(timezone.utc).isoformat()
    frames = []
    for sd in SIDOS:
        try:
            d = load(sd)
            print(f"  {sd}: {len(d):,}건")
            frames.append(d)
        except Exception as e:
            print("  로드 실패", sd, e)
    tr = pd.concat(frames, ignore_index=True)
    tr = tr[tr["dealing_type"] != "직거래"] if "dealing_type" in tr.columns else tr
    for c in ("price", "size", "deal_date"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr = tr[(tr["price"] > 0) & (tr["size"] > 10)].copy()
    tr["d"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce")
    tr = tr.dropna(subset=["d"])
    tr["sido"] = tr["region"].map(sido_of)
    tr["key"] = tr["sido"] + "|" + tr["region"].astype(str).str.split(" ").str[-1] + "|" + tr["dong"].astype(str)
    tr["dk"] = tr["key"] + "|" + tr["danji"].astype(str)
    tr["ppm"] = tr["price"] / tr["size"]
    tr["sz"] = (tr["size"] / 5).round()
    # 신고가 여부: 같은 단지·비슷한 평형(5㎡ 단위)의 이전 최고가를 넘은 거래
    tr = tr.sort_values("d")
    cm = tr.groupby(["dk", "sz"])["price"].cummax()
    tr["prevmax"] = cm.groupby([tr["dk"], tr["sz"]]).shift(1)
    tr["newhigh"] = (tr["prevmax"].notna()) & (tr["price"] > tr["prevmax"])
    print(f"  전체 {len(tr):,}건")

    cutoffs = pd.date_range("2021-07-01", "2025-09-01", freq="MS")
    recs = []
    for T in cutoffs:
        W = tr[(tr["d"] >= T - pd.Timedelta(days=BUCKET_DAYS * 6)) & (tr["d"] < T)].copy()
        if W.empty:
            continue
        # ── 돈되는 지역: 단지 기준가 대비 상대지수 ──
        base = W.groupby("dk")["ppm"].mean()
        W["rel"] = W["ppm"] / W["dk"].map(base)
        W["b"] = ((T - W["d"]).dt.days // BUCKET_DAYS).clip(0, 5)
        g = W.groupby(["key", "b"])["rel"].agg(["mean", "size"]).reset_index()
        g.loc[g["size"] < 3, "mean"] = np.nan
        P = g.pivot(index="key", columns="b", values="mean").reindex(columns=range(6))
        P = P[[5, 4, 3, 2, 1, 0]]  # 오래된 → 최근
        P = P.ffill(axis=1).bfill(axis=1)
        P = P.dropna()
        diffs = P.diff(axis=1).iloc[:, 1:]
        up = (diffs > 0).sum(axis=1)
        mom = P[0] / P[5] - 1
        M = pd.DataFrame({"mom": mom, "up": up})
        M = M[M["up"] >= 3]
        M["sido"] = M.index.str.split("|").str[0]
        money = M.sort_values("mom", ascending=False).groupby("sido").head(TOP_N)
        # ── 거래 급등: 최근 6개월 건수 ──
        V = tr[(tr["d"] >= T - pd.Timedelta(days=182)) & (tr["d"] < T)].groupby("key").size().rename("n").to_frame()
        V = V[V["n"] >= 10]
        V["sido"] = V.index.str.split("|").str[0]
        hot = V.sort_values("n", ascending=False).groupby("sido").head(TOP_N)
        # ── 신고가 ──
        NH = W[W["newhigh"]].groupby("key").size().rename("n").to_frame()
        NH = NH[NH["n"] >= 2]
        NH["sido"] = NH.index.str.split("|").str[0]
        newh = NH.sort_values("n", ascending=False).groupby("sido").head(TOP_N)
        # ── 이후 성과: 단지별 (이후 구간 중앙 평단가 ÷ 직전 3개월 중앙 평단가), 동은 단지 중앙값 ──
        pre = tr[(tr["d"] >= T - pd.Timedelta(days=90)) & (tr["d"] < T)].groupby("dk")["ppm"].median()
        for horizon, (a, b) in {"6m": (150, 210), "12m": (330, 400)}.items():
            post = tr[(tr["d"] >= T + pd.Timedelta(days=a)) & (tr["d"] < T + pd.Timedelta(days=b))].groupby("dk")["ppm"].median()
            ch = (post / pre).dropna()
            if ch.empty:
                continue
            chk = ch.groupby(ch.index.str.rsplit("|", n=1).str[0]).median()
            F = chk.rename("fwd").to_frame()
            F["sido"] = F.index.str.split("|").str[0]
            smed = F.groupby("sido")["fwd"].median()
            F["excess"] = F["fwd"] - F["sido"].map(smed)
            for name, picks in (("money", money), ("hot", hot), ("newhigh", newh)):
                sel = F.loc[F.index.intersection(picks.index)]
                for k, row in sel.iterrows():
                    recs.append({"T": T.strftime("%Y-%m"), "h": horizon, "sig": name, "sido": row["sido"], "key": k,
                                 "excess": float(row["excess"]), "hit": bool(row["excess"] > 0)})
            # 비교용: 모든 동
            for sd, G in F.groupby("sido"):
                recs.append({"T": T.strftime("%Y-%m"), "h": horizon, "sig": "all", "sido": sd, "key": "*",
                             "excess": float(G["excess"].mean()), "hit": float((G["excess"] > 0).mean())})
        print("  ", T.strftime("%Y-%m"), "돈되는", len(money), "급등", len(hot), "신고가", len(newh))
    R = pd.DataFrame(recs)
    out = {"generatedAt": now, "sidos": SIDOS, "topN": TOP_N, "months": len(cutoffs), "bySignal": {}}
    S = R[R["sig"] != "all"]
    for (sig, h), G in S.groupby(["sig", "h"]):
        res = {"전체": {"n": int(len(G)), "hitPct": round(float(G["hit"].mean()) * 100, 1), "excessPctp": round(float(G["excess"].mean()) * 100, 2),
                       "excessMedPctp": round(float(G["excess"].median()) * 100, 2)}}
        for sd, H in G.groupby("sido"):
            res[sd] = {"n": int(len(H)), "hitPct": round(float(H["hit"].mean()) * 100, 1), "excessPctp": round(float(H["excess"].mean()) * 100, 2)}
        # 연도별(상승기/하락기에 따라 달라지는지)
        G2 = G.assign(y=G["T"].str[:4])
        res["byYear"] = {y: {"n": int(len(H)), "hitPct": round(float(H["hit"].mean()) * 100, 1), "excessPctp": round(float(H["excess"].mean()) * 100, 2)} for y, H in G2.groupby("y")}
        out["bySignal"].setdefault(sig, {})[h] = res
    print(json.dumps(out, ensure_ascii=False, indent=1))
    cyc.upsert_rows([{"id": "signal|__surge_backtest__", "payload": cyc.clean_json(out), "fetched_at": now}])
    print("✅ 저장 완료")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 급등·돈되는지역 적중률\n\n```\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
