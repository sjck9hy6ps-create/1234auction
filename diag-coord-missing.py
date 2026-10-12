"""좌표 변환이 안 된 건물 vs 된 건물의 차이 점검(2026-10-13, 사용자 요청) - 서버 최신 자료로 계산(병렬 받기).
complex_coords에 새·예전 두 키 형식 어느 것도 없는 거래 건물을 '좌표 없음'으로 보고, 특징별 비율·표본을 로그와 CSV로 남김."""
import os, re, importlib.util, collections, json
import pandas as pd
spec = importlib.util.spec_from_file_location("avm", "train-avm.py"); avm = importlib.util.module_from_spec(spec); spec.loader.exec_module(avm)
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd")
keys = set(cc["cache_key"].str.lower())
print("complex_coords 키", len(keys))
cols = "region,dong,danji,bunji,road_name,main_num,sub_num,deal_date,price,size,floor,build_year"
rows = []
for kind, table in (("apt", "house_trades"), ("villa", "villa_trades")):
    df = avm.fetch_all_rows(table, cols=cols)
    for c in ("dong", "danji", "bunji", "road_name"): df[c] = df[c].fillna("")
    # JSON 숫자가 소수(1.0)로 읽히지 않게 정수 문자열로 맞춤(앱 buildCacheKey와 같은 규칙: 주번 없으면 0, 부번 없으면 빈 칸)
    df["main_num"] = df["main_num"].map(lambda v: 0 if v is None or v != v or v == "" else int(float(v)))
    df["sub_num"] = df["sub_num"].map(lambda v: "" if v is None or v != v or v == "" else (str(int(float(v))) if str(v).replace(".", "", 1).isdigit() else str(v)))
    df["k"] = (df["dong"] + "|" + df["danji"] + "|" + df["bunji"] + "|" + df["road_name"] + "|" + df["main_num"].astype(str) + "|" + df["sub_num"].astype(str)).str.lower()
    g = df.groupby("k").agg(n=("price", "size"), last=("deal_date", "max"), by=("build_year", "max"), region=("region", "first"), dong=("dong", "first"), danji=("danji", "first"), bunji=("bunji", "first"), road=("road_name", "first"), size=("size", "median")).reset_index()
    g["kind"] = kind; g["has"] = g["k"].isin(keys)
    rows.append(g)
G = pd.concat(rows, ignore_index=True)
def feat(r):
    b, d, dg = r.bunji, r.danji, r.dong
    return {"번지": "없음" if not b else ("숫자-숫자" if re.fullmatch(r"\d+(-\d+)?", b) else "문자섞임"), "도로명": "있음" if r.road else "없음",
            "단지명": "없음" if not d else ("괄호형" if re.fullmatch(r"\(.*\)", d) else ("동표기 끝" if re.search(r"(\d+|[a-zA-Z가-힣])동\)?$", d) else "일반")),
            "동": "읍면리" if " " in dg else "동·가", "거래수": "1건" if r.n == 1 else ("2~4건" if r.n < 5 else "5건+"), "최근거래": "2025+" if r.last >= 20250101 else ("2023~24" if r.last >= 20230101 else "2022 이전")}
for kind in ("apt", "villa"):
    S = G[G.kind == kind]; print(f"===== {kind} 건물 {len(S):,} · 좌표 없음 {int((~S.has).sum()):,} ({(~S.has).mean()*100:.1f}%)")
    agg = collections.defaultdict(lambda: [0, 0])
    for r in S.itertuples():
        for fk, fv in feat(r).items():
            a = agg[(fk, fv)]; a[0] += 1; a[1] += (not r.has)
    for (fk, fv), a in sorted(agg.items()):
        if a[0] >= 30: print(f"  {fk:6s} {fv:10s} 건물 {a[0]:>7,} 좌표 없음 {a[1]:>6,} ({a[1]/a[0]*100:5.1f}%)")
M = G[~G.has].sort_values("n", ascending=False)
M.to_csv("coord-missing.csv", index=False)
print("좌표 없음 상위 30 (거래 많은 순):"); print(M.head(30)[["kind", "region", "dong", "danji", "bunji", "road", "n", "last"]].to_string(index=False))
print("무작위 표본 30:"); print(M.sample(min(30, len(M)), random_state=1)[["kind", "region", "dong", "danji", "bunji", "road", "n", "last"]].to_string(index=False))
