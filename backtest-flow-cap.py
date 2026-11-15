"""🧪 상한 규칙 시험(2026-11-15, 사용자: 시세 흐름 상향 보정이 지나치게 높은 단지 - 경매 단타는 현재 시점 시세가 가장 중요)
질문: '지역 흐름으로 더하는 상향 보정'을 최근 실거래(현재 시세)보다 얼마 이상 못 올라가게 막으면 예상매도가가 더 맞는가?
방법: 흐름 연구실(analyze-flow-lab.py)과 같은 자료·같은 대상 거래(2025-01 이후 약 4만 건, 30일 전 기준 6개월 같은 평형 거래 3건+)로
  현재 앱 방식(최근 가중 중위값 × 흐름 보정, 범위 0.95~1.08, 계수 수도권 2.0·지방 0.6)을 기준선으로 두고,
  상한 규칙 = 예상값이 기준 가격 × (1+u)를 넘지 못하게. 기준 가격: ① 보정 전 가중 중위값(b0) ② 최근 3개월 거래 중위값(r3) ③ 가장 최근 거래(last) / u: 0·2·4·6%.
  거래량 규칙 = 가격은 오르는데 거래량이 급감(vol < -0.5)하면 흐름 보정을 반으로/0으로.
평가: 수도권 전체 · '상향 보정이 5% 넘는 구간' · '오르는데 거래량 급감 구간' 에서 보통 오차·쏠림·10% 넘게 높게(손해 쪽)·낮게 맞춘 비율·손해 가중 오차(높게 맞추면 2배).
※ 앱의 3개월 뒤 예측·종합 평가 보정은 포함하지 않은 '흐름 보정 단계'만의 시험. 결과는 로그·flow-cap-report.json 으로만 남김(서버·앱 저장 없음).
"""
import os, json, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "analyze-flow-lab.py"), encoding="utf-8").read()
i = src.index("def backtest_coeff():")
exec(compile(src[:i], "analyze-flow-lab(prefix)", "exec"), globals())          # 자료 불러오기·흐름 표 만들기까지만
fn_src = src[i: src.index('try:\n    REPORT["coeff"] = backtest_coeff()')]
j = fn_src.index('    log(f"보정계수 점검 대상'); j = fn_src.index("\n", j) + 1
exec(fn_src[:j].replace("def backtest_coeff():", "def build_recs():") + "    return recs\n", globals())   # 대상 거래 목록만 재사용
recs = build_recs()
log(f"시험 대상 {len(recs):,}건")


def est_base(prices, ages, cls):
    w = 0.5 ** (ages / (1.0 if cls == "수도권" else 2.0)); o = np.argsort(prices); pp, ww = prices[o], w[o]
    c_ = (np.cumsum(ww) - 0.5 * ww) / ww.sum(); return float(np.interp(0.5, c_, pp))
def flow_at(level, cm, ci, di, si):
    if level == "radius": P, V, Nn = P3[ci], VAR3[ci], N3[ci]
    elif level == "dong": P, V, Nn = dP3[di], dVAR3[di], dN3[di]
    else: P, V, Nn = sP3[si], sVAR3[si], sN3[si]
    a, b = P[cm], P[cm - 3]
    if not (np.isfinite(a) and np.isfinite(b)): return None
    na, nb = Nn[cm], Nn[cm - 3]
    se = math.sqrt(max(V[cm], 1e-6) / max(na, 1) + max(V[cm - 3], 1e-6) / max(nb, 1)) if np.isfinite(V[cm]) and np.isfinite(V[cm - 3]) else 0.05
    return {"rate": (a - b) / 0.25, "z": (a - b) / max(se, 0.003), "vol": math.log((na + 1) / (nb + 1))}
COEF = {"수도권": 2.0, "지방": 0.6}
def app_flow(cls, cm, ci, di, si):
    for lv in (("radius", "dong", "sgg") if cls == "수도권" else ("sgg",)):
        f = flow_at(lv, cm, ci, di, si)
        if f is not None and abs(f["z"]) >= 1.0: return f
    return None
def adj_of(cls, f, scale=1.0):
    if f is None: return 1.0
    raw = math.exp(COEF[cls] * f["rate"] * (0.15 if cls == "수도권" else 0.30)); a = float(np.clip(raw, 0.95, 1.08))
    return 1.0 + (a - 1.0) * scale

rows = []
for (price, cls, prices, ages, cm, ci, gi, di, si) in recs:
    b0 = est_base(prices, ages, cls); f = app_flow(cls, cm, ci, di, si); adj = adj_of(cls, f)
    m3 = prices[ages <= 3.0]; r3 = float(np.median(m3)) if len(m3) >= 2 else b0
    last = float(prices[int(np.argmin(ages))])
    rows.append({"cls": cls, "price": float(price), "b0": b0, "adj": adj, "r3": r3, "last": last, "rate": f["rate"] if f else 0.0, "vol": f["vol"] if f else 0.0, "has": f is not None})

