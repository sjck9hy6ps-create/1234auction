"""금리 인상·인하기를 2017-09부터의 전체 실거래(house_trades)로 본다(2026-11-15, 사용자: 17년도 매매기록 전체로).
 ① 시도·전국 월별 가격지수(analyze-cycle.py와 같은 단지 고정효과 지수 - 거래 구성 변화에 덜 흔들림)
 ② 한국은행 기준금리·주담대 금리(2017~) - 서버 ecosRaw 통로
 A) 기준금리를 바꾼 달 기준: 직전 6개월 vs 이후 6·12개월 전국·시도 지수 변화, 사이클 시작 시점별 표
 B) 전국 지수 고점·저점(지그재그)과 기준금리 방향 전환의 선후
 C) 시간순 채점: 그 시점 이전 자료로만 학습해 6개월 뒤 변화 예측 - 가격 흐름만 / +거래량 / +금리, 구간별
앱·서버에는 아무것도 저장하지 않음."""
import os, sys, json, math, time, importlib.util
import numpy as np, pandas as pd, requests
from sklearn.ensemble import HistGradientBoostingRegressor
HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(_s); _s.loader.exec_module(cyc)
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
def get(params, tries=4):
    for k in range(tries):
        try: return requests.get(f"{SITE}/api/data-coverage", params=params, timeout=90).json()
        except Exception: time.sleep(2 * (k + 1))
    return {}
def ecos(stat, cycle, frm, to, item):
    d = get({"mode": "ecosRaw", "stat": stat, "cycle": cycle, "from": frm, "to": to, "item": item, "count": 20000})
    rows = (d.get("StatisticSearch") or {}).get("row") or []
    return [(r["TIME"], float(r["DATA_VALUE"])) for r in rows if r.get("DATA_VALUE") not in (None, "")]
