"""🔨 수리(인테리어)된 집의 호가 프리미엄 측정(2026-11-14) - 사용자 계획: 수리해서 좋은 집으로 만들어 판다 → 수리된 집 호가가 같은 조건의 그 외 호가보다 얼마나 높은가, 앱의 수리비 가정(㎡당)을 넘는가.
방법: 쌓인 호가 스냅샷(asks/villa/**)에서 세입자 낀 매물 제외, 같은 스냅샷(지도 화면=같은 생활권) 안에서 ㎡당 가격의 로그를 '면적·층 구분·연식 구간'으로 보정한 뒤 수리 표시 여부의 효과를 추정(스냅샷 고정효과).
수리 표시: strict = 올수리·올리모델링·샤시(샷시)포함/까지 / broad = strict + 내부깔끔·완벽 등. 프리미엄은 호가끼리의 차이(호가는 흥정 전)이므로 실제 거래 프리미엄은 이보다 작을 수 있음."""
import os, re, json, importlib.util
import numpy as np, pandas as pd, requests
spec = importlib.util.spec_from_file_location("aa", "analyze-villa-asks.py"); aa = importlib.util.module_from_spec(spec); spec.loader.exec_module(aa)
files = aa.lst("asks/villa/"); snaps = []
for f in files:
    r = requests.get(f"{aa.SB}/storage/v1/object/data/{f}", headers=aa.HD, timeout=60)
    if r.ok: snaps.append(r.json())
rows = []
STRICT = re.compile(r"올수리|올리모델링|올\s*수리|샤시포함|샷시포함|샤시까지|샷시까지")
for si, s in enumerate(snaps):
    for b in s["items"]:
        it = aa.parse_item(b)
        if not it or not it["price"] or not it["area"] or it["tenant"]: continue
        L = b.split("\n"); pl = next((l for l in L if re.match(r"^매매\s*[\d억]", l)), ""); d = " ".join(L[L.index(pl) + 1:]) if pl in L else b
        age = re.search(r"(\d+)년\s*(이상|이내)", b); at = (age.group(1) + age.group(2)) if age else ""
        dm = re.search(r"/\d+층,\s*(\S+)", b); dr = dm.group(1) if dm else ""
        key = "|".join(str(x) for x in (it["price"], it["area"], it["floor"], it["maxF"], dr, d[:30]))
        rows.append({"snap": si, "lat": round(s["lat"], 3), "lon": round(s["lon"], 3), "price": it["price"], "area": it["area"], "floor": it["floor"], "maxF": it["maxF"], "repair": it["repair"], "strict": bool(STRICT.search(d)), "age": at, "key": key})
A = pd.DataFrame(rows).drop_duplicates(subset=["key", "lat", "lon"]); A = A[(A["area"] >= 20) & (A["area"] <= 85)].copy()
print(f"스냅샷 {len(snaps)}개, 세입자 제외 고유 호가 {len(A)}건, 수리 표시(strict) {int(A['strict'].sum())}건, (broad) {int((A['repair']=='full').sum() + 0)}건", flush=True)
A["ppm"] = A["price"] / A["area"]; A["ly"] = np.log(A["ppm"])
A["top"] = ((A["floor"].notna()) & (A["maxF"].notna()) & (A["floor"] >= A["maxF"])).astype(float); A["low"] = ((A["floor"].notna()) & (A["floor"] <= 1)).astype(float)
A["new"] = A["age"].isin(["5년이내", "10년이내"]).astype(float); A["mid_age"] = A["age"].isin(["15년이내", "20년이내", "25년이내"]).astype(float)
A["broad"] = ((A["repair"] == "full") | A["strict"]).astype(float); A["strictf"] = A["strict"].astype(float); A["need"] = (A["repair"] == "need").astype(float)
def fe_ols(D, xcols, ycol="ly", group="loc"):
    D = D.copy(); D[group] = D["lat"].astype(str) + "|" + D["lon"].astype(str)
    g = D.groupby(group); keep = g[ycol].transform("size") >= 8; D = D[keep]
    Y = D[ycol] - g[ycol].transform("mean")[keep]; X = pd.DataFrame({c: D[c] - D.groupby(group)[c].transform("mean") for c in xcols})
    XtX = X.T.values @ X.values; b = np.linalg.solve(XtX + 1e-9 * np.eye(len(xcols)), X.T.values @ Y.values); res = Y.values - X.values @ b
    dof = max(len(D) - D[group].nunique() - len(xcols), 1); cov = (res @ res / dof) * np.linalg.inv(XtX + 1e-9 * np.eye(len(xcols)))
    return dict(zip(xcols, zip(b, np.sqrt(np.diag(cov))))), len(D), int(D[group].nunique())
out = {}
ctrl = ["area", "top", "low", "new", "mid_age", "need"]
for nm, col in (("strict(올수리·샤시포함)", "strictf"), ("broad(+내부깔끔·완벽)", "broad")):
    if A[col].sum() < 5: out[nm] = {"메모": "수리 표시 호가가 5건 미만"}; continue
    res, n, ng = fe_ols(A, [col] + ctrl)
    b, se = res[col]; mean_ppm = float(A["ppm"].mean())
    out[nm] = {"호가 건수": n, "생활권(지도 화면) 수": ng, "수리 표시 건수": int(A.loc[A.index.isin(A.index), col].sum()), "수리 표시 효과(㎡당 가격 %)": round((np.exp(b) - 1) * 100, 1), "표준오차(로그)": round(float(se), 3), "95% 범위 %": [round((np.exp(b - 1.96 * se) - 1) * 100, 1), round((np.exp(b + 1.96 * se) - 1) * 100, 1)],
               "평균 ㎡당 가격(만원)": round(mean_ppm, 1), "㎡당 프리미엄 환산(만원)": round(mean_ppm * (np.exp(b) - 1), 1), "36㎡ 환산 프리미엄(만원)": round(36 * mean_ppm * (np.exp(b) - 1)), "수리 필요 표시 효과 %": round((np.exp(res['need'][0]) - 1) * 100, 1)}
out["참고: 앱 수리비 가정"] = "현대그린빌라(36㎡) 1,635만원 = ㎡당 약 45만원(effRepairFee 연식 기준) - 같은 단위로 비교"
print(json.dumps(out, ensure_ascii=False, indent=1)); json.dump(out, open("renovation-premium.json", "w"), ensure_ascii=False, indent=1)