def metrics(R, pred_fn):
    if len(R) < 30: return None
    e = np.array([math.log(pred_fn(r) / r["price"]) for r in R])
    return {"n": int(len(R)), "medAbs%": round(float(np.median(np.abs(e))) * 100, 2), "bias%": round(float(np.median(e)) * 100, 2),
            "높게10%+": round(float((e > math.log(1.10)).mean()) * 100, 1), "낮게10%+": round(float((e < -math.log(1.10)).mean()) * 100, 1),
            "손해가중오차%": round(float(np.mean(np.where(e > 0, 2 * e, -e))) * 100, 2)}

variants = {"보정 없음(가중 중위값)": lambda r: r["b0"], "현재 방식(흐름 보정)": lambda r: r["b0"] * r["adj"]}
for an in ("b0", "r3", "last"):
    for u in (0.0, 0.02, 0.04, 0.06):
        variants[f"상한 {an}×(1+{int(u*100)}%)"] = (lambda an_, u_: (lambda r: min(r["b0"] * r["adj"], r[an_] * (1 + u_))))(an, u)
variants["거래량 급감 시 흐름 반으로"] = lambda r: r["b0"] * (1 + (r["adj"] - 1) * (0.5 if (r["rate"] > 0 and r["vol"] < -0.5) else 1.0))
variants["거래량 급감 시 흐름 0"] = lambda r: r["b0"] * (1.0 if (r["rate"] > 0 and r["vol"] < -0.5) else r["adj"])
def _vol0(r): return r["rate"] > 0 and r["vol"] < -0.5
for u in (0.03, 0.04, 0.05):
    variants[f"[조합] 거래량 급감 시 흐름 0 + 상한 b0×(1+{int(u*100)}%)"] = (lambda u_: (lambda r: min(r["b0"] * (1.0 if _vol0(r) else r["adj"]), r["b0"] * (1 + u_))))(u)
    variants[f"[조합] 거래량 급감 시 흐름 반 + 상한 b0×(1+{int(u*100)}%)"] = (lambda u_: (lambda r: min(r["b0"] * (1 + (r["adj"] - 1) * (0.5 if _vol0(r) else 1.0)), r["b0"] * (1 + u_))))(u)
variants["상한 b0×(1+3%)"] = lambda r: min(r["b0"] * r["adj"], r["b0"] * 1.03)
variants["상한 b0×(1+5%)"] = lambda r: min(r["b0"] * r["adj"], r["b0"] * 1.05)
# 2026-11-15 하향 규칙 시험(창원 성산구: 시군구 가격 연 -51.6% → -5% 보정이 단지 흐름(+2.5%)과 반대로 걸림)
variants["하락 흐름 반으로"] = lambda r: r["b0"] * (1 + (r["adj"] - 1) * (0.5 if r["adj"] < 1 else 1.0))
variants["하락 흐름 0(내리는 쪽 보정 안 함)"] = lambda r: r["b0"] * (1.0 if r["adj"] < 1 else r["adj"])
variants["하락 하한 -2%"] = lambda r: r["b0"] * max(r["adj"], 0.98)
variants["하락 하한 -3%"] = lambda r: r["b0"] * max(r["adj"], 0.97)
variants["최근 3개월 중위값만"] = lambda r: r["r3"]
variants["가장 최근 거래만"] = lambda r: r["last"]

groups = {"수도권 전체": lambda r: r["cls"] == "수도권", "수도권·상향 5%+ 구간": lambda r: r["cls"] == "수도권" and r["adj"] >= 1.05,
          "수도권·오르는데 거래량 급감": lambda r: r["cls"] == "수도권" and r["rate"] > 0 and r["vol"] < -0.5, "지방 전체": lambda r: r["cls"] == "지방", "지방·하향 보정 3%+": lambda r: r["cls"] == "지방" and r["adj"] <= 0.97, "지방·하향 보정 상한(-5%)": lambda r: r["cls"] == "지방" and r["adj"] <= 0.951, "수도권·하향 보정 3%+": lambda r: r["cls"] == "수도권" and r["adj"] <= 0.97, "지방·상향 3%+": lambda r: r["cls"] == "지방" and r["adj"] >= 1.03, "전체": lambda r: True}
OUT = {"n": len(rows), "groups": {}}
for gname, gf in groups.items():
    R = [r for r in rows if gf(r)]
    OUT["groups"][gname] = {"n": len(R), "variants": {vn: metrics(R, vf) for vn, vf in variants.items()}}
    log(f"── {gname} ({len(R):,}건)")
    for vn in variants:
        m = OUT["groups"][gname]["variants"][vn]
        if m: log(f"   {vn:<28} 보통오차 {m['medAbs%']:5.2f}% 쏠림 {m['bias%']:+5.2f}% 높게10%+ {m['높게10%+']:4.1f}% 낮게10%+ {m['낮게10%+']:4.1f}% 손해가중 {m['손해가중오차%']:5.2f}%")
json.dump(OUT, open("flow-cap-report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
