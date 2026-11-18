"""
저평가 아파트 후보 찾기 + 시장에서 말하는 저평가 기준이 실제로 맞았는지 시간순 검증 (2026-11-19, 사용자: 저평가 후보를 찾고 싶다 - 전국 아파트 단지, 시장에서 말하는 기준)
기준(모두 입력은 그 시점까지의 실거래만):
  ① 같은 지역·비슷한 연식 단지 대비 평당가(peer): 낮을수록 저평가
  ② 대장 단지와의 격차가 평소(최근 1~3년)보다 벌어진 정도(catch): 클수록 저평가(키 맞추기 여지)
  ③ 전고점 대비 낙폭(dd): 낙폭이 클수록 저평가
  ④ 전세가율: 전세 자료가 2024-07 이후라 시간순 검증은 못 하고, 현재 후보 표시에만 참고(있으면)
검증: 오늘 기준 최근 3·6·9·12개월 전을 각각 출발점으로 두고, 그 시점 자료만으로 점수를 내서 그 뒤 오늘까지 가격 변화가
같은 시군구 중앙 변화보다 얼마나 더 올랐는지(초과 변화)를 5분위로 비교. 평가 구간은 모두 같은 기준(사용자 지침: 오늘 기준 3·6·9·12개월).
결과: 현재 후보 상위를 leader_follower_cache 'signal|__undervalued__'에 저장(앱은 아직 안 씀).
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_s); _s.loader.exec_module(cyc)
avm = cyc.avm


def mi_of(ym):  # 년월(YYYYMM) → 월 번호
    return (ym // 100) * 12 + (ym % 100)


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type,build_year,cdeal_type", extra_filter=f"&deal_date=gte.{cyc.START_DATE}")
    df = raw
    if "cdeal_type" in df.columns:
        df = df[df["cdeal_type"].fillna("").astype(str).str.strip() == ""]
    if "dealing_type" in df.columns:
        df = df[df["dealing_type"] != "직거래"]
    for c in ("price", "size", "floor", "deal_date", "build_year"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"])
    df = df[(df["price"] > 0) & (df["size"] >= 55) & (df["size"] <= 90) & (df["floor"].fillna(5) >= 2)].copy()   # 중소형(전용 55~90㎡)·2층 이상으로 단지끼리 비교
    df["ppm"] = df["price"] / df["size"] * 3.305785   # 만원/평
    df["ym"] = (df["deal_date"] // 100).astype(int); df["mi"] = mi_of(df["ym"])
    df["dongk"] = df["dong"].astype(str).str.split().str[-1]
    df["ckey"] = df["region"].astype(str) + "|" + df["dongk"] + "|" + df["danji"].astype(str)
    mi_max_all = int(df["mi"].max()); Tend = mi_max_all - 1   # 마지막 달은 신고가 덜 들어와 뺌
    print(f"거래 {len(df):,}건, 단지 {df['ckey'].nunique():,}곳, 마지막 기준 월 {Tend // 12}-{Tend % 12:02d}", flush=True)
    attr = df.groupby("ckey").agg(region=("region", "first"), dongk=("dongk", "first"), danji=("danji", "first"), by=("build_year", lambda s: s.mode().iloc[0] if s.notna().any() else np.nan))
    sgg = attr["region"].astype(str).str.split().str[:2].str.join(" ")   # 시군구(구가 붙은 시는 시+구까지 쓰면 너무 잘게 쪼개져 앞 2토큰)
    attr["sgg"] = sgg

    def level(t0, t1, minn=3):
        s = df[(df["mi"] >= t0) & (df["mi"] <= t1)].groupby("ckey")["ppm"].agg(["median", "count"])
        return s[s["count"] >= minn]["median"], s["count"]

    def scores(T):
        """출발 시점 T(월 번호)의 점수 표 - T까지의 거래만"""
        p, n = level(T - 5, T)
        if len(p) < 50: return None
        S = pd.DataFrame({"p": p}).join(attr[["sgg", "dongk", "by"]], how="left")
        S["n12"] = df[(df["mi"] >= T - 11) & (df["mi"] <= T)].groupby("ckey").size().reindex(S.index).fillna(0)
        S["band"] = (S["by"] // 5).fillna(-1)
        g_b = S.groupby(["sgg", "band"])["p"].transform("median"); g_c = S.groupby(["sgg", "band"])["p"].transform("count")
        g_r = S.groupby("sgg")["p"].transform("median")
        base = np.where(g_c >= 5, g_b, g_r)
        S["peer"] = np.log(S["p"] / base)   # ① 낮을수록 저평가
        # ② 대장(같은 동에서 12개월 거래 10건 이상 중 평당가 최고, 동 단지가 3곳 미만이면 시군구) 대비 격차와 평소 격차
        def leader_price(Tm):
            pm, _ = level(Tm - 5, Tm); L = pd.DataFrame({"p": pm}).join(attr[["sgg", "dongk"]], how="left")
            n12 = df[(df["mi"] >= Tm - 11) & (df["mi"] <= Tm)].groupby("ckey").size(); L["n12"] = n12.reindex(L.index).fillna(0)
            big = L[L["n12"] >= 10]
            ld = big.groupby(["sgg", "dongk"])["p"].max(); lc = L.groupby(["sgg", "dongk"])["p"].count(); ls = big.groupby("sgg")["p"].max()
            return L, ld, lc, ls
        def gap_at(Tm, idx):
            L, ld, lc, ls = leader_price(Tm)
            key = list(zip(L["sgg"], L["dongk"])); lead = pd.Series([ld.get(k, np.nan) if lc.get(k, 0) >= 3 else np.nan for k in key], index=L.index)
            lead = lead.fillna(L["sgg"].map(ls))
            return np.log(L["p"] / lead).reindex(idx)
        gap_now = gap_at(T, S.index)
        hist = pd.concat([gap_at(T - m, S.index) for m in (12, 24, 36)], axis=1).median(axis=1)
        S["gap"] = gap_now; S["catch"] = hist - gap_now   # 클수록 평소보다 대장과 더 벌어져 있음(키 맞추기 여지)
        # ③ 전고점 대비 낙폭(최근 4년 6개월 중앙값 수준 중 최고 대비)
        lv = pd.concat([level(T - m - 5, T - m)[0].reindex(S.index) for m in (0, 6, 12, 18, 24, 30, 36, 42, 48)], axis=1)
        S["dd"] = np.log(S["p"] / lv.max(axis=1))   # 0이면 전고점, 음수일수록 낙폭
        return S

    def forward(T, S):
        pf, _ = level(Tend - 2, Tend, minn=2)
        f = np.log(pf.reindex(S.index) / S["p"])
        S = S.assign(fwd=f)
        S["rel"] = S["fwd"] - S.groupby("sgg")["fwd"].transform("median")   # 시군구 중앙 변화를 뺀 초과 변화
        return S

    out = {"기준월": f"{Tend // 12}-{Tend % 12:02d}", "검증": {}}
    CR = {"peer": ("낮을수록 저평가", True), "catch": ("클수록 저평가", False), "dd": ("낙폭 클수록 저평가", True)}
    for H in (3, 6, 9, 12):
        T = Tend - H; S = scores(T)
        if S is None: continue
        S = forward(T, S); S = S[(S["n12"] >= 8) & S["rel"].notna()]
        res = {"n": int(len(S)), "전체 초과변화 중앙%": round(float(S["rel"].median()) * 100, 2)}
        S["comp"] = -S["peer"].rank(pct=True) + S["catch"].rank(pct=True) - S["dd"].rank(pct=True)
        for k, (lab, asc) in list(CR.items()) + [("comp", ("종합(위 3개 순위 합)", False))]:
            v = S[k]; s = S.dropna(subset=[k]).copy()
            # 저평가가 높은 쪽이 q=4: peer/dd는 값이 작을수록 저평가 → 부호를 뒤집어 q 계산
            sign = -1 if k in ("peer", "dd") else 1
            s["q"] = pd.qcut((sign * s[k]).rank(method="first"), 5, labels=False)
            qs = s.groupby("q")["rel"].agg(["mean", "median", "count"])
            top, bot = s[s["q"] == 4], s[s["q"] == 0]
            res[k] = {"설명": lab, "5분위 초과변화 중앙%(저평가 5분위 → 고평가 1분위)": [round(float(qs.loc[q, "median"]) * 100, 2) for q in (4, 3, 2, 1, 0)],
                      "저평가 상위20% 초과변화 중앙%": round(float(top["rel"].median()) * 100, 2), "저평가 상위20%에서 시군구 중앙보다 더 오른 비율%": round(float((top["rel"] > 0).mean()) * 100, 1),
                      "고평가 하위20% 초과변화 중앙%": round(float(bot["rel"].median()) * 100, 2), "격차%p(상위-하위)": round(float(top["rel"].median() - bot["rel"].median()) * 100, 2), "표본": int(len(top))}
        out["검증"][f"{H}개월 전 출발"] = res
        print(f"  {H}개월 전 출발:", json.dumps(res, ensure_ascii=False), flush=True)
    # 현재 후보
    S = scores(Tend)
    cand = []
    if S is not None:
        S = S[S["n12"] >= 12].copy()
        S["comp"] = -S["peer"].rank(pct=True) + S["catch"].rank(pct=True) - S["dd"].rank(pct=True)
        S = S.join(attr[["region", "danji"]], how="left")
        S["p84"] = S["p"] * 84 / 3.305785 / 10000   # 84㎡ 환산 억
        top = S.sort_values("comp", ascending=False).head(300)
        for ck, r in top.iterrows():
            cand.append({"c": r["danji"], "r": r["region"], "dong": ck.split("|")[1], "by": None if pd.isna(r["by"]) else int(r["by"]), "n12": int(r["n12"]), "p84": round(float(r["p84"]), 2), "peer": round(float(r["peer"]) * 100, 1),
                         "catch": None if pd.isna(r["catch"]) else round(float(r["catch"]) * 100, 1), "dd": None if pd.isna(r["dd"]) else round(float(r["dd"]) * 100, 1), "score": round(float(r["comp"]), 3)})
        seoul = [c for c in cand if str(c["r"]).startswith("서울")][:30]
        out["서울 상위"] = seoul; print("서울 상위:", json.dumps(seoul[:15], ensure_ascii=False))
        print("전국 상위:", json.dumps(cand[:25], ensure_ascii=False))
    out["후보"] = cand
    print("📋 UV_JSON " + json.dumps({k: v for k, v in out.items() if k != "후보"}, ensure_ascii=False))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cyc.upsert_rows([{"id": "signal|__undervalued__", "payload": cyc.clean_json({"generatedAt": now, **out}), "fetched_at": now}])
    print("저장 완료")


if __name__ == "__main__":
    main()
