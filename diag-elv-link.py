"""승강기 값이 시험 거래의 66.7%에만 있던 원인 추적(2026-11-07): 연결 단계별 비율 + 대장을 읽어오는 방식(정렬 없는 페이지 읽기) 누락 여부."""
import os, json, importlib.util
from datetime import datetime, timezone
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py"); cyc = load("cyc", "analyze-cycle.py")
avm = bv.avm
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
df = bv.prep(raw)
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples()}
mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
c2 = k_new.map(cmap)
for alt in (k_leg, k_leg0): c2 = c2.where(~c2.isna(), alt.map(cmap))
df["sg"] = c2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = c2.map(lambda x: x[1] if isinstance(x, tuple) else None)
bb = df["bunji"].map(vf.bunji_to_bunji); df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
T = df[df["deal_date"] >= bv.TEST_FROM]
R = {"generatedAt": datetime.now(timezone.utc).isoformat(), "시험기간 거래수": int(len(T))}
pct = lambda m: round(float(m.mean()) * 100, 1)
R["① 좌표행→법정동코드 있음%"] = pct(T["sg"].notna() & T["bj"].notna())
R["② 번지 해석됨%"] = pct(T["bun"].notna())
# 대장 전체(정렬 읽기) - id, title_json 유무
bi = avm.fetch_all_rows("building_info", cols="id,sigungu_cd,bjdong_cd,bun,ji", order_col="id")
bi_null = avm.fetch_all_rows("building_info", cols="id", order_col="id", extra_filter="&title_json=is.null")
nullids = set(bi_null["id"].tolist()) if len(bi_null) else set()
bi["has"] = ~bi["id"].isin(nullids)
R["대장 행 수(정렬 읽기)"] = int(len(bi)); R["그중 내용 없음"] = int(len(nullids))
R["대장 키 중복 행"] = int(bi.duplicated(["sigungu_cd", "bjdong_cd", "bun", "ji"]).sum())
keyset = {(str(r.sigungu_cd), str(r.bjdong_cd), str(r.bun), str(r.ji)): r.has for r in bi.itertuples(index=False)}
tk = list(zip(T["sg"].astype(str), T["bj"].astype(str), T["bun"].astype(str), T["ji"].astype(str)))
hit = np.array([keyset.get(k) for k in tk], dtype=object)
R["③ 대장 행 있음%"] = round(float(np.mean([h is not None for h in hit])) * 100, 1)
R["④ 대장 행 있고 내용 있음%"] = round(float(np.mean([h is True for h in hit])) * 100, 1)
# 시험 때 쓴 읽기 방식
B = vf.fetch_buildings()
R["시험이 읽은 대장 행 수(정렬 없는 읽기)"] = int(len(B))
for c in ("elv", "emg"): B[c] = pd.to_numeric(B.get(c), errors="coerce")
R["읽은 행 중 승강기 칸(rideElvtCnt) 값 있음%"] = pct(B["elv"].notna()); R["읽은 행 중 비상용(emgenElvtCnt) 값 있음%"] = pct(B["emg"].notna())
R["읽은 행 중 승강기·비상용 둘 다 비어 있음%"] = pct(B["elv"].isna() & B["emg"].isna())
bk2 = set(zip(B["sigungu_cd"].astype(str), B["bjdong_cd"].astype(str), B["bun"].astype(str), B["ji"].astype(str)))
R["⑤ 시험 읽기로 대장 행 찾음%"] = round(float(np.mean([k in bk2 for k in tk])) * 100, 1)
Bv = B.dropna(subset=["elv", "emg"], how="all"); bk3 = set(zip(Bv["sigungu_cd"].astype(str), Bv["bjdong_cd"].astype(str), Bv["bun"].astype(str), Bv["ji"].astype(str)))
R["⑥ 그중 승강기 값 있는 행%"] = round(float(np.mean([k in bk3 for k in tk])) * 100, 1)
# 대장에는 있는데 시험 읽기에서 빠진 건물 예시
miss = [k for k in set(tk) if keyset.get(k) is True and k not in bk2]
R["대장엔 있고 시험 읽기엔 빠진 건물 수"] = int(len(miss)); R["예시"] = [list(k) for k in miss[:5]]
print(json.dumps(R, ensure_ascii=False, indent=1))
cyc.upsert_rows([{"id": "signal|__villa_bt_elvdiag__", "payload": cyc.clean_json(R), "fetched_at": R["generatedAt"]}])
