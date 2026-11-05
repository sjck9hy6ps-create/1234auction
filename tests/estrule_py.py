import numpy as np
from datetime import date,timedelta,datetime
def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def int_to_date(v):
    v = int(v)
    return datetime(v // 10000, (v // 100) % 100, v % 100)


def _wmed(v, w):
    o = np.argsort(v); v = np.asarray(v, dtype=float)[o]; w = np.asarray(w, dtype=float)[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(0.5, c, v))


FLOW_COEF = 1.5   # 흐름 반영 계수(2026-11-05 점검: 1.5~3에서 오차 최소·평탄, 0.6은 얻을 개선의 일부만)


def flow_gate_g(rate, vol):
    """거래량으로 가격 흐름 믿음을 조절하던 값 - 2026-11-05 점검에서 시세 보정에는 도움이 안 돼 쓰지 않음(항상 1)"""
    return 1.0


def est_rule_asof(g, c, sale_d, cut, cut_ym, idx_at, flow=None):
    """2026-10-20 앱의 새 예상매도가 규칙을 '입찰 30일 전 시점'으로 재현(사용자: 낙찰가 모델의 시세 기준을 새 규칙으로 바꾸면 오차가 줄까)
    6개월 같은 평형(±3㎡) 3건+ → 서울 최근3건 중위 / 경기·인천 반감1개월 / 지방 반감2개월 가중 중위. 부족하면 같은 평형 36개월(6개월 밖은 시군구 지수 보정, 반감3개월; 지방 최근 1건+는 12개월 원값),
    없으면 같은 단지 다른 평형 12개월 ㎡당 가격 환산. 같은 평형 이전 값과 다른 평형 값이 둘 다 있고 6개월 안 거래가 없으면 6:4. (층·회전율·전세 보정은 제외)"""
    area = float(c.area)
    cut_d = int_to_date(int(cut))
    h = g[(g["deal_date"] < cut) & ((g["size"] - area).abs() <= 3)]
    if len(h):
        age = np.array([(cut_d - int_to_date(int(x))).days / 30.4 for x in h["deal_date"].values])
    else:
        age = np.array([])
    price = h["price"].values.astype(float) if len(h) else np.array([])
    # 📈 지역 가격 흐름 반영(2026-11-05, 사용자: 모든 가격에 부동산 흐름 반영): 12개월 안 원값 거래를 거래 나이(년)×연율 흐름×계수(FLOW_COEF)로 지금 시점에 맞춤(-5%~+8%). flow=None이면 예전 값 그대로
    pf = price
    if flow is not None and len(price):
        _g = flow_gate_g(flow["rate"], flow.get("vol"))
        pf = price * np.where(age <= 12, np.clip(np.exp(FLOW_COEF * flow["rate"] * _g * age / 12.0), 0.95, 1.08), 1.0)
    sido = str(c.region).split(" ")[0]
    cls = "서울" if sido.startswith("서울") else ("경기·인천" if sido[:2] in ("경기", "인천") else "지방")
    m6 = age <= 6; n6 = int(m6.sum())
    if n6 >= 3:
        p6, a6 = pf[m6], age[m6]
        if cls == "서울": return float(np.median(p6[np.argsort(a6)[:3]]))
        return _wmed(p6, 0.5 ** (a6 / (1.0 if cls == "경기·인천" else 2.0)))
    base = idx_at(c.region, cut_ym)
    t2 = None
    m36 = age <= 36
    if m36.any():
        if cls == "지방" and n6 >= 1:
            m12 = age <= 12
            t2 = _wmed(pf[m12], 0.5 ** (age[m12] / 3.0))
        else:
            vals, ws = [], []
            for pr, ag, ym, pfv in zip(price[m36], age[m36], h["ym"].values[m36], pf[m36]):
                v = pfv
                if ag > 6:
                    v = pr
                    b0 = idx_at(c.region, int(ym))
                    if not (base and b0): continue
                    v = pr * max(0.7, min(1.4, base / b0))
                vals.append(v); ws.append(0.5 ** (ag / 3.0))
            if vals: t2 = _wmed(vals, ws)
    o = g[(g["deal_date"] < cut) & ((g["size"] - area).abs() > 3)]
    t3 = None
    if len(o) and base:
        oa = np.array([(cut_d - int_to_date(int(x))).days / 30.4 for x in o["deal_date"].values]); k12 = oa <= 12
        if k12.sum() >= 2:
            pp, sz = [], []
            for ppm, ym, z in zip(o["ppm"].values[k12], o["ym"].values[k12], o["size"].values[k12]):
                b0 = idx_at(c.region, int(ym))
                if b0: pp.append(ppm * max(0.7, min(1.4, base / b0))); sz.append(z)
            if len(pp) >= 2:
                ms = float(np.median(sz)); r = area / ms
                if 0.6 <= r <= 1.6: t3 = float(np.median(pp)) * area * float(np.exp(-0.285 * np.log(r)))
    if t2 and t3 and abs(t3 / t2 - 1) > 0.20: t3 = None
    if t2 and t3 and n6 == 0: return 0.6 * t2 + 0.4 * t3
    return t2 or t3


