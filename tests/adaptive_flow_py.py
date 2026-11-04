import numpy as np
from datetime import date,timedelta,datetime
def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def int_to_date(v):
    v = int(v)
    return datetime(v // 10000, (v // 100) % 100, v % 100)


def ymd_ord(a):
    """yyyymmdd 정수(배열) → 1970-01-01부터 지난 날수(벡터 계산)"""
    a = np.asarray(a, dtype=np.int64); y = a // 10000; m = (a // 100) % 100; d = a % 100
    y = y - (m <= 2); era = y // 400; yoe = y - era * 400; mp = np.where(m > 2, m - 3, m + 9)
    doy = (153 * mp + 2) // 5 + d - 1; doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def adaptive_flow(dd, pp, cut_ymd, K, max_days):
    """🌊 적응형 흐름(2026-11-04, 사용자: 고정 건수·기간 기준은 수도권에만 맞음 - 지방은 거래가 적어 노이즈) -
    비교 기간 W = max(입찰 30일 전 이전 최근 K건이 걸린 기간, 90일): 거래가 적은 곳은 W가 자동으로 길어지고, 많은 곳도 90일보다 짧게 쓰지 않음(며칠치 가격에 흔들리지 않게).
    최근 W일(R)과 그 앞 W일(P)을 비교하고, P에도 K건 이상 있어야 하며 2W가 max_days를 넘으면 None.
    rate = 가격 변화(로그)를 W로 연율화, z = 변화 ÷ 불확실성(묶음 안 가격 흩어짐 MAD/√건수) - |z|<1이면 보합(불확실)로 취급, vol = 거래 수 변화(로그, +1 보정), dens = 최근 W의 하루 거래 수.
    dd=정렬된 거래일 yyyymmdd, pp=㎡당 가격"""
    if dd is None or len(dd) == 0: return None
    i = int(np.searchsorted(dd, int(cut_ymd)))
    if i < 2 * K: return None
    co = int(ymd_ord([int(cut_ymd)])[0]); oK = int(ymd_ord([int(dd[i - K])])[0]); W = max(co - oK, 90)
    if 2 * W > max_days: return None
    oall = ymd_ord(dd[max(0, i - 4000):i]); base = max(0, i - 4000)
    a1 = int(np.searchsorted(oall, co - W)); a0 = int(np.searchsorted(oall, co - 2 * W))
    nR, nP = (len(oall) - a1), (a1 - a0)
    if nR < K or nP < K: return None
    lr = np.log(np.asarray(pp[base + a1:i], dtype=float)); lp = np.log(np.asarray(pp[base + a0:base + a1], dtype=float))
    mR, mP = float(np.median(lr)), float(np.median(lp)); flow = mR - mP
    sR, sP = 1.4826 * float(np.median(np.abs(lr - mR))), 1.4826 * float(np.median(np.abs(lp - mP)))
    se = max(1.2533 * float(np.sqrt(sR ** 2 / nR + sP ** 2 / nP)), 0.005)
    return {"rate": flow / (W / 365.0), "z": flow / se, "vol": float(np.log((nR + 1) / (nP + 1))), "dens": nR / W}


