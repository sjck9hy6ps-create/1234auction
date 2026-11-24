"""팔리는 곳 판정 기준이 자료가 쌓여도 같은 결과를 내는지 달마다 확인(2026-11-24, 사용자: "앞으로 자료가 쌓일 때도 같은 결과물이 나올 수 있을지").
backtest-liquidity-band.py가 만든 JSON을 기준값(scripts/data/liquidity-baseline.json, 2026-11-24 시험)과 비교한다.
 - 구간별 '이후 같은 평형(가격대) 거래 0건 비율'이 기준값에서 허용 폭(절대 %p) 넘게 벗어나면 경고
 - 순서(거래 많을수록·시세에 가까울수록 0건이 적다)가 뒤집히면 경고
 - 앱이 쓰는 문턱(아파트 12개월 5건·10건, 빌라 평형대 5건·10건, 인정 가격대 1.25배)이 여전히 뜻이 있는지 확인
경고가 있으면 종료 코드 1(GitHub이 알림 메일을 보냄) + 요약을 GITHUB_STEP_SUMMARY에 남긴다. 앱 규칙은 자동으로 바꾸지 않는다(사용자 승인 필요)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(HERE, "data", "liquidity-baseline.json")
cur = json.load(open(os.environ.get("BAND_JSON", "backtest-liquidity-band.json"), encoding="utf-8"))


def pick(o):
    v = o["빌라(평형대·가격대·아파트 경쟁)"]; a = o["아파트 단지 내 평형 인기"]
    w = v.get("12개월") or v.get("전체 시험구간"); wa = a["12개월"]
    out = {}
    for lab, d in (w["같은 평형대 12개월 거래(시세 1.0배)"]).items():
        if d: out["빌라 같은 평형 12개월 " + lab] = d["이후0건%"]
    for mu, d in (w["시세 대비 가격대별(같은 평형 12개월 거래가 중앙값 대비)"]).items():
        if d["같은평형 12개월 5건 이상"]: out["빌라 시세 " + mu + "(5건+)"] = d["같은평형 12개월 5건 이상"]["이후0건%"]
    for lab, tiers in wa["같은 거래 건수 안에서 등급별"].items():
        n = sum(t["행수"] for t in tiers.values()); out["아파트 같은 평형 12개월 " + lab.replace("12개월 ", "")] = round(sum(t["행수"] * t["이후 0건%"] for t in tiers.values()) / n, 1)
    return out


CHAINS = [["빌라 같은 평형 12개월 3~4건", "빌라 같은 평형 12개월 5~9건", "빌라 같은 평형 12개월 10건+"], ["빌라 시세 1.5배(5건+)", "빌라 시세 1.25배(5건+)", "빌라 시세 1.0배(5건+)"],
          ["아파트 같은 평형 12개월 2~4건", "아파트 같은 평형 12개월 5~9건", "아파트 같은 평형 12개월 10~19건", "아파트 같은 평형 12개월 20건+"]]
if os.environ.get("MAKE_BASELINE") == "1":   # 처음 기준값 만들 때만(2026-11-24)
    json.dump({"made": "2026-11-24", "note": "backtest-liquidity-band.py 12개월 구간 결과(이후 같은 평형 거래 0건 비율%)", "tolerance_pp": 8, "tolerance_small_pp": 4, "values": pick(cur), "order_chains": CHAINS}, open(BASE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("기준값 저장"); sys.exit(0)
base = json.load(open(BASE_PATH, encoding="utf-8"))
b, c = base["values"], pick(cur); msgs = []; bad = False
for k, bv in b.items():
    if k not in c: msgs.append(f"⚠️ {k}: 이번 시험에 표본이 부족해 비교 못 함"); continue
    tol = base["tolerance_pp"] if bv >= 10 else base["tolerance_small_pp"]
    d = c[k] - bv; flag = abs(d) > tol; bad = bad or flag
    msgs.append(f"{'🚨' if flag else '✅'} {k}: 기준 {bv}% → 이번 {c[k]}% ({d:+.1f}%p, 허용 ±{tol})")
for chain in base["order_chains"]:
    vals = [c.get(k) for k in chain]
    if any(v is None for v in vals): continue
    ok = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)); bad = bad or not ok
    msgs.append(f"{'✅' if ok else '🚨'} 순서 {' ≥ '.join(chain)}: {vals}")
txt = "## 팔리는 곳 판정 기준 점검\n" + "\n".join("- " + m for m in msgs) + ("\n\n**기준이 흔들렸어요 - 시험을 다시 보고 규칙을 점검해야 해요.**" if bad else "\n\n모든 구간이 기준값 안에 있어요.")
print(txt)
if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(txt + "\n")
sys.exit(1 if bad else 0)
