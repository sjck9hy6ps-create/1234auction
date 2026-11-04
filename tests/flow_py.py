import numpy as np
from datetime import date,timedelta,datetime
def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def int_to_date(v):
    v = int(v)
    return datetime(v // 10000, (v // 100) % 100, v % 100)


def flow_ratio(dd, pp, cut_ymd, min_n):
    """🌊 시세 흐름(2026-11-04, 사용자: 수도권은 시군구·법정동 흐름이 비슷하고 지방은 단지별 차이가 극명 - 노이즈가 없어야 함) -
    입찰 30일 전(cut) 기준 최근 3개월 ㎡당 가격 중위값 ÷ 그 앞 3개월 중위값의 로그. dd=거래일(yyyymmdd 정렬 배열), pp=㎡당 가격. 두 구간 모두 min_n건 이상이 아니면 None(노이즈 방지: 값을 억지로 만들지 않음)"""
    if dd is None or len(dd) == 0:
        return None
    ref = int_to_date(int(cut_ymd))
    lo1, lo2 = ymd_int(ref - timedelta(days=90)), ymd_int(ref - timedelta(days=180))
    i2, i1, i0 = int(np.searchsorted(dd, lo2)), int(np.searchsorted(dd, lo1)), int(np.searchsorted(dd, int(cut_ymd)))
    R_, P_ = pp[i1:i0], pp[i2:i1]
    if len(R_) < min_n or len(P_) < min_n:
        return None
    a, b = float(np.median(R_)), float(np.median(P_))
    return float(np.log(a / b)) if a > 0 and b > 0 else None


