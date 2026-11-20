"""빌라 저층 호가 국토부 공시 목록에 없는 사건 → 건축물대장 전유부에서 그 호의 용도(주거/근생) 확인(읽기만 함)."""
import json, os, re, requests, collections, time
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
cases = json.load(open("data/diag-villa-lowfloor.json", encoding="utf-8"))
dg = lambda x: re.sub(r"\D", "", str(x or ""))
cnt = collections.Counter(); out = []
for c in cases:
    p = c["pnu"]
    try:
        r = requests.get(SITE + "/api/get-building", params={"sigunguCd": p[:5], "bjdongCd": p[5:10], "bun": p[11:15], "ji": p[15:19], "platGbCd": "0" if p[10] == "1" else "1"}, timeout=90).json()
    except Exception as e:
        cnt["조회 실패"] += 1; out.append({**c, "res": "err " + str(e)[:60]}); continue
    ex = r.get("exposAreas") or []
    if r.get("quotaExceeded"): cnt["건축HUB 한도 초과"] += 1; out.append({**c, "res": "quota"}); continue
    ho = dg(c["unit"]).lstrip("0")
    hit = [e for e in ex if dg(e.get("hoNm")).lstrip("0") == ho and (e.get("esUseNm") or "").find("전유") >= 0] or [e for e in ex if dg(e.get("hoNm")).lstrip("0") == ho]
    if not ex: k = "전유부 자료 없음"
    elif not hit: k = "전유부에 그 호 없음"
    else:
        pu = " ".join(sorted({str(e.get("mainPurps")) for e in hit}))
        k = "근생 등 비주거" if re.search(r"근린|상가|사무|판매|점포", pu) else ("주거(다세대·다가구 등)" if re.search(r"다세대|연립|공동주택|아파트|주택|다가구", pu) else "용도 기타:" + pu[:20])
    cnt[k] += 1; out.append({**c, "res": k, "purps": [e.get("mainPurps") for e in (hit or [])][:2], "n_expos": len(ex)})
    time.sleep(0.2)
print(cnt, flush=True)
for o in out: print(json.dumps(o, ensure_ascii=False)[:300], flush=True)
json.dump(out, open("diag-lowfloor.json", "w"), ensure_ascii=False)
