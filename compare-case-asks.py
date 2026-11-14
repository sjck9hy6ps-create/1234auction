"""🏘 한 사건 반경의 호가 vs 실거래 vs 앱 예상매도가 비교(2026-11-14, 참고용 - 앱 숫자는 바꾸지 않음).
환경변수: LAT, LON, AREA(㎡), YEAR(연식), SALE(앱 예상매도가 만원), AREA_TOL=10, YEAR_TOL=3, RAD_KM=0.5"""
import os, re, json, importlib.util
import numpy as np, pandas as pd, requests
from scipy.spatial import cKDTree
spec = importlib.util.spec_from_file_location("aa", "analyze-villa-asks.py"); aa = importlib.util.module_from_spec(spec); spec.loader.exec_module(aa)
LAT, LON, AREA, YEAR, SALE = [float(os.environ[k]) for k in ("LAT", "LON", "AREA", "YEAR", "SALE")]
AT = float(os.environ.get("AREA_TOL", "10")); YT = float(os.environ.get("YEAR_TOL", "3")); RAD = float(os.environ.get("RAD_KM", "0.5"))
KM = 111.0 * np.cos(np.radians(37.5))
def dist_km(la, lo): return float(np.hypot((la - LAT) * 111.0, (lo - LON) * KM))
files = aa.lst("asks/villa/"); snaps = []
for f in files:
    r = requests.get(f"{aa.SB}/storage/v1/object/data/{f}", headers=aa.HD, timeout=60)
    if r.ok: snaps.append(r.json())
rows = []
for s in snaps:
    d = dist_km(s["lat"], s["lon"])
    if d > RAD: continue
    for b in s["items"]:
        it = aa.parse_item(b)
        if not it or not it["price"] or not it["area"]: continue
        age = re.search(r"(\d+)년\s*(이상|이내)", b); it["age_tag"] = (age.group(1) + "년" + age.group(2)) if age else ""
        it["snap_at"] = s["at"]; it["raw"] = b.replace("\n", " / ")[:160]; rows.append(it)
A = pd.DataFrame(rows).drop_duplicates(subset=["price", "area", "floor", "raw"])
print(f"반경 {RAD}km 안 호가 {len(A)}건(중복 제거)")
if not len(A): raise SystemExit
A["ppm"] = A["price"] / A["area"]
sel = A[(A["area"] - AREA).abs() <= AT].copy()
# 연식: 호가 글에는 정확한 연식이 없고 '25년이상' 같은 구간만 있음 → 사건 연식에서 계산한 나이(올해-연식)가 구간과 겹치는지로 판단
age_now = 2026 - YEAR
def age_ok(t):
    if not t: return None
    n = int(re.search(r"\d+", t).group()); return (age_now >= n) if "이상" in t else (age_now <= n)
sel["age_ok"] = sel["age_tag"].map(age_ok)
print(f"면적 {AREA-AT:.0f}~{AREA+AT:.0f}㎡: {len(sel)}건 | 연식 구간 맞음 {int((sel['age_ok']==True).sum())}건, 구간표시 없음 {int(sel['age_ok'].isna().sum())}건, 안 맞음 {int((sel['age_ok']==False).sum())}건")
pd.set_option("display.width", 250, "display.max_colwidth", 110)
print(sel.sort_values("ppm")[["price", "area", "floor", "age_tag", "age_ok", "raw"]].to_string())
use = sel[sel["age_ok"] != False]
res = {"반경km": RAD, "호가 전체": int(len(A)), "면적 조건": int(len(sel)), "면적+연식 조건": int(len(use))}
if len(use):
    res["호가 ㎡당 중앙(만원)"] = round(float(use["ppm"].median()), 1); res["호가 환산(이 사건 면적, 만원)"] = int(use["ppm"].median() * AREA)
    res["호가 낮은쪽 25%·높은쪽 25% 환산"] = [int(use["ppm"].quantile(.25) * AREA), int(use["ppm"].quantile(.75) * AREA)]
# 실거래
df = pd.read_pickle(os.environ.get("DF_FILE", "input/villa-df.pkl")); df = df[df["lat"].notna() & (df["size"] > 0)].copy()
tree = cKDTree(np.c_[df["lat"].values * 111.0, df["lon"].values * KM]); ii = np.array(tree.query_ball_point([LAT * 111.0, LON * KM], RAD))
T = df.iloc[ii].copy(); T["date"] = pd.Timestamp("2020-01-01") + pd.to_timedelta(T["day"].values, unit="D")
by = T["by2"] if "by2" in T else T["build_year"]; T["by"] = by.where(by.notna(), T.get("build_year"))
print(f"반경 안 실거래 {len(T)}건, 최근 거래일 {T['date'].max().date()}")
def stat(X, nm):
    if len(X) == 0: res[nm] = {"건수": 0}; return
    res[nm] = {"건수": int(len(X)), "㎡당 중앙(만원)": round(float(X["ppm"].median()), 1), "환산(만원)": int(X["ppm"].median() * AREA), "최근 거래일": str(X["date"].max().date())}
cond = (T["size"] - AREA).abs() <= AT
for mo in (6, 12, 24):
    t0 = T["date"].max() - pd.Timedelta(days=30 * mo)
    stat(T[cond & (T["date"] >= t0)], f"실거래 면적조건 최근{mo}개월")
    stat(T[cond & (T["date"] >= t0) & ((T["by"] - YEAR).abs() <= YT)], f"실거래 면적+연식±{int(YT)} 최근{mo}개월")
res["앱 예상매도가(만원)"] = SALE
for k in ("실거래 면적+연식±3 최근12개월", "실거래 면적조건 최근12개월"):
    v = res.get(k, {})
    if v.get("환산(만원)") and "호가 환산(이 사건 면적, 만원)" in res:
        res["호가 갭(호가÷" + k + " - 1)"] = round((res["호가 환산(이 사건 면적, 만원)"] / v["환산(만원)"] - 1) * 100, 1)
        res["앱 예상매도가 ÷ " + k + " - 1(%)"] = round((SALE / v["환산(만원)"] - 1) * 100, 1)
print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("case-asks-report.json", "w"), ensure_ascii=False, indent=1)
