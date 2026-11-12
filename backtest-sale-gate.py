"""예상매도가 '보정 선택 적용' 검증 (2026-11-12, 사용자: 보정을 끄지 말고 원칙 안에서 선택적으로 적용)
backtest-sale-rule.json(직전 정보만으로 만든 예상 vs 실제 다음 거래)에서, 회전율 구간별 치우침 표(보정)를 상향일 때만 단지 흐름(trd)으로 걸러 적용하는 규칙들을 비교.
표는 한 구간에서 만들고 다른 구간에서 시험(앞↔뒤 교차) - 같은 자료로 만들고 같은 자료로 채점하지 않음."""
import json, numpy as np, pandas as pd
D = pd.DataFrame(json.load(open("backtest-sale-rule.json", encoding="utf-8")))
MAIN = {"서울": "e_최근3건중위", "경기·인천": "e_최근가중(반감1m)중위", "지방": "e_최근가중(반감2m)중위"}
D["base"] = [D.loc[i, MAIN[D.loc[i, "cls"]]] for i in D.index]
D = D[D.base.notna() & D.hh.notna() & (D.hh > 0)].copy()
D["turn"] = D.tr12 / D.hh * 100
qs = D.turn.quantile([1 / 3, 2 / 3]).values
D["tb"] = pd.cut(D.turn, [-1, qs[0], qs[1], 1e9], labels=["낮음", "중간", "높음"]).astype(str)
tmid = D.t.median(); D["half"] = (D.t >= tmid).astype(int)
def table(tr):
    out = {}
    for (c, b), g in tr.groupby(["cls", "tb"]):
        if len(g) >= 200: out[(c, b)] = float(np.median(g.actual / g.base) - 1)
    return out
CAPS = {"최근6개월 최고가": "mx6", "최근6개월 2번째 높은 가": "top2"}
RULES = {
 "보정 없음": lambda b, t: 0.0,
 "보정 항상": lambda b, t: b,
 "내림만(올리는 보정 끔)": lambda b, t: min(b, 0.0),
 "올림은 흐름 ≥ 0%일 때만": lambda b, t: b if (b <= 0 or (t == t and t >= 0)) else 0.0,
 "올림은 흐름 ≥ +3%일 때만": lambda b, t: b if (b <= 0 or (t == t and t >= 3)) else 0.0,
 "올림은 흐름 > −3%(하락 아닐 때)": lambda b, t: b if (b <= 0 or (t == t and t > -3)) else 0.0,
}
def stat(r):
    return dict(n=len(r), 오차=round(float(np.median(np.abs(r - 1))) * 100, 3), 치우침=round(float(np.median(r) - 1) * 100, 2), 예상높음10=round(float((r < 0.9).mean()) * 100, 2), 예상높음5=round(float((r < 0.95).mean()) * 100, 2), 예상높음3=round(float((r < 0.97).mean()) * 100, 2))
res = {}
for scope in ("전체", "서울", "경기·인천", "지방"):
    res[scope] = {}
    for name, f in RULES.items():
        rs = []
        for h in (0, 1):  # h구간으로 시험, 반대 구간으로 표 작성
            tr, te = D[D.half != h], D[D.half == h]
            if scope != "전체": te = te[te.cls == scope]
            tab = table(tr)
            fac = []
            for c, b, t in zip(te.cls, te.tb, te.trd):
                bias = tab.get((c, b), 0.0)
                bias = max(-0.03, min(0.03, bias))
                fac.append(1 + f(bias, t))
            est = te.base.values * np.array(fac)
            rs.append(pd.Series(te.actual.values / est))
        r = pd.concat(rs)
        res[scope][name] = stat(r)
    print(f"\n==== [{scope}] ====")
    for k, v in res[scope].items(): print(f"  {k:<28}", v)
