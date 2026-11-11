"""
🏘️ 빌라 대장 미연결 거래 원인 분류 (2026-11-11, 사용자: 시군구·동 1~4건 단계의 대장 연결을 높이기) - 측정 전용
빌라 거래 파일(villa-df.pkl, 2017~, 수도권)에서 2023년 이후 거래 중 대장(승강기 정보)이 안 붙은 것을 원인별로 나눠 센다.
 A 좌표·법정동코드 매칭 실패(sg 없음) / B 코드는 있으나 번지 해석 실패(bun 없음) / C 코드·번지는 있으나 대장에 그 번지 없음(조회 안 했거나 빈 결과) / D 대장은 붙었으나 승강기 값 없음
각 원인별 거래 수·건물 수·시군구 상위·번지 예시, 그리고 '시세 근거 단계가 약한 거래'(건물 거래 3건 미만) 중 비중.
"""
import json, os
import numpy as np, pandas as pd
df = pd.read_pickle(os.environ.get("DF_FILE", "input/villa-df.pkl"))
d = df[df["deal_date"] >= 20230101].copy(); print(f"2023~ 거래 {len(d):,}건")
d["elv_ok"] = d["elv"].notna(); d["sg_ok"] = d["sg"].notna(); d["bun_ok"] = d["bun"].notna()
def cause(r_sg, r_bun, r_elv, r_nt):
    return None
m = ~d["elv_ok"]
d["cause"] = np.where(d["elv_ok"], "연결됨", np.where(~d["sg_ok"], "A 코드 없음", np.where(~d["bun_ok"], "B 번지 해석 실패", "C 대장에 번지 없음")))
bc = d.groupby("bld").size(); d["bld_n"] = d["bld"].map(bc)
res = {"거래": int(len(d)), "연결률%": round(d["elv_ok"].mean() * 100, 2)}
tab = {}
for c, G in d.groupby("cause"):
    o = {"거래": int(len(G)), "비중%": round(len(G) / len(d) * 100, 2), "건물": int(G["bld"].nunique()), "건물거래 3건 미만 거래%": round(float((G["bld_n"] < 3).mean()) * 100, 1)}
    if c != "연결됨":
        o["시군구 상위"] = {str(k): int(v) for k, v in G["region"].value_counts().head(8).items()}
        o["연도별"] = {str(int(k)): int(v) for k, v in (G["deal_date"] // 10000).value_counts().sort_index().items()}
        o["예시(동|번지|도로명)"] = [f"{r.region} {r.dong} {r.bunji} {r.road_name}" for r in G.sample(min(12, len(G)), random_state=1).itertuples()]
        o["도로명 있음%"] = round(float(G["road_name"].fillna("").astype(str).str.len().gt(0).mean()) * 100, 1)
    tab[c] = o
res["원인별"] = tab
# 연결 안 된 건물이 거래 많은 순으로 몇 개나 되는지(조회 우선순위 후보)
bl = d[~d["elv_ok"]].groupby("bld").agg(n=("bld", "size"), region=("region", "first"), dong=("dong", "first"), bunji=("bunji", "first"), cause=("cause", "first")).sort_values("n", ascending=False)
res["미연결 건물 수"] = int(len(bl)); res["미연결 건물 상위 15"] = [f"{r.region} {r.dong} {r.bunji} ({r.n}건, {r.cause})" for r in bl.head(15).itertuples()]
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-unlinked.json", "w"), ensure_ascii=False, indent=1)
bl.reset_index().to_csv("villa-unlinked-buildings.csv", index=False)
