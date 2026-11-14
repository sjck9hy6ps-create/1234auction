"""한 건물의 거래가 서버 종합 평가에서 '건물 거래 0건'으로 잡힌 이유 진단(2026-11-14)"""
import os, pandas as pd, importlib.util, sys
DONG = os.environ.get("DONG", "주교동"); BUN = os.environ.get("BUN", "305")
df = pd.read_pickle("input/villa-df.pkl")
print("전체 거래", len(df), "열:", list(df.columns)[:40])
d = df[df["dong"].astype(str) == DONG]
print(f"동 {DONG} 거래 {len(d)}건, region 값:", d["region"].value_counts().to_dict())
m = d[d["bunji"].astype(str).str.startswith(BUN)]
print(f"번지 {BUN}* 거래 {len(m)}건, bunji 값:", m["bunji"].value_counts().to_dict(), "danji 값:", m.get("danji", pd.Series(dtype=str)).value_counts().head(8).to_dict())
pd.set_option("display.width", 220)
cols = [c for c in ("region", "dong", "bunji", "danji", "bld", "deal_date", "floor", "size", "price", "dealing_type", "build_year", "by2") if c in m.columns]
print(m.sort_values("deal_date", ascending=False)[cols].head(25).to_string())
print("이 번지의 bld 키:", m["bld"].unique().tolist() if "bld" in m else None)
# 서버가 경매 쪽에서 만드는 키
spec = importlib.util.spec_from_file_location("cvs", "compute-villa-stack.py"); 
src = open("compute-villa-stack.py", encoding="utf-8").read()
import re
sido = re.search(r"^SIDO\s*=.*$", src, re.M)
ns = {}; exec(sido.group(0), ns)
t = "경기도 고양시 덕양구 주교동 305-1 현대그린빌라 1동".split(); sd = ns["SIDO"].get(t[0]); 
reg = f"{sd} {t[1][:-1]} {t[2]}" if (len(t) >= 3 and t[1].endswith("시") and t[2].endswith("구")) else f"{sd} {t[1]}"
print("서버가 만드는 경매 쪽 건물 키:", f"{reg}|주교동|305-1", "| 거래 쪽 같은 번지 키:", m["bld"].unique().tolist() if "bld" in m else None)