# 상향 적용을 받는 물건만 따로(보정 항상 기준 상향 대상): 규칙별 예상 대비 실제
print("\n==== 상향 보정 대상 물건만 ====")
sub = {}
for name, f in RULES.items():
    rs = []
    for h in (0, 1):
        tr, te = D[D.half != h], D[D.half == h]; tab = table(tr); fac = []; up = []
        for c, b, t in zip(te.cls, te.tb, te.trd):
            bias = max(-0.03, min(0.03, tab.get((c, b), 0.0))); fac.append(1 + f(bias, t)); up.append(bias > 0)
        up = np.array(up); est = te.base.values * np.array(fac)
        rs.append(pd.Series((te.actual.values / est)[up]))
    sub[name] = stat(pd.concat(rs)); print(f"  {k if False else name:<28}", sub[name])
# 흐름 구간별 상향 보정의 효과
print("\n==== 흐름 구간별: 상향 대상 물건의 치우침(보정 없음 기준) ====")
for lo, hi, lab in ((-999, -3, "하락"), (-3, 0, "보합(−3~0)"), (0, 3, "보합(0~3)"), (3, 999, "상승 +3%↑")):
    rs = []
    for h in (0, 1):
        tr, te = D[D.half != h], D[D.half == h]; tab = table(tr)
        m = [(max(-0.03, min(0.03, tab.get((c, b), 0.0))) > 0) and (t == t and lo < t <= hi) for c, b, t in zip(te.cls, te.tb, te.trd)]
        te = te[np.array(m)]; rs.append(te.actual / te.base)
    r = pd.concat(rs)
    print(f"  {lab:<12} n{len(r):>6} 치우침 {(np.median(r)-1)*100:+.2f}%  (+면 실제가 예상보다 비쌈 → 올려야 맞음)")
na = []
for h in (0, 1):
    tr, te = D[D.half != h], D[D.half == h]; tab = table(tr)
    m = [(max(-0.03, min(0.03, tab.get((c, b), 0.0))) > 0) and not (t == t) for c, b, t in zip(te.cls, te.tb, te.trd)]
    na.append((te[np.array(m)].actual / te[np.array(m)].base))
r = pd.concat(na); print(f"  흐름 계산 불가 n{len(r):>6} 치우침 {(np.median(r)-1)*100:+.2f}%")
import os
if os.environ.get("GITHUB_STEP_SUMMARY"):
    open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 보정 선택 적용 검증\n```json\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n```\n")

print("\n==== 보정은 유지하되, 예상매도가가 '같은 평형 최근 6개월에 실제로 있었던 가격'을 넘지 못하게 막으면? ====")
for scope in ("전체", "서울", "경기·인천", "지방"):
    print(f"[{scope}]")
    for capname, col in CAPS.items():
        for rname in ("보정 항상",):
            rs = []; hit = []
            for h in (0, 1):
                tr, te = D[D.half != h], D[D.half == h]
                if scope != "전체": te = te[te.cls == scope]
                tab = table(tr)
                fac = np.array([1 + max(-0.03, min(0.03, tab.get((c, b), 0.0))) for c, b in zip(te.cls, te.tb)])
                est0 = te.base.values * fac; est = np.minimum(est0, te[col].values); hit.append((est < est0 - 1).mean())
                rs.append(pd.Series(te.actual.values / est))
            print(f"  보정+상한({capname:<14})", stat(pd.concat(rs)), "상한에 걸린 비율", round(float(np.mean(hit)) * 100, 1), "%")
# 거래 수·변동성별 상향 보정 효과
print("\n==== 6개월 거래 수별: 상향 대상 물건의 치우침(보정 없음 기준) ====")
for lo, hi in ((3, 5), (5, 10), (10, 20), (20, 999)):
    rs = []
    for h in (0, 1):
        tr, te = D[D.half != h], D[D.half == h]; tab = table(tr)
        m = np.array([max(-0.03, min(0.03, tab.get((c, b), 0.0))) > 0 for c, b in zip(te.cls, te.tb)]) & (te.n6.values >= lo) & (te.n6.values < hi)
        rs.append(te[m].actual / te[m].base)
    r = pd.concat(rs); print(f"  6개월 {lo}~{hi-1}건 n{len(r):>6} 치우침 {(np.median(r)-1)*100:+.2f}%")