now = pd.Timestamp.utcnow(); ymd = now.strftime("%Y%m%d"); ym_now = now.strftime("%Y%m")
base_d = ecos("722Y001", "D", "20170101", ymd, "0101000"); mort_m = ecos("121Y006", "M", "201701", ym_now, "BECBLA0302")
print("기준금리 일별", len(base_d), base_d[0] if base_d else None, "~", base_d[-1] if base_d else None, "· 주담대 월별", len(mort_m))
base_m = {}
for t, v in base_d: base_m[int(t[:6])] = v          # 그 달 마지막 값
mort = {int(t[:6]): v for t, v in mort_m}
def ym_idx(ym): return (ym // 100) * 12 + (ym % 100) - 1
def ym_back(ym, n): i = ym_idx(ym) - n; return (i // 12) * 100 + (i % 12) + 1
def gm(d, ym, back=0):
    k = ym_back(ym, back)
    for _ in range(6):
        if k in d: return d[k]
        k = ym_back(k, 1)
    return np.nan
# ① 지수
raw = cyc.avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter=f"&deal_date=gte.{cyc.START_DATE}")
df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
for c in ("price", "size", "floor", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"])
df = df[(df["price"] > 0) & (df["size"] > 10) & (df["floor"].fillna(5) >= 2)]
df["logp"] = np.log(df["price"] / df["size"] * 3.305785); df["ym"] = cyc.ym_of(df["deal_date"])
df["unit"] = df["region"].astype(str) + "|" + df["dong"].astype(str).str.split().str[-1] + "|" + df["danji"].astype(str) + "|" + (df["size"] / cyc.SIZE_BUCKET_M2).round().astype(int).astype(str)
df["sido"] = df["region"].astype(str).str.split().str[0]
last_full = int(df["ym"].max()) - 1; df = df[df["ym"] <= last_full]
print("실거래", len(df), "건", int(df.ym.min()), "~", last_full)
IDX, CNT, RAW = {}, {}, {}
def to_ym(k): return (int(k) // 12) * 100 + int(k) % 12 + 1   # analyze-cycle의 월 번호(연*12+월-1) → YYYYMM
for name, sub in [("전국", df)] + [(s, g) for s, g in df.groupby("sido") if len(g) > 20000]:
    s, n = cyc.fe_index(sub, "unit", "ym"); s = s[n.reindex(s.index).fillna(0) >= cyc.MIN_UNITS_PER_MONTH]
    if len(s) >= 36:
        RAW[name] = s; sm = cyc.smooth_series(s, "trail"); cn = sub.groupby("ym").size().reindex(sm.index).fillna(0)
        sm.index = [to_ym(k) for k in sm.index]; cn.index = sm.index; IDX[name] = sm; CNT[name] = cn
print("지수 만든 지역", list(IDX))
# A) 기준금리 변동 달 기준
chg = []
prev = None
for t, v in base_d:
    if prev is not None and abs(v - prev) > 1e-9: chg.append((int(t[:6]), v - prev, v))
    prev = v
nat = IDX["전국"]
def fwd(s, ym, h): a, b = ym, ym_back(ym, -h) if False else None, None
def ch(s, ym, h):
    i0, i1 = ym, (ym_idx(ym) + h); i1 = (i1 // 12) * 100 + (i1 % 12) + 1
    return float(s[i1] - s[i0]) if (i0 in s.index and i1 in s.index) else np.nan
print("\n[A] 기준금리 변경과 전국 가격지수(로그 변화 %)")
print("달      변경     이후금리   직전6개월  이후6개월  이후12개월  이후18개월")
for ym, dl, lv in chg:
    if ym < 201709: continue
    pre = ch(nat, ym_back(ym, 6), 6)
    print(f"{ym}  {dl:+.2f}%p  {lv:.2f}%   {pre*100:+6.2f}   {ch(nat, ym, 6)*100:+6.2f}   {ch(nat, ym, 12)*100:+6.2f}   {ch(nat, ym, 18)*100:+6.2f}")
CYC = [("2017-11 인상 시작", 201711), ("2019-07 인하 시작", 201907), ("2021-08 인상 시작", 202108), ("2024-10 인하 시작", 202410), ("2026-07 인상 시작", 202607)]
print("\n사이클 시작 시점별 시도 지수 이후 12개월 변화 %")
for lab, ym in CYC:
    row = {s: ch(IDX[s], ym, 12) * 100 for s in IDX if s != "전국"}
    row = {k: v for k, v in row.items() if np.isfinite(v)}
    if row: print(f"{lab}: 전국 {ch(nat, ym, 12)*100:+.1f}% · 시도 중앙 {np.median(list(row.values())):+.1f}% · 오른 시도 {sum(v>0 for v in row.values())}/{len(row)}")
    else: print(f"{lab}: 이후 12개월 자료 없음(전국 이후 6개월 {ch(nat, ym, 6)*100:+.1f}%)")
# B) 지수 전환점 vs 금리 방향
pts = cyc.zigzag(cyc.smooth_series(RAW["전국"], "center"), 0.03)
for p_ in pts: p_["ym"] = to_ym(p_["ym"])
print("\n[B] 전국 지수 전환점(3% 되돌림)과 그때 기준금리")
for p in pts:
    ym = p["ym"]; print(f"{p['type']:6s} {ym}  기준금리 {gm(base_m, ym):.2f}% (6개월 전 대비 {gm(base_m, ym) - gm(base_m, ym, 6):+.2f}%p, 12개월 전 대비 {gm(base_m, ym) - gm(base_m, ym, 12):+.2f}%p)")
# C) 시간순 채점
rows = []
for s, idx in IDX.items():
    if s == "전국": continue
    cnt = CNT[s]
    for ym in idx.index:
        ym6, ym12, ymf = ym_back(ym, 6), ym_back(ym, 12), ym_back(ym, -6)
        if ym6 not in idx.index or ym12 not in idx.index or ymf not in idx.index: continue
        c3 = cnt.reindex([ym_back(ym, k) for k in range(3)]).sum(); c9 = cnt.reindex([ym_back(ym, k) for k in range(3, 12)]).sum()
        rows.append(dict(sido=s, ym=ym, y=float(idx[ymf] - idx[ym]), m3=float(idx[ym] - idx[ym_back(ym, 3)]) if ym_back(ym, 3) in idx.index else np.nan, m6=float(idx[ym] - idx[ym6]), m12=float(idx[ym] - idx[ym12]),
                         vol=math.log((c3 + 1) / (c9 / 3 + 1)), base=gm(base_m, ym), b6=gm(base_m, ym) - gm(base_m, ym, 6), b12=gm(base_m, ym) - gm(base_m, ym, 12), mort=gm(mort, ym), mt6=gm(mort, ym) - gm(mort, ym, 6)))
D = pd.DataFrame(rows).dropna(subset=["m12"]).reset_index(drop=True); D["t"] = D.ym.map(ym_idx)
print(f"\n[C] 시도 월별 {len(D)}행, {int(D.ym.min())}~{int(D.ym.max())}, 정답=6개월 뒤 지수 변화")
SETS = {"가격 흐름만": ["m3", "m6", "m12"], "+거래량": ["m3", "m6", "m12", "vol"], "+금리": ["m3", "m6", "m12", "vol", "base", "b6", "b12", "mort", "mt6"]}
WIN = [("2020-07~2021-12 인하 끝·급등", 202007, 202112), ("2022-01~2023-06 인상·하락", 202201, 202306), ("2023-07~2024-12 바닥·반등", 202307, 202412), ("2025-01~현재", 202501, 209912)]
for name, a, b in WIN:
    te = D[(D.ym >= a) & (D.ym <= b)]; tr = D[D.t <= ym_idx(a) - 6 - 1]
    if len(te) < 40 or len(tr) < 100: print(f"── {name}: 채점 {len(te)} · 학습 {len(tr)} → 자료 부족"); continue
    rev = np.sign(te.m6) != np.sign(te.y)
    print(f"── {name} (채점 {len(te)}행 · 학습 {len(tr)}행 · 지난 6개월과 방향이 뒤집힌 비율 {rev.mean()*100:.0f}%)")
    print(f"   {'변화 없음 예측':14s} 오차중앙 {np.median(np.abs(te.y))*100:.2f}%p")
    print(f"   {'지난 6개월 유지':14s} 오차중앙 {np.median(np.abs(te.y - te.m6))*100:.2f}%p  방향 {(np.sign(te.m6)==np.sign(te.y)).mean()*100:.1f}%")
    for sn, cols in SETS.items():
        X = tr[cols].fillna(tr[cols].median()); mdl = HistGradientBoostingRegressor(loss="absolute_error", max_iter=150, learning_rate=0.05, max_depth=3, min_samples_leaf=20, random_state=0).fit(X, tr.y)
        p = mdl.predict(te[cols].fillna(tr[cols].median())); e = te.y - p; hit = (np.sign(p) == np.sign(te.y)).mean(); hr = (np.sign(p[rev.values]) == np.sign(te.y[rev])).mean() if rev.sum() else float("nan")
        print(f"   {sn:14s} 오차중앙 {np.median(np.abs(e))*100:.2f}%p  방향 {hit*100:.1f}%  뒤집힌 구간 방향 {hr*100:.1f}%")
sub = D.dropna(subset=["b12"])
for lab, a, b in (("2017-09~2019-12", 201709, 201912), ("2020-01~2022-12", 202001, 202212), ("2023-01~현재", 202301, 209912)):
    s2 = sub[(sub.ym >= a) & (sub.ym <= b)]
    print(f"{lab}: 지난 12개월 기준금리 변화 ↔ 6개월 뒤 가격 변화 상관 {s2.b12.corr(s2.y):+.3f} · 지난 6개월 가격 ↔ 6개월 뒤 {s2.m6.corr(s2.y):+.3f} · 표본 {len(s2)}")
