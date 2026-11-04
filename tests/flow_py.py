import numpy as np
from datetime import date,timedelta,datetime
def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def int_to_date(v):
    v = int(v)
    return datetime(v // 10000, (v // 100) % 100, v % 100)


def flow_pv(dd_p, pp, dd_v, cut_ymd, min_p, min_base):
    """🌊 시세 흐름 = 가격 + 거래량(2026-11-04, 사용자: 거래량이 줄어드는데 신고가면 하락 쪽, 거래량이 늘며 가격이 다져지면 상승기 쪽 - 가격만으로는 흐름을 못 봄) -
    입찰 30일 전(cut) 기준 ① 가격: 최근 3개월 ㎡당 가격 중위값 ÷ 그 앞 3개월 중위값(로그), 두 구간 모두 min_p건 이상이어야 함 ② 거래량: 최근 3개월 거래 수 ÷ 그 앞 9개월의 분기 평균 거래 수(로그, +1 보정),
    앞 9개월 거래가 min_base건 이상이어야 함. 모자라면 None(노이즈 방지: 값을 억지로 만들지 않음). dd_p·pp=가격용(날짜 yyyymmdd 정렬, ㎡당 가격), dd_v=거래량용 날짜(정렬)"""
    ref = int_to_date(int(cut_ymd)); price = None; vol = None
    lo1, lo2, lo3 = ymd_int(ref - timedelta(days=90)), ymd_int(ref - timedelta(days=180)), ymd_int(ref - timedelta(days=360))
    if dd_p is not None and len(dd_p):
        i2, i1, i0 = int(np.searchsorted(dd_p, lo2)), int(np.searchsorted(dd_p, lo1)), int(np.searchsorted(dd_p, int(cut_ymd)))
        R_, P_ = pp[i1:i0], pp[i2:i1]
        if len(R_) >= min_p and len(P_) >= min_p:
            a, b = float(np.median(R_)), float(np.median(P_))
            price = float(np.log(a / b)) if a > 0 and b > 0 else None
    if dd_v is not None and len(dd_v):
        a0, a1, a2 = int(np.searchsorted(dd_v, lo3)), int(np.searchsorted(dd_v, lo1)), int(np.searchsorted(dd_v, int(cut_ymd)))
        nR, nB = a2 - a1, a1 - a0
        if nB >= min_base:
            vol = float(np.log((nR + 1) / (nB / 3.0 + 1)))
    return price, vol


