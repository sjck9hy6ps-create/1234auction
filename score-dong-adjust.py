"""
🏢 동(棟) 보정 경매 후보 채점 (2026-11-09, analyze-dong-effect.py 후속)
앱 예상매도가(채점 사례 rows.json의 saleFinal)에 '같은 동 이전 거래 가격 차이'를 곱했을 때 맞히는 정도가 좋아지는지 후보(go) 기준으로 확인(측정만, 앱·서버 값 변경 없음).
 - 동 효과 = 그 사례 입찰 기준일(cutoff) 이전 24개월, 같은 단지·같은 동·같은 평형(±3㎡) 거래의 잔차 평균 × m/(m+k) (잔차 = 거래가 ÷ 그 시점 직전 6개월 같은 단지·평형 중위값)
 - k·기울기 b는 2025년 이전 거래로만 맞춤(채점 사례보다 앞선 자료만 사용)
 - 정답 두 가지: ① 단지 전체 정답(기존 mkt) ② 같은 동 정답(낙찰 뒤 6개월 같은 동 거래 중위값) - 내 물건이 팔리는 값은 ②에 가까움
입력: 환경변수 ROWS_DIR(rows.json 들어 있는 폴더), SITE_URL. 출력: dong-adjust.json
"""
import os, json, re, glob, importlib.util
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("avm", os.path.join(HERE, "train-avm.py"))
avm = importlib.util.module_from_spec(_s); _s.loader.exec_module(avm)
_s2 = importlib.util.spec_from_file_location("abc", os.path.join(HERE, "analyze-bidcases.py"))
abc = importlib.util.module_from_spec(_s2); _s2.loader.exec_module(abc)

FIT_UNTIL = 20250101


