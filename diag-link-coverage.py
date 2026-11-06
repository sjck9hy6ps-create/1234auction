"""🔎 빌라 거래↔건축물대장 연결률·전월세 자료 충분도 실측(2026-11-06, 사용자: "매주 대장을 수집하는데 왜 50%만 연결인가, 전세·거래 자료가 부족하다는 말이 이해가 안 된다")
연결이 안 되는 이유를 단계별로 나눠 셈: 좌표 행 없음 → 법정동코드 없음 → 지번 해석 실패 → 대장 행 없음(아직 조회 안 함) → 대장 행은 있으나 내용 비어 있음(조회했는데 없음/한도 오류) → 연결 성공. 거래 건수 가중.
전월세: 연도별 건수(매매 대비), 매매 건물 중 전월세 이력이 있는 비율. 결과는 signal|__link_diag__에 저장(서버 mode=linkDiag)."""
import os, re, json, importlib.util
from datetime import datetime, timezone
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cyc)
avm = cyc.avm
REPORT = {"generatedAt": datetime.now(timezone.utc).isoformat()}
CAP = ("서울", "경기", "인천")

def num(x, default=0):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)): return default
        return int(float(x))
    except Exception: return default

vt = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,deal_date,dealing_type", extra_filter="&deal_date=gte.20230101")
vt = vt[vt["region"].astype(str).str[:2].isin(CAP)].copy()
vt["y"] = (pd.to_numeric(vt["deal_date"], errors="coerce") // 10000).astype("Int64")
print("빌라 매매(수도권 2023~):", len(vt))
def keyof(r):
    mn = num(r.main_num, 0); sn = "" if (r.sub_num is None or (isinstance(r.sub_num, float) and np.isnan(r.sub_num)) or str(r.sub_num).strip() in ("", "0", "0.0")) else str(num(r.sub_num))
    return "|".join(str(x) for x in [r.dong or "", r.danji or "", r.bunji or "", r.road_name or "", mn, sn]).lower()
vt["k"] = [keyof(r) for r in vt.itertuples(index=False)]
G = vt.groupby("k").agg(n=("price", "size"), region=("region", "first"), bunji=("bunji", "first"), dong=("dong", "first"), last=("deal_date", "max")).reset_index()
cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd,lat,lon", order_col="id")
cc["ck"] = cc["cache_key"].astype(str).str.lower(); ccd = cc.drop_duplicates("ck").set_index("ck")
bi = avm.fetch_all_rows("building_info", cols="id,sigungu_cd,bjdong_cd,bun,ji", order_col="id")
bi_empty = avm.fetch_all_rows("building_info", cols="id", order_col="id", extra_filter="&title_json=is.null")
empty_ids = set(bi_empty["id"].tolist()) if len(bi_empty) else set()
bimap = {(str(r.sigungu_cd), str(r.bjdong_cd), str(r.bun), str(r.ji)): r.id for r in bi.itertuples(index=False)}
print("complex_coords:", len(cc), "building_info:", len(bi), "빈 대장:", len(empty_ids))
cat, ex = [], {}
for r in G.itertuples(index=False):
    s = ccd.loc[r.k] if r.k in ccd.index else None
    if s is None: c = "A 좌표 행 없음(아직 위치 조회 안 함)"
    elif not s["sigungu_cd"] or not s["bjdong_cd"] or str(s["bjdong_cd"]) in ("nan", "None", ""): c = "B 법정동코드 없음"
    else:
        p = str(r.bunji or "").split("-")
        if not p or not re.fullmatch(r"\d+", p[0] or "") or (len(p) > 1 and not re.fullmatch(r"\d+", p[1] or "")): c = "C 지번 해석 실패(번지 비었거나 산·글자)"
        else:
            hit = bimap.get((str(s["sigungu_cd"]), str(s["bjdong_cd"]), p[0].zfill(4), (p[1] if len(p) > 1 else "0").zfill(4)))
            c = "D 대장 행 없음(조회 대기)" if hit is None else ("E 대장 조회했으나 내용 없음" if hit in empty_ids else "F 연결 성공")
    cat.append(c)
    if len(ex.setdefault(c, [])) < 6 and r.n >= 3: ex[c].append([r.k, int(r.n)])
G["cat"] = cat
def summ(df):
    t = df["n"].sum(); b = df.groupby("cat")["n"].agg(["size", "sum"])
    return {c: {"건물": int(v["size"]), "거래%": round(float(v["sum"]) / t * 100, 1)} for c, v in b.iterrows()}
REPORT["연결_전체(수도권 2023~)"] = summ(G); REPORT["건물수"] = int(len(G)); REPORT["거래수"] = int(G["n"].sum())
G["cls"] = G["region"].astype(str).str[:2]
REPORT["연결_지역별"] = {c: summ(g_) for c, g_ in G.groupby("cls")}
G["recent"] = pd.to_numeric(G["last"], errors="coerce") >= 20250101
REPORT["연결_최근거래(2025~)건물"] = summ(G[G["recent"]])
G["busy"] = G["n"] >= 3
REPORT["연결_거래3건+건물"] = summ(G[G["busy"]])
REPORT["예시"] = ex
for k, v in REPORT.items():
    if k.startswith("연결_") and k != "연결_지역별": print(k, json.dumps(v, ensure_ascii=False))
# 전월세
rr = avm.fetch_all_rows("villa_rent", cols="region,dong,bunji,deposit,monthly_rent,deal_date", extra_filter="&deal_date=gte.20210101")
rr = rr[rr["region"].astype(str).str[:2].isin(CAP)].copy()
rr["y"] = (pd.to_numeric(rr["deal_date"], errors="coerce") // 10000).astype("Int64"); rr["ym"] = (pd.to_numeric(rr["deal_date"], errors="coerce") // 100).astype("Int64")
vt_all = avm.fetch_all_rows("villa_trades", cols="deal_date", extra_filter="&deal_date=gte.20210101", order_col="id")
vt_all["y"] = (pd.to_numeric(vt_all["deal_date"], errors="coerce") // 10000).astype("Int64")
REPORT["전월세_연도별"] = {str(int(y)): {"전월세": int((rr["y"] == y).sum()), "전세만": int(((rr["y"] == y) & (pd.to_numeric(rr["monthly_rent"], errors="coerce").fillna(0) == 0)).sum()), "매매(수도권+전국 빌라)": int((vt_all["y"] == y).sum())} for y in range(2021, 2027)}
REPORT["전월세_월별(최근24개월 건수)"] = {str(int(k)): int(v) for k, v in rr.groupby("ym").size().sort_index().tail(24).items()}
bk = lambda df: df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["bunji"].astype(str)
rr["bk"] = bk(rr); vt["bk"] = bk(vt)
rec_rent = set(rr[pd.to_numeric(rr["deal_date"], errors="coerce") >= 20240701]["bk"])
tb = vt[pd.to_numeric(vt["deal_date"], errors="coerce") >= 20250101].groupby("bk").size()
REPORT["전월세_이력_있는 건물"] = {"2025~ 매매 건물": int(len(tb)), "그중 2024-07~ 전월세 이력 있음%": round(float(tb.index.isin(rec_rent).mean()) * 100, 1), "거래 가중%": round(float(tb[tb.index.isin(rec_rent)].sum() / tb.sum()) * 100, 1), "거래 3건+ 건물에서%": round(float(tb[tb >= 3].index.isin(rec_rent).mean()) * 100, 1)}
rk = rr.groupby("bk").size()
REPORT["전월세_이력_건물당"] = {"전월세 있는 건물": int(len(rk)), "건물당 중앙 건수": float(rk.median())}
print(json.dumps({k: REPORT[k] for k in ("전월세_연도별", "전월세_이력_있는 건물", "전월세_이력_건물당")}, ensure_ascii=False))
cyc.upsert_rows([{"id": "signal|__link_diag__", "payload": cyc.clean_json(REPORT), "fetched_at": REPORT["generatedAt"]}])
json.dump(REPORT, open("link-diag.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장 완료")
