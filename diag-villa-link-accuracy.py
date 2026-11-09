"""
🔎 빌라 거래↔건축물대장 '매칭 정확도' 진단 (2026-11-09, 사용자: 빌라의 가장 큰 걱정은 건축물대장 매칭 정확도)
연결률(대장이 붙었나)이 아니라 연결된 대장이 '그 건물이 맞나'를 거래 자신이 가진 값과 대조해 추정한다.
 ① 연식: 거래의 건축년도 vs 대장 사용승인연도(같은 지번에 표제부가 여러 개면 그중 하나라도 ±1년)
 ② 층: 거래 층 ≤ 대장 지상층수 ③ 면적: 거래 전용면적 ≤ 대장 연면적
 ④ 지번 하나에 표제부(건물)가 여럿인 비율 - 이때 어느 건물인지 못 가림(앱은 최소 사용승인·최대 층·최대 승강기로 합침)
 ⑤ 불일치가 큰 쪽(연식 5년+ 차이)이 가격 예측에서 얼마나 틀리는지는 별도 시험
결과: link-accuracy.json (수도권 빌라 2023~). 측정만, 앱·서버 값은 건드리지 않음.
"""
import os, json, re, importlib.util
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avf", os.path.join(HERE, "analyze-villa-factors.py"))
avf = importlib.util.module_from_spec(_s); _s.loader.exec_module(avf)
bv = avf.bv; avm = bv.avm


