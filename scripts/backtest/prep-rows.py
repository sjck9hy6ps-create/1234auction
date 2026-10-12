"""분석 아티팩트(bidcases-R.csv.gz)에서 규칙 검증에 쓸 사례를 rows.json으로 뽑음(2026-10-12).
사용: gh run download <analyze-bidcases 실행 번호> -n bidcases-R  →  python scripts/backtest/prep-rows.py bidcases-R.csv.gz rows.json [최대 예상매도가(만원, 기본 10000)]
rows.json 한 줄 = [id, 입찰30일전 예상매도가, 낙찰가, 최저가, 되판가(같은 동 확인 시), 되판 개월, 같은 평형 1년 거래수(n12), 전용㎡, 층] (금액 만원)"""
import sys, json
import pandas as pd
src, dst = sys.argv[1], sys.argv[2]
cap = float(sys.argv[3]) if len(sys.argv) > 3 else 10000
R = pd.read_csv(src)
R = R[(R.sale >= 20230101) & R.est.notna() & (R.est < cap) & R.minbid.notna()]
n12 = R["n12"] if "n12" in R.columns else pd.Series(0, index=R.index)
f = lambda x: 0 if x != x else x
rows = []
for i, r in enumerate(R.itertuples()):
    ok = r.resale_conf == "dong" and r.resale == r.resale
    rows.append([r.id, float(r.est), float(f(r.actual)), float(r.minbid), float(r.resale) if ok else 0, float(r.resale_m) if ok and r.resale_m == r.resale_m else 0, int(f(n12.iloc[i])), float(r.area), int(f(r.floor))])
json.dump(rows, open(dst, "w"))
print(len(rows), "건 →", dst)
