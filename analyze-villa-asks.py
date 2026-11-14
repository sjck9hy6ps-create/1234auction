"""🏘 빌라 주변 호가 분석 (2026-11-14) - 확장이 쌓은 스냅샷(asks/villa/**)을 읽어 ① 호가를 해석(가격·면적·층) ② 지도 화면 중심 반경의 호가 중앙 ㎡당 가격을 만들고
③ 같은 반경의 최근 실거래(직전 6개월) ㎡당 중앙값과 비교한 '호가 갭'(= 호가/실거래 - 1)을 기록. ④ 쌓인 지 N일 지난 스냅샷은 이후 실제 거래와 비교해 '호가 갭이 이후 거래가를 설명하는지' 검증.
검증 질문: 같은 반경에서 (스냅샷 이후 60일) 거래의 ㎡당 가격 / (스냅샷 직전 6개월 거래 중앙) - 1 이 호가 갭과 같은 방향·비례하는가? (상관·방향 일치율·갭 구간별 평균 이후 변화)
호가는 부풀려지는 값이므로 '갭 그 자체'가 아니라 '갭이 클 때 이후 거래가 어떻게 되는가'만 본다. 통과 전에는 앱 계산에 넣지 않는다."""
import os, re, json, glob, gzip
import numpy as np, pandas as pd, requests
from scipy.spatial import cKDTree
SB = os.environ["SUPABASE_URL"].rstrip("/"); KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]; HD = {"apikey": KEY, "Authorization": "Bearer " + KEY}
RAD_KM = float(os.environ.get("RAD_KM", "0.5")); HORIZON = int(os.environ.get("HORIZON", "60"))

def parse_price(s):  # '매매3억 5,000' / '매매 9,800' / '매매2억' -> 만원
    m = re.match(r"^매매\s*(?:(\d+)억)?\s*([\d,]+)?", s)
    if not m or (not m.group(1) and not m.group(2)): return None
    return (int(m.group(1)) * 10000 if m.group(1) else 0) + (int(m.group(2).replace(",", "")) if m.group(2) else 0)
def parse_item(blk):
    L = blk.split("\n"); pl = next((l for l in L if re.match(r"^매매\s*[\d억]", l)), None)
    if not pl: return None
    price = parse_price(pl)
    t = " ".join(L)
    ar = re.search(r"(?:전용|공급)?\s*(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", t)   # 전용 우선
    ex = re.search(r"전용\s*(\d+(?:\.\d+)?)", t)
    area = float(ex.group(1)) if ex else (float(ar.group(1)) if ar else None)
    fl = re.search(r"(\d+|저|중|고)\s*/\s*(\d+)\s*층", t); floor = int(fl.group(1)) if fl and fl.group(1).isdigit() else None
    return {"price": price, "area": area, "floor": floor}
def lst(prefix):
    out = []; stack = [prefix]
    while stack:
        p = stack.pop(); off = 0
        while True:
            r = requests.post(f"{SB}/storage/v1/object/list/data", headers=HD, json={"prefix": p, "limit": 1000, "offset": off}, timeout=60); r.raise_for_status(); j = r.json()
            for o in j:
                if o.get("id") is None: stack.append(p + o["name"] + "/")
                else: out.append(p + o["name"])
            if len(j) < 1000: break
            off += 1000
    return out
def main():
    files = lst("asks/villa/"); print("스냅샷 파일", len(files), flush=True)
    snaps = []
    for f in files:
        r = requests.get(f"{SB}/storage/v1/object/data/{f}", headers=HD, timeout=60)
        if r.ok: snaps.append(r.json())
    if not snaps: print("아직 쌓인 호가가 없어요"); json.dump({"snapshots": 0}, open("villa-asks-report.json", "w")); return
    df = pd.read_pickle(os.environ.get("DF_FILE", "input/villa-df.pkl")); df = df[df["lat"].notna() & (df["size"] > 0)].copy()
    KM = 111.0 * np.cos(np.radians(37.5)); tree = cKDTree(np.c_[df["lat"].values * 111.0, df["lon"].values * KM])
    day0 = pd.Timestamp("2020-01-01"); ddate = (day0 + pd.to_timedelta(df["day"].values, unit="D")).values
    ppm = df["ppm"].values
    rows = []
    for s in snaps:
        at = pd.Timestamp(s["at"]).tz_localize(None); its = [parse_item(b) for b in s["items"]]; its = [x for x in its if x and x["price"] and x["area"] and x["area"] > 10]
        if len(its) < 5: continue
        ask_ppm = np.median([x["price"] / x["area"] for x in its])
        ii = np.array(tree.query_ball_point([s["lat"] * 111.0, s["lon"] * KM], RAD_KM))
        if len(ii) < 10: continue
        past = ii[(ddate[ii] < np.datetime64(at)) & (ddate[ii] >= np.datetime64(at - pd.Timedelta(days=180)))]
        fut = ii[(ddate[ii] >= np.datetime64(at)) & (ddate[ii] < np.datetime64(at + pd.Timedelta(days=HORIZON)))]
        if len(past) < 8: continue
        tr_ppm = float(np.median(ppm[past])); row = {"at": s["at"], "lat": s["lat"], "lon": s["lon"], "n_ask": len(its), "n_past": int(len(past)), "ask_ppm": float(ask_ppm), "trade_ppm": tr_ppm, "gap": float(ask_ppm / tr_ppm - 1)}
        if len(fut) >= 5: row["fut_change"] = float(np.median(ppm[fut]) / tr_ppm - 1); row["n_fut"] = int(len(fut))
        rows.append(row)
    R = pd.DataFrame(rows); print(R.describe().T.to_string() if len(R) else "해석 가능한 스냅샷 없음")
    rep = {"snapshots": len(snaps), "usable": int(len(R))}
    if len(R):
        rep["호가갭 중앙"] = round(float(R["gap"].median()) * 100, 1)
        V = R.dropna(subset=["fut_change"]) if "fut_change" in R else R.iloc[:0]
        rep["검증 가능"] = int(len(V))
        if len(V) >= 30:
            rep["상관"] = round(float(np.corrcoef(V["gap"], V["fut_change"])[0, 1]), 3)
            rep["방향 일치율"] = round(float((np.sign(V["gap"] - V["gap"].median()) == np.sign(V["fut_change"] - V["fut_change"].median())).mean()) * 100, 1)
            V = V.assign(q=pd.qcut(V["gap"], 3, labels=["갭 작음", "중간", "갭 큼"])); rep["갭 구간별 이후 변화%"] = {str(k): round(float(g["fut_change"].median()) * 100, 2) for k, g in V.groupby("q")}
        else: rep["메모"] = "검증에 필요한 30건이 아직 안 쌓였어요(스냅샷 후 60일 지난 것)"
    print(json.dumps(rep, ensure_ascii=False, indent=1)); json.dump(rep, open("villa-asks-report.json", "w"), ensure_ascii=False, indent=1)
if __name__ == "__main__": main()
