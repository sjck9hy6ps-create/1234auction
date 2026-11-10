"""
🏘️ 빌라 추천가·예상낙찰가 실제 결과 채점 (2026-11-10, 사용자: 빌라 결과 채점해줘)
앱이 입찰 전에 저장한 빌라 예측(predSnap: 예상매도가 sale·추천가 recBid·예상낙찰가 win·낙찰 가능성 prob)을, 입찰 후 올라온 낙찰사례(bidCases, 상태 '매각')와 사건번호·법정동·저장일 이후 입찰일로 맞춰 채점한다.
빌라 예측 저장은 2026-11-08부터(그 전엔 저장 버그) - 결과가 올라오면(입찰 결과 CSV 업로드) 이 도구를 돌리면 됨. 사용: python3 scripts/score-villa-predictions.py [SITE_URL]
채점: 예상낙찰가 오차(중앙·쏠림·±10%), 추천가로 낙찰됐을 비율, 낙찰가÷추천가 중앙, 낙찰 가능성 구간별 예측 vs 실제, 시세 근거 단계별.
"""
import sys, re, json, statistics as st, collections, requests
SITE = sys.argv[1] if len(sys.argv) > 1 else "https://1234auction.vercel.app"
nc = lambda c: re.sub(r"타경\s*", "-", str(c)).replace(" ", "")


def main():
    au = requests.get(SITE + "/api/auction", timeout=180).json(); bc = requests.get(SITE + "/api/auction?kind=bidCases", timeout=180).json()
    V = [x for x in au if isinstance(x, dict) and x.get("propType") == "villa" and not x.get("isBacktest") and x.get("predSnap")]
    sold = collections.defaultdict(list)
    for c in bc:
        if c.get("status") == "매각" and c.get("finalBidPrice") and re.search("다세대|연립|빌라|도시형", str(c.get("propertyType"))): sold[nc(c.get("caseNo"))].append(c)
    rows = []
    for x in V:
        ps = x["predSnap"]
        cands = [c for c in sold.get(nc(x.get("caseNo")), []) if str(c.get("dong")) == str(x.get("dong")) and str(c.get("saleDate")) >= str(ps.get("at"))]
        if not cands: continue
        c = cands[0]; ap = float(x.get("appraisal") or 0) * 1e4; ca = float(c.get("appraisalPrice") or 0)
        if ap and ca and abs(ap / ca - 1) > 0.05: continue   # 같은 사건번호의 다른 물건이 섞이지 않게
        rows.append({"sale": ps.get("sale"), "rec": ps.get("recBid"), "win": ps.get("win"), "prob": ps.get("prob"), "final": c["finalBidPrice"] / 1e4, "bidders": c.get("bidders"), "lvl": ps.get("lvl"), "date": c.get("saleDate")})
    print(f"예측 저장 빌라 {len(V):,}건 중 결과와 맞춰진 건 {len(rows):,}건")
    if len(rows) < 20:
        print("표본이 적어(20건 미만) 채점하지 않음 - 입찰 결과가 올라온 뒤 다시 실행하세요"); return
    W = [r for r in rows if r["win"] and r["final"]]
    e = [r["win"] / r["final"] - 1 for r in W]
    print(f"예상 낙찰가: n={len(W)} 중앙 오차 {st.median(abs(x) for x in e) * 100:.1f}% 쏠림 {st.median(e) * 100:+.1f}% ±10% {100 * sum(abs(x) <= .1 for x in e) / len(e):.1f}%")
    R = [r for r in rows if r["rec"]]
    won = [r for r in R if r["final"] <= r["rec"]]
    print(f"추천가: n={len(R)} 추천가로 낙찰 {100 * len(won) / len(R):.1f}% · 낙찰가÷추천가 중앙 {st.median(r['final'] / r['rec'] for r in R):.3f}")
    P = [r for r in R if r["prob"] is not None]
    for lo, hi in ((0, .1), (.1, .25), (.25, .5), (.5, 1.01)):
        G = [r for r in P if lo <= r["prob"] < hi]
        if len(G) >= 10: print(f"  낙찰 가능성 {int(lo * 100)}~{int(min(hi, 1) * 100)}% 예측: n={len(G)} 예측 {100 * st.mean(r['prob'] for r in G):.0f}% 실제 {100 * sum(r['final'] <= r['rec'] for r in G) / len(G):.0f}%")
    S = [r for r in rows if r["sale"] and r["final"]]
    print(f"낙찰가÷예상매도가 중앙 {st.median(r['final'] / r['sale'] for r in S):.3f} (n={len(S)})")


if __name__ == "__main__":
    main()