def to_days(d):
    d = np.asarray(d, dtype=np.int64)
    return (d // 10000 - 2000) * 372 + ((d // 100) % 100 - 1) * 31 + (d % 100 - 1)


def case_adong(c):
    ad = c.get("aptDong")
    if isinstance(ad, str) and ad.strip().isdigit(): return str(int(ad.strip()))
    txt = str(c.get("addrJibun") or ""); b = str(c.get("bunji") or "")
    tail = txt.split(b, 1)[1] if b and b in txt else txt
    for t in (tail, str(c.get("unitNo") or "")):
        m = re.search(r"(\d{1,4})\s*동(?![가-힣])", t)
        if m: return str(int(m.group(1)))
    return None


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,size,price,deal_date,dealing_type,cdeal_type,apt_dong", extra_filter="&deal_date=gte.20230101")
    df = raw[raw["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    df = df[df["dealing_type"].fillna("") != "직거래"]
    for c in ("size", "price", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["size", "price", "deal_date"])
    df = df[(df["price"] > 0) & (df["size"] >= 20) & (df["size"] <= 250)]
    df["adong"] = df["apt_dong"].map(lambda v: (str(int(re.search(r"(\d{1,4})", str(v)).group(1))) if re.search(r"(\d{1,4})", str(v or "")) else ""))
    df["unit"] = df["region"].astype(str) + "|" + df["dong"].astype(str) + "|" + df["bunji"].astype(str) + "|" + df["danji"].astype(str) + "|" + (df["size"] / 3).round().astype(int).astype(str)
    df["day"] = to_days(df["deal_date"].astype(int).values); df["lp"] = np.log(df["price"].values)
    df = df.sort_values(["unit", "day"]).reset_index(drop=True)
    res = np.full(len(df), np.nan)
    days = df["day"].values; lp = df["lp"].values
    for u, idx in df.groupby("unit", sort=False).indices.items():
        if len(idx) < 4: continue
        dd = days[idx]; ll = lp[idx]
        for k in range(len(idx)):
            lo = np.searchsorted(dd, dd[k] - 180, side="left"); hi = np.searchsorted(dd, dd[k], side="left")
            if hi - lo >= 3: res[idx[k]] = ll[k] - np.median(ll[lo:hi])
    df["r"] = res
    K = df[df["adong"] != ""].copy()
    K["region_n"] = K["region"].map(abc.region_norm); K["dk"] = K["dong"].map(abc.dong_key); K["bj"] = K["bunji"].astype(str).str.strip()
    K["ck"] = K["region_n"].astype(str) + "|" + K["dk"] + "|" + K["bj"] + "|" + K["adong"]
    print(f"동 정보 거래 {len(K):,}건, 잔차 있음 {int(K['r'].notna().sum()):,}")
    # k, b - 2025년 이전 거래로만
    F = K[np.isfinite(K["r"]) & (K["r"].abs() < 0.5) & (K["deal_date"] < FIT_UNTIL)].copy()
    F["unitd"] = F["unit"] + "|" + F["adong"]
    e = np.full(len(F), np.nan); mc = np.zeros(len(F))
    dd_all = F["day"].values; r_all = F["r"].values
    for kk, idx in F.groupby("unitd", sort=False).indices.items():
        if len(idx) < 2: continue
        o = np.argsort(dd_all[idx]); idx = idx[o]; dd = dd_all[idx]; rr = r_all[idx]
        for j in range(1, len(idx)):
            lo = np.searchsorted(dd, dd[j] - 730, side="left"); hi = np.searchsorted(dd, dd[j], side="left")
            if hi - lo >= 1: e[idx[j]] = rr[lo:hi].mean(); mc[idx[j]] = hi - lo
    F["e"] = e; F["m"] = mc; F = F[np.isfinite(F["e"])]
    gm = F.groupby("unitd")["r"].agg(["mean", "var", "size"]).dropna(); gm = gm[gm["size"] >= 3]
    within = float(gm["var"].median()); between = float(max(gm["mean"].var() - within / gm["size"].median(), 1e-6)); k = within / between
    es_f = F["e"] * F["m"] / (F["m"] + k)
    b = float((es_f * F["r"]).sum() / max((es_f ** 2).sum(), 1e-9))
    print(f"k={k:.2f} b={b:.3f} (맞춘 거래 {len(F):,}건, ~2024)")

    # 사례
    cases = {c["id"]: c for c in requests.get(os.environ.get("SITE_URL", "https://1234auction.vercel.app") + "/api/auction?kind=bidCases", timeout=180).json() if isinstance(c, dict) and c.get("id")}
    rows = []
    for f in glob.glob(os.path.join(os.environ.get("ROWS_DIR", "."), "**", "rows.json"), recursive=True): rows += json.load(open(f))
    groups = {kk: g for kk, g in K[np.isfinite(K["r"]) & (K["r"].abs() < 0.5)].groupby("ck")}
    groups_all = {kk: g for kk, g in K.groupby("ck")}
    out_rows = []
    for r in rows:
        if r.get("err") or not r.get("saleFinal") or not r.get("mkt"): continue
        c = cases.get(r["id"])
        if not c: continue
        ad = case_adong(c)
        item = {"id": r["id"], "date": r["saleDate"], "go": bool(r.get("go")), "cls": "서울" if str(r["lawd"]).startswith("11") else ("경기·인천" if str(r["lawd"])[:2] in ("41", "28") else "지방"),
                "est": r["saleFinal"], "mkt": r["mkt"], "mktN": r["mktN"], "act": r["act"], "rec": r.get("rec"), "margin": r.get("margin"), "marginRaw": r.get("marginRaw"), "n6": r.get("n6"), "hasDong": ad is not None}
        if ad is not None:
            ck = f"{abc.region_norm(c.get('addrJibun'))}|{abc.dong_key(c.get('dong'))}|{str(c.get('bunji') or '').strip()}|{ad}"
            area = float(c.get("areaM2") or 0)
            cut = to_days([int(str(r["cutoff"]).replace("-", ""))])[0]; sale = to_days([int(str(r["saleDate"]).replace("-", ""))])[0]
            g = groups.get(ck)
            if g is not None and area:
                gg = g[(abs(g["size"].values - area) <= 3) & (g["day"].values < cut) & (g["day"].values >= cut - 730)]
                if len(gg) >= 1:
                    m = len(gg); item["es"] = float(gg["r"].mean() * m / (m + k)); item["m"] = m
            g2 = groups_all.get(ck)
            if g2 is not None and area:
                later = g2[(abs(g2["size"].values - area) <= 3) & (g2["day"].values >= sale) & (g2["day"].values <= sale + 183)]
                if len(later) >= 1: item["dongTruth"] = float(np.median(later["price"].values)); item["dongTruthN"] = len(later)
        out_rows.append(item)
    O = pd.DataFrame(out_rows)
    O["adj"] = O["est"] * np.exp(b * O["es"].fillna(0))
    print(f"채점 사례 {len(O):,}건, 동 번호 있음 {int(O['hasDong'].sum()):,}, 동 효과 추정 {int(O['es'].notna().sum()):,}, 같은 동 정답 {int(O['dongTruth'].notna().sum()) if 'dongTruth' in O else 0}")

    def acc(S, truth):
        S = S[S[truth].notna()]
        if len(S) < 30: return {"n": int(len(S))}
        e0 = S["est"] / S[truth] - 1; e1 = S["adj"] / S[truth] - 1
        return {"n": int(len(S)), "보정전_중앙오차%": round(float(e0.abs().median()) * 100, 2), "보정후_중앙오차%": round(float(e1.abs().median()) * 100, 2),
                "보정전_10%+높음%": round(float((e0 > 0.10).mean()) * 100, 1), "보정후_10%+높음%": round(float((e1 > 0.10).mean()) * 100, 1),
                "보정전_하위10%": round(float(np.quantile(-e0, 0.1)) * 100, 1), "보정후_하위10%": round(float(np.quantile(-e1, 0.1)) * 100, 1)}
    out = {"k": round(k, 2), "b": round(b, 3), "n": int(len(O))}
    G = O[O["go"] & O["es"].notna()]
    out["후보·동효과있음_같은동정답"] = acc(G, "dongTruth")
    out["후보·동효과있음_단지정답(참고)"] = acc(G[G["mktN"] >= 3], "mkt")
    out["후보·동효과있음_같은동정답_권역별"] = {c: acc(G[G["cls"] == c], "dongTruth") for c in ("서울", "경기·인천", "지방")}
    big = G["es"].abs(); q = big.quantile(.8) if len(G) else 0
    out["후보·동효과큼(상위20%)_같은동정답"] = acc(G[big >= q], "dongTruth")
    out["후보 전체(동 번호 없는 것 포함) 중 동 효과 추정 가능 비율%"] = round(float(O[O["go"]]["es"].notna().mean()) * 100, 1) if O["go"].any() else None

    # 선택 시뮬레이션(학습 안 쓴 2025-10-30 이후): 예상매도가가 Δ만큼 바뀌면 추천가·예상마진도 같은 폭만큼 이동한다고 근사 - 낙찰 여부·실현 수익은 실제 낙찰가·같은 동 정답으로
    S = O[(O["date"] >= "2025-10-30") & O["go"] & O["rec"].notna() & O["margin"].notna() & O["dongTruth"].notna()].copy()
    S["d"] = S["adj"] - S["est"]
    def sim(use_adj):
        d = S["d"] if use_adj else 0 * S["d"]
        rec = S["rec"] + d; mar = S["margin"] + d
        won = (rec >= S["act"]) & (mar >= 500)   # 최소 순이익 500만 (앱 기준)
        net = (S["marginRaw"].fillna(S["margin"]) + (S["dongTruth"] - S["est"]))[won] if won.any() else pd.Series(dtype=float)
        return {"후보수": int(((mar >= 500)).sum()), "추천가낙찰": int(won.sum()), "손해건": int((net < 0).sum()), "손해%": round(float((net < 0).mean()) * 100, 1) if len(net) else None, "실현합계(만원)": int(net.sum()) if len(net) else 0}
    out["선택시뮬레이션_2025-10-30이후_같은동정답"] = {"현재": sim(False), "동보정": sim(True)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("dong-adjust.json", "w"), ensure_ascii=False)
    O.to_json("dong-adjust-rows.json", orient="records", force_ascii=False)


if __name__ == "__main__":
    main()