def pct(x): return round(float(x) * 100, 1)


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year",
                             extra_filter=f"&deal_date=gte.20230101{avf.METRO}")
    df = bv.prep(raw)
    print(f"빌라 거래 {len(df):,}건")
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples()}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    cc2 = k_new.map(cmap)
    for alt in (k_leg, k_leg0):
        miss = cc2.isna(); cc2 = cc2.where(~miss, alt.map(cmap))
    df["sg"] = cc2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = cc2.map(lambda x: x[1] if isinstance(x, tuple) else None)
    bb = df["bunji"].map(avf.bunji_to_bunji)
    df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
    B = avf.fetch_buildings()
    for c in ("elv", "emg", "grnd", "hh", "tot", "plat"): B[c] = pd.to_numeric(B[c], errors="coerce")
    B["aprY"] = pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
    B = B[B["aprY"].between(1900, 2030) | B["aprY"].isna()]
    key = ["sigungu_cd", "bjdong_cd", "bun", "ji"]
    lot = B.groupby(key).agg(nt=("aprY", "size"), aprMin=("aprY", "min"), aprMax=("aprY", "max"), aprSet=("aprY", lambda s: sorted(set(int(x) for x in s.dropna()))),
                             grnd=("grnd", "max"), tot=("tot", "max"), hh=("hh", "sum"), purp=("purp", lambda s: ",".join(sorted(set(str(x) for x in s.dropna()))[:3]))).reset_index()
    out = {"거래수": int(len(df)), "대장 조회된 지번 수": int(len(lot))}
    M = df.merge(lot, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=key)
    n = len(M)
    out["좌표(법정동코드) 연결%"] = pct(M["sg"].notna().mean()); out["지번 해석%"] = pct(M["bun"].notna().mean()); out["대장 찾음%"] = pct(M["nt"].notna().mean())
    L = M[M["nt"].notna()].copy(); nl = len(L)
    print(f"대장 찾은 거래 {nl:,}건 ({nl / n * 100:.1f}%)")
    # ④ 지번당 표제부 수
    out["④ 지번당 표제부 수 분포%"] = {"1개": pct((L["nt"] == 1).mean()), "2개": pct((L["nt"] == 2).mean()), "3~5개": pct(L["nt"].between(3, 5).mean()), "6개+": pct((L["nt"] >= 6).mean())}
    # ① 연식
    by = L["build_year"].where(L["build_year"].between(1960, 2026))
    L["by"] = by
    A = L[L["by"].notna() & L["aprMin"].notna()].copy()
    out["① 연식 비교 가능 거래"] = int(len(A))
    def near(row_by, aset, tol): return any(abs(row_by - a) <= tol for a in aset)
    single = A[A["nt"] == 1]; multi = A[A["nt"] > 1]
    d1 = (single["by"] - single["aprMin"]).abs()
    out["① 연식 차이 (표제부 1개 지번)"] = {"n": int(len(single)), "0~1년%": pct((d1 <= 1).mean()), "2~3년%": pct(d1.between(2, 3).mean()), "4~5년%": pct(d1.between(4, 5).mean()), "6년+%": pct((d1 >= 6).mean())}
    if len(multi):
        ok1 = np.array([near(b, s, 1) for b, s in zip(multi["by"], multi["aprSet"])])
        ok_min = ((multi["by"] - multi["aprMin"]).abs() <= 1).values
        out["① 연식 (표제부 여러 개 지번) 하나라도 ±1년 일치%"] = {"n": int(len(multi)), "일치%": pct(ok1.mean()), "앱 방식(가장 오래된 표제부) 일치%": pct(ok_min.mean())}
    # 같은 지번 연식 불일치가 큰 건 비율 (전체)
    big = np.where(A["nt"].values == 1, (A["by"] - A["aprMin"]).abs().values >= 6, False)
    out["① 연식 6년+ 어긋난 거래%(전체 중)"] = pct(big.sum() / len(A))
    # ② 층
    F = L[L["floor"].notna() & L["grnd"].notna() & (L["grnd"] > 0)]
    out["② 거래 층이 대장 지상층보다 높음%"] = {"n": int(len(F)), "비율%": pct((F["floor"] > F["grnd"]).mean()), "2층+ 초과%": pct((F["floor"] > F["grnd"] + 1).mean())}
    # ③ 면적
    S = L[L["tot"].notna() & (L["tot"] > 0)]
    out["③ 거래 전용면적이 대장 연면적보다 큼%"] = {"n": int(len(S)), "비율%": pct((S["size"] > S["tot"]).mean())}
    # 건물 크기별: 지번에 표제부가 많거나 가구수 큰 곳에서 연식 불일치
    for lab, mask in (("표제부 1개", L["nt"] == 1), ("2개", L["nt"] == 2), ("3개+", L["nt"] >= 3)):
        X = A[A.index.isin(L[mask].index)]
        if len(X) > 200: out.setdefault("연식 6년+ 어긋남% (표제부 수별, 가장 오래된 표제부 기준)", {})[lab] = {"n": int(len(X)), "%": pct(((X["by"] - X["aprMin"]).abs() >= 6).mean())}
    # 시도별
    out["시도별"] = {}
    for sd, G in A.groupby(A["region"].astype(str).str[:2]):
        if len(G) > 500: out["시도별"][sd] = {"n": int(len(G)), "연식 0~1년 일치%": pct(((G["by"] - G["aprMin"]).abs() <= 1).mean()), "표제부 여러 개%": pct((G["nt"] > 1).mean())}
    # 연식 일치/불일치별 ㎡당 가격 동 내 분산(품질 영향 대략)
    A["dk"] = A["region"].astype(str) + "|" + A["dong"].astype(str)
    A["lp"] = np.log(A["ppm"]); A["dev"] = A["lp"] - A.groupby(["dk", A["deal_date"] // 100 // 3])["lp"].transform("median")
    A["match"] = np.where(A["nt"] == 1, np.where((A["by"] - A["aprMin"]).abs() <= 1, "일치", np.where((A["by"] - A["aprMin"]).abs() >= 6, "6년+불일치", "2~5년")), "다건")
    out["동 내 ㎡당 가격 흩어짐(|dev| 중앙값 %) 연식 일치별"] = {k: {"n": int(len(G)), "중앙|dev|%": pct(G["dev"].abs().median())} for k, G in A.groupby("match") if len(G) > 200}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("link-accuracy.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
