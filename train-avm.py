#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
헤도닉 회귀모델(AVM, Automated Valuation Model) 학습 스크립트 - 2026-08 신규

## 왜 필요한가
index.html의 getCompEstValue()는 지금 "비슷한 물건 몇 건(반경/평형/연식 조건으로 골라낸
비교물건)의 평단가를 평균/중앙값 내는" 방식임. 표본이 넉넉한 대단지에서는 잘 맞지만,
나홀로 아파트·연립다세대처럼 비교물건 자체가 적은 경우 몇 건 안 되는 표본의 우연한 편차에
그대로 휘둘림. 이 스크립트는 house_trades 테이블 전체(28만 건 이상)를 회귀분석해서
"면적/층/연식/시점/법정동"이 평단가에 미치는 영향을 계수로 뽑아두고, 서버(api/data-coverage.js
mode=avmEstimate)가 그 계수로 임의의 물건 평단가를 예측하게 함 - 표본이 적은 물건도 전체
데이터의 패턴으로 보정된 값을 낼 수 있음.

## 방법론: Fixed-Effects(고정효과) 회귀 - Frisch-Waugh-Lovell(FWL) 정리 이용
법정동마다 "그 동네 자체의 기본 수준"이 다르므로(강남 vs 강북), 법정동을 더미변수로 넣는
게 정석이지만 법정동 수가 수천 개라 원-핫 인코딩하면 회귀행렬이 커짐. 대신 FWL 정리를 써서:
  1) 종속변수(y)와 설명변수(X)를 각각 "자기 그룹 평균"만큼 빼서 중심화(demean)함
  2) 중심화된 데이터로 회귀하면, 그 그룹을 더미변수로 실제로 넣은 것과 수학적으로 완전히
     동일한 계수(β)가 나옴(고전적인 패널데이터 계량경제학 기법) - 그런데 계산량은 훨씬 적음
  3) 그룹별 절편(그 그룹 고유의 기본 수준)은 "그 그룹 y 평균 - 그 그룹 X 평균·β"로 뒤에서
     따로 구함
이렇게 하면 "그룹 고정효과 + 연속변수(면적/층/연식/시점) 회귀"를 동시에 반영하면서도
행렬 크기는 변수 개수(6개)만큼만 유지됨.

## 그룹(고정효과 단위) - 아파트 vs 연립다세대 다르게 적용 (2026-08 추가)
처음엔 그룹을 법정동(region+dong) 하나로만 뒀는데, 실제 배포 후 확인해보니 같은 법정동
안에서도 단지(danji)별 편차가 매우 컸음(예: 인천/안산 고잔동 실측 573건 - 평단가 최소
1,291만원 ~ 최대 4,426만원, 약 3.4배 차이 - 준공연도·브랜드가 다른 단지가 섞여 있어서).
아파트는 표본이 넉넉하고(단지별로도 대부분 몇 건 이상 모임) danji 컬럼이 실제로 그 단지
정체성을 반영하므로, 아파트는 "단지(danji) 단위"까지 고정효과를 세분화함:
  danji(region+dong+danji) → 표본부족 시 dong(region+dong) → 그래도 부족하면 region
  3단계로 표본이 확보될 때까지 순서대로 승격(promote)함.
연립다세대는 애초에 거래 자체가 뜸하고(#297/#298 데이터 보강 전까지는) 단지 개념도
아파트만큼 뚜렷하지 않아(다세대는 한 필지에 한 동인 경우가 많음) 단지 단위로 쪼개면 표본이
너무 잘게 쪼개져 오히려 불안정해짐 - 연립다세대는 기존처럼 "법정동(dong) 단위" → 표본부족
시 region 2단계만 씀.

## 설명변수(X)
- log(size): 면적(㎡) 로그 - 면적이 클수록 평당가는 보통 체감(로그관계가 선형관계보다 잘 맞음)
- floor, floor^2: 층 및 층의 제곱(저층/고층 모두 살짝 할인되고 중간층이 프리미엄인 비선형
  관계를 잡기 위해 제곱항 추가)
- age, age^2: 연식(거래연도-준공연도) 및 제곱(신축 프리미엄이 빠르게 꺼지다가 완만해지는
  비선형 관계)
- time_trend: 거래시점(가장 오래된 거래로부터 경과 연수) - 전체 시장의 시간 흐름에 따른
  가격 추세를 잡음

## 종속변수(y)
log(평단가) = log(price / size * 3.305785) - 로그를 씌우는 이유는 (a) 가격이 0 밑으로
내려갈 수 없어 로그정규분포에 가깝고 (b) 계수를 "%변화"로 해석할 수 있어(예: age 계수
-0.01 = 연식 1년 늘 때마다 약 1% 하락) 해석이 쉬움.

## 사용법
  python train-avm.py
환경변수 SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 필요(GitHub Actions 시크릿으로 주입).
"""
import os
import re
import sys
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

# ⚠️ 2026-08(K-apt 2단계 추가): sync-kapt.py가 채워둔 kapt_complex_info(세대수 등)를
# 여기서 조인하려면 "5자리 시군구코드 → house_trades.region과 동일한 표기의 지역명" 매핑이
# 필요함 - sync-kapt.py와 어긋나지 않도록 공용 모듈(lawd_codes_py.py)에서 가져옴.
from lawd_codes_py import LAWD_CODES

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}
CODE_TO_REGION = dict(LAWD_CODES)

# ⚠️ 표본이 극단적으로 적은 그룹(< MIN_*_SAMPLES)은 FWL 중심화 자체가 불안정해짐
# (거래 1~2건짜리 그룹은 "그 그룹의 평균"이 곧 그 거래 자체라 회귀에 아무 정보도 안 남음).
# 이런 그룹은 한 단계 더 큰 단위로 묶어(승격) 표본을 확보함.
MIN_DANJI_SAMPLES = 5  # 아파트 전용 - 단지 단위 그룹의 최소 표본
MIN_DONG_SAMPLES = 5   # 법정동 단위 그룹의 최소 표본(아파트는 단지 승격 후 2차 기준, 연립다세대는 1차 기준)
MAX_AGE_YEARS = 60  # 이보다 오래된 건 데이터 오류로 보고 제외
PAGE_SIZE = 1000

# ⚠️ 2026-08(사용자 요청: "AVM 추정가를 법정동 기준만 적용하지 말고, 법정동 내 연식·평형
# 필터를 적용한 값으로") ──────────────────────────────────────────────────────
# 배경: 지금까지 "법정동" 고정효과(dong_effects[region|dong])는 danji(아파트)/grid(빌라)
# 표본이 부족해 승격됐을 때, 그 동 안의 모든 연식·평형을 뭉뚱그려 하나의 절편값으로 씀 -
# 신축 20평대와 노후 10평대가 같은 동이면 같은 "동네 기본가격"을 적용받았음. 개별 매물의
# 연식/면적 자체는 이미 age/log_size 회귀계수(전국 공통 기울기)로 반영되지만, "그 동네
# 안에서 연식·평형별로 가격수준 자체가 다르게 형성되는" 지역별 상호작용까지는 못 잡았음.
# danji/grid와 plain dong 사이에 "법정동+평형대+연식단계" 중간 그룹을 하나 더 끼워 넣어,
# 표본이 있으면 그 조합의 실제 평균 가격수준을 쓰고, 그마저 부족하면 기존처럼 법정동 →
# 시군구로 계속 승격되게 함. 경계값은 index.html의 PYEONG_TIERS/VILLA_AGE_TIERS와 반드시
# 일치시켜야 함(학습 시점과 서빙 시점의 그룹 정의가 어긋나면 group_key가 안 맞아 이 중간
# 단계가 사실상 무의미해짐 - grid_key/danji_key와 같은 종류의 학습/서빙 일치 요구사항).
MIN_TIER_SAMPLES = 5  # 법정동+평형대+연식단계 그룹의 최소 표본(danji/dong과 동일 기준)
PYEONG_TIER_BOUNDS = [  # (키, 상한 ㎡) - index.html PYEONG_TIERS와 반드시 동일
    ("t1", 33.0), ("t2", 44.0), ("t3", 55.0), ("t4", 66.0), ("t5", 85.0), ("t6", float("inf")),
]
AGE_TIER_BOUNDS = [  # (키, 최소연차, 최대연차) - index.html VILLA_AGE_TIERS와 반드시 동일
    ("premium", 0, 3), ("new", 4, 8), ("semi", 9, 15), ("old", 16, 25), ("aged", 26, float("inf")),
]


def _pyeong_tier_from_size(size_m2):
    """전용면적(㎡) → 평형대 키. index.html getPyeongTier()와 동일 경계."""
    if pd.isna(size_m2) or size_m2 <= 0:
        return "t_na"
    for key, max_m2 in PYEONG_TIER_BOUNDS:
        if size_m2 <= max_m2:
            return key
    return "t6"


def _age_tier_from_age(age_years):
    """연식(년) → 연식단계 키. index.html getAgeTierByYear()와 동일 경계."""
    if pd.isna(age_years):
        return "a_na"
    for key, lo, hi in AGE_TIER_BOUNDS:
        if lo <= age_years <= hi:
            return key
    return "aged"

# ⚠️ 2026-08(빌라 반경기반 공간 그룹핑 - 사용자 요청) ──────────────────────────────
# 배경: villa_v1의 홀드아웃 오차(±36%)가 apt_v1(±10%)보다 훨씬 컸는데, 원인 중 하나가
# 법정동(행정동) 단위 그룹핑이었음 - 행정동 경계는 행정 편의로 그어진 것이라 실제
# 매수자의 비교 반경(사용자: "빌라 매매를 위해 사실은 1km 내에서 움직이는게 핵심")과
# 일치하지 않음. 진짜 "반경 검색"은 물건마다 이웃 집합이 겹쳐서 FWL 고정효과 회귀의
# groupby.transform('mean') 방식과 근본적으로 안 맞음(그룹은 반드시 배타적 파티션이어야
# 함) - 대신 좌표를 GRID_CELL_KM 크기 격자로 스냅해 그룹 삼음(각 물건은 정확히 하나의
# 격자에 속하면서도, 격자 크기가 법정동보다 훨씬 작아 실제 도보/생활권 비교 단위에 더
# 가까움). 아파트는 danji(단지) 고정효과가 이미 위치를 정확히 반영하므로 이 격자 그룹핑을
# 적용하지 않음(danji 자체가 최고 수준의 위치 정보라 격자로 덮어쓸 이유가 없음).
GRID_CELL_KM = 1.0     # 격자 한 변의 대략적인 길이(km) - 사용자가 말한 "1km 내" 비교 반경에 맞춤
MIN_GRID_SAMPLES = 5   # 격자 단위 그룹의 최소 표본(danji/dong과 동일 기준 - 표본부족 시 법정동으로 승격)
LAT_KM_PER_DEG = 111.0  # 위도 1도 ≈ 111km(지구 어디서나 거의 일정) - 경도는 위도에 따라 달라져
# cos(위도)를 곱해 보정함(적도에서 111km, 극지방으로 갈수록 좁아짐 - 한국은 위도 약 33~38도).

# ⚠️ 2026-08(정확도 보완 - 이상치 제거/홀드아웃 검증 추가) ────────────────────────
# 배경: 이전엔 학습 데이터에 이상치 제거가 전혀 없었고(가격>0, 연식 0~60년 필터만 있었음),
# 학습 스크립트가 보고하는 R^2도 "전체 데이터로 학습한 뒤 그 데이터로 다시 채점"하는
# in-sample 값이라 실제 예측 정확도를 보여주지 못했음(특히 이 모델처럼 그룹(단지/법정동)
# 고정효과를 쓰면 그룹 수가 많을수록 R^2가 원래 낙관적으로 나옴 - 그룹 평균만 알아도 분산의
# 대부분이 설명되기 때문). 아래 두 가지로 보완함:
#  1) remove_residual_outliers(): 1차 학습 후 "잔차"(그룹·면적·층·연식·시점을 다 반영하고도
#     설명 안 되는 편차) IQR 기준 밖인 행을 제외하고 재학습. 원본 평단가가 아니라 잔차로
#     걸러내는 이유는 원본 평단가는 지역·면적차만으로도 자연스럽게 몇 배씩 벌어지므로
#     그 자체로는 이상치 판별 기준이 될 수 없기 때문(비교물건 UI의 getCompEstValue IQR
#     이상치 제거와 같은 발상이나, 회귀는 그룹 내 변동뿐 아니라 면적/층/연식차까지 이미
#     설명하므로 "잔차" 기준이 더 정확함).
#  2) evaluate_holdout(): 무작위 80/20 분할 - train만으로 재학습해서 test(모델이 한 번도
#     못 본 실제 거래)를 얼마나 잘 맞히는지 측정. 이 값이 in-sample R^2보다 훨씬 정직한
#     "새 물건 예측이 실제로 얼마나 정확한지" 추정치임. avm_model_coefs.feature_ranges(이미
#     jsonb라 스키마 변경 없이 새 키를 추가할 수 있음)에 저장해서 서버(data-coverage.js)가
#     예측값과 함께 오차범위를 같이 내려줄 수 있게 함.
RESIDUAL_IQR_MULT = 3.0  # 일반적인 이상치 탐지 기준(1.5)보다 훨씬 보수적으로 잡음 - 이 모델이
# 못 보는 정상적 요인(리모델링 상태·조망·급매 등)까지 이상치로 오인해 지워버리면 표본이
# 줄어 소규모 그룹이 더 불안정해지는 부작용이 있어, "명백한 데이터 이상"만 걸러내는 데 목적을 둠.
HOLDOUT_FRACTION = 0.2
HOLDOUT_SEED = 42  # 실행마다 다른 표본이 빠지면 검증지표가 매번 흔들려 비교가 어려움 - 고정
MIN_HOLDOUT_SAMPLES = 200  # 이보다 적으면 홀드아웃 지표 자체가 불안정해 계산을 건너뜀(null)


def fetch_all_rows(table: str, cols: str = "region,dong,danji,price,size,floor,deal_date,build_year") -> pd.DataFrame:
    """Supabase REST API에서 페이지네이션으로 전체 행을 가져옴. cols 기본값은 house_trades류
    테이블 기준이고, kapt_complex_info처럼 스키마가 다른 테이블은 호출부에서 cols를 넘겨씀."""
    rows = []
    offset = 0
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select={cols}&limit={PAGE_SIZE}&offset={offset}"
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        offset += PAGE_SIZE
        if len(batch) < PAGE_SIZE:
            break
    df = pd.DataFrame(rows)
    print(f"  {table}: {len(df)}행 로드")
    return df


def normalize_complex_name(name) -> str:
    """단지명 정규화 - house_trades.danji와 kapt_complex_info.kapt_name을 조인하기 위함.
    ⚠️ data-coverage.js의 normalizeComplexName()과 반드시 동일한 로직이어야 함(학습 시점과
    예측 시점의 정규화가 어긋나면 매칭이 조용히 실패함). 공백 제거 + "아파트"/"단지" 접미사
    제거 정도로 보수적으로만 정규화함 - 너무 공격적으로 정규화하면(예: 괄호 제거) 서로 다른
    단지(예: "이촌코오롱(A)"/"이촌코오롱(B)")를 잘못 같은 단지로 묶어버릴 위험이 있어 피함."""
    if not name:
        return ""
    s = re.sub(r"\s+", "", str(name).strip())
    for suf in ("아파트", "단지"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def build_kapt_lookup():
    """kapt_complex_info에서 (region, dong, 정규화단지명) → households/top_floor 매핑을 만듦.
    households가 아직 없는(sync-kapt.py가 상세정보를 아직 못 가져온) 행은 제외함.
    ⚠️ top_floor(최고층수, 2026-08 추가 - AVM 정확도 개선)는 households와 달리 선택적
    특성값으로 둠 - K-apt 원본에 top_floor가 비어있는 단지가 households보다 흔해서,
    households 기준 필수로 걸러내면 안 그래도 소중한 표본이 필요 이상 줄어듦(결측은
    attach_kapt_features에서 중앙값으로 폴백)."""
    raw = fetch_all_rows("kapt_complex_info", cols="kapt_name,sigungu_code,as3,households,top_floor")
    if raw.empty:
        print("  kapt_complex_info: 데이터 없음 - 아직 sync-kapt.py가 한 번도 안 돌았거나 초기 단계")
        return None
    raw = raw.dropna(subset=["kapt_name", "sigungu_code", "as3", "households"])
    if raw.empty:
        print("  kapt_complex_info: 상세정보(세대수) 채워진 행이 아직 없음")
        return None
    raw["households"] = pd.to_numeric(raw["households"], errors="coerce")
    raw = raw.dropna(subset=["households"])
    # ⚠️ 세대수 0(또는 음수)인 행이 섞여 있으면 np.log(0) = -inf가 되어 회귀행렬을 깨뜨림
    # (2026-08 실배포 중 SVD did not converge 크래시로 발견됨 - K-apt 원본에 상가/오피스
    # 복합단지 등에서 세대수 0으로 잘못 채워진 행이 실제로 존재함). 아예 매칭 후보에서 제외.
    raw = raw[raw["households"] > 0]
    if raw.empty:
        print("  kapt_complex_info: 세대수>0인 유효 행이 없음")
        return None
    raw["top_floor"] = pd.to_numeric(raw["top_floor"], errors="coerce")
    raw["region"] = raw["sigungu_code"].astype(str).map(CODE_TO_REGION)
    raw = raw.dropna(subset=["region"])  # LAWD_CODES에 없는 코드는 매칭 불가(있을 수 없지만 방어)
    raw = raw.rename(columns={"as3": "dong"})
    raw["_name_norm"] = raw["kapt_name"].map(normalize_complex_name)
    # 같은 (region,dong,정규화이름) 조합에 단지가 둘 이상 걸리면(드묾 - 동명이인 단지 등)
    # 세대수가 더 큰 쪽을 대표값으로 씀(대단지가 실거래도 더 많아 매칭 효용이 큼).
    raw = raw.sort_values("households", ascending=False).drop_duplicates(
        subset=["region", "dong", "_name_norm"], keep="first"
    )
    print(f"  kapt_complex_info: 매칭 가능한 단지 {len(raw)}개 (세대수 정보 있는 것만)")
    return raw[["region", "dong", "_name_norm", "households", "top_floor"]]


def _cache_key_part(p) -> str:
    """cache_key 한 조각을 warmup-locations.mjs(JS)와 같은 문자열로 만듦.
    ⚠️ 2026-08(실배포 발견, 역세권 매칭 0% 버그): Supabase REST에서 가져온 행을
    pd.DataFrame으로 만들면, main_num/sub_num처럼 일부 행이 null인 정수 컬럼은
    pandas가 컬럼 전체를 float64로 승격시켜(정수 dtype은 NaN을 못 담으므로) 152가
    152.0으로 바뀜 - str(152.0) == "152.0"인데 JS 쪽 Number(152).toString()은
    "152"라 뒤에 ".0"이 붙어 cache_key가 절대 일치하지 않게 됨(실제 배포 로그에서
    역세권 매칭 0/281398행으로 발견). 정수값을 갖는 float은 정수 문자열로 되돌려 맞춤."""
    # pd.isna()로 None/np.nan/pd.NA(nullable dtype)/NaT를 한 번에 다 걸러냄 - math.isnan()은
    # pd.NA(정수 컬럼이 nullable Int64/Float64로 들어오는 경우 발생 가능)에서 TypeError가 남.
    if pd.isna(p):
        return ""
    if isinstance(p, (float, np.floating)):
        if float(p).is_integer():
            return str(int(p))
        return str(p)
    return str(p)


def build_cache_key(dong, danji, bunji, road_name, main_num, sub_num) -> str:
    """warmup-locations.mjs의 buildCacheKey()와 반드시 동일해야 함(complex_coords/
    transit_features가 그 키로 저장돼 있음). JS의 Array.join은 null/undefined를 빈
    문자열로 바꾸므로 여기서도 None을 ""로 치환해 맞춤(_cache_key_part 참고)."""
    parts = [dong, danji, bunji, road_name, main_num, sub_num]
    return "|".join(_cache_key_part(p) for p in parts).lower()


def build_transit_lookup():
    """transit_features(sync-transit.mjs가 채움)를 그대로 불러옴 - cache_key가
    complex_coords와 동일한 체계라 house_trades 쪽에서도 같은 함수로 cache_key를
    만들어 정확히 일치(exact match)시킬 수 있음(K-apt처럼 이름 정규화 매칭이 아님)."""
    raw = fetch_all_rows("transit_features", cols="cache_key,dist_subway_m")
    if raw.empty:
        print("  transit_features: 데이터 없음 - 아직 sync-transit.mjs가 한 번도 안 돌았거나 초기 단계")
        return None
    raw["dist_subway_m"] = pd.to_numeric(raw["dist_subway_m"], errors="coerce")
    print(f"  transit_features: {len(raw)}행 로드 (역 발견 {int(raw['dist_subway_m'].notna().sum())}건, 반경밖 {int(raw['dist_subway_m'].isna().sum())}건)")
    return raw


def build_coords_lookup():
    """complex_coords(warmup-locations.mjs가 채워둔 단지/건물 좌표 캐시)를 그대로 불러옴 -
    cache_key가 house_trades/villa_trades 양쪽 모두와 같은 체계라 attach_transit_features와
    동일한 방식(build_cache_key)으로 정확히 일치(exact match)시킬 수 있음. 빌라 반경기반
    그룹핑(attach_spatial_grid_grouping)에만 씀 - single_trades(단독다가구)는 애초에
    지오코딩 대상이 아니라 여기 매칭될 수 없고, 그 행들은 자동으로 법정동 단위로 폴백됨."""
    raw = fetch_all_rows("complex_coords", cols="cache_key,lat,lon")
    if raw.empty:
        print("  complex_coords: 데이터 없음 - 아직 웜업 스크립트가 한 번도 안 돌았거나 초기 단계")
        return None
    raw["lat"] = pd.to_numeric(raw["lat"], errors="coerce")
    raw["lon"] = pd.to_numeric(raw["lon"], errors="coerce")
    raw = raw.dropna(subset=["lat", "lon"])
    print(f"  complex_coords: 좌표 있는 캐시 {len(raw)}개 로드")
    return raw


def _spatial_grid_key(lat, lon, cell_km):
    """좌표를 cell_km 크기 격자로 스냅해 격자 ID 문자열을 만듦.
    ⚠️ data-coverage.js의 spatialGridKey()와 반드시 같은 공식이어야 함(학습 시점과 예측
    시점의 격자 정의가 어긋나면 group_key가 절대 일치하지 않음 - K-apt/역세권 cache_key와
    같은 종류의 학습/서빙 일치 요구사항)."""
    if pd.isna(lat) or pd.isna(lon):
        return None
    lon_km_per_deg = LAT_KM_PER_DEG * math.cos(math.radians(lat))
    if lon_km_per_deg <= 1.0:  # 극단적 위도(사실상 발생 안 함) 방어 - 0 나눗셈류 문제 예방
        lon_km_per_deg = LAT_KM_PER_DEG
    lat_cell = int(math.floor(lat * LAT_KM_PER_DEG / cell_km))
    lon_cell = int(math.floor(lon * lon_km_per_deg / cell_km))
    return f"grid_{lat_cell}_{lon_cell}"


def attach_spatial_grid_grouping(df: pd.DataFrame, coords_lookup, cell_km: float, min_grid_samples: int):
    """clean_and_featurize가 이미 만들어둔 group_key(법정동→시군구 2단계)를, 좌표가 있는
    행에 한해 더 촘촘한 공간 격자(grid) 단위로 대체함 - danji가 아파트의 1차 그룹인 것과
    같은 자리에 빌라는 grid를 씀(grid→dong→region 3단계). 표본부족(min_grid_samples 미만)
    격자는 기존 danji 승격 로직과 동일하게 법정동 단위로 되돌림. 좌표를 못 찾은 행(단독주택
    등)은 건드리지 않고 기존 법정동/시군구 폴백을 그대로 유지함."""
    df = df.copy()
    df["_cache_key"] = df.apply(
        lambda r: build_cache_key(r.get("dong"), r.get("danji"), r.get("bunji"), r.get("road_name"), r.get("main_num"), r.get("sub_num")),
        axis=1,
    )
    if coords_lookup is None or coords_lookup.empty:
        print("  공간격자 그룹핑: complex_coords 데이터 없음 - 법정동 단위로 전량 폴백")
        df = df.drop(columns=["_cache_key"], errors="ignore")
        return df
    merged = df.merge(coords_lookup, left_on="_cache_key", right_on="cache_key", how="left")
    has_coord = merged["lat"].notna() & merged["lon"].notna()
    n_matched = int(has_coord.sum())
    print(f"  공간격자 좌표 매칭: {n_matched}/{len(merged)}행 ({n_matched / len(merged) * 100:.1f}%) - 나머지는 법정동 단위로 폴백")
    grid_key = pd.Series([None] * len(merged), index=merged.index, dtype=object)
    if n_matched > 0:
        idx = merged.index[has_coord]
        grid_key.loc[idx] = [
            _spatial_grid_key(lat, lon, cell_km)
            for lat, lon in zip(merged.loc[idx, "lat"], merged.loc[idx, "lon"])
        ]
    merged["grid_key"] = grid_key
    merged = merged.drop(columns=["_cache_key", "cache_key", "lat", "lon"], errors="ignore")

    # group_key 재구성: grid_key가 있는 행은 우선 그걸로 바꾸되(표본부족 시 원래 법정동/
    # 시군구 값으로 되돌림), 좌표가 없던 행은 clean_and_featurize가 만들어둔 값을 그대로 둠.
    has_grid = merged["grid_key"].notna()
    original_group = merged["group_key"].copy()
    new_group = original_group.copy()
    new_group.loc[has_grid] = merged.loc[has_grid, "grid_key"]
    grid_counts = new_group[has_grid].value_counts()
    small_grid = grid_counts[grid_counts < min_grid_samples].index
    demote_mask = has_grid & new_group.isin(small_grid)
    new_group.loc[demote_mask] = original_group.loc[demote_mask]
    merged["group_key"] = new_group
    merged = merged.drop(columns=["grid_key"], errors="ignore")
    n_grid_level = int((has_grid & ~demote_mask).sum())
    print(f"  공간격자({cell_km}km) 그룹 채택: {n_grid_level}/{len(merged)}행 (표본부족으로 법정동 승격 {int(demote_mask.sum())}행)")
    return merged


SUBWAY_SEARCH_RADIUS_M = 2000  # sync-transit.mjs의 SEARCH_RADIUS_M과 동일(반경 밖은 "역세권 아님")


def attach_transit_features(df: pd.DataFrame, transit_lookup):
    """df에 지하철역까지 거리(log_dist_subway)를 조인함. 아파트(house_trades)만 씀 -
    complex_coords/transit_features가 단지(danji) 단위 좌표라 danji 개념이 뚜렷한
    아파트에만 정확히 맞고, 연립다세대는 건물 수가 훨씬 많아 전수 좌표화 비용이 커서
    이번 단계에서는 제외함(모듈 상단 K-apt 설명과 같은 이유로 예산 문제).
    매칭 3가지 케이스:
      1) transit_features에 아예 없음(아직 좌표 웜업/역거리 동기화가 안 된 단지) → 결측 취급
      2) 있는데 dist_subway_m이 null(반경 2km 안에 역이 없음이 확인됨) → "먼 거리"로 확정 처리(반경값 그대로 사용)
      3) 역을 찾음 → 그 거리값 사용
    1)의 결측만 중앙값으로 폴백(모르는 것과 "확인해봤더니 멂"은 다른 정보이므로 구분)."""
    df = df.copy()
    df["_cache_key"] = df.apply(
        lambda r: build_cache_key(r.get("dong"), r.get("danji"), r.get("bunji"), r.get("road_name"), r.get("main_num"), r.get("sub_num")),
        axis=1,
    )
    if transit_lookup is None or transit_lookup.empty:
        median_dist = 500.0
        df["log_dist_subway"] = np.log(median_dist + 100)
        df = df.drop(columns=["_cache_key"], errors="ignore")
        return df, median_dist, 0.0
    merged = df.merge(transit_lookup, left_on="_cache_key", right_on="cache_key", how="left")
    matched_mask = merged["cache_key"].notna()
    n_matched = int(matched_mask.sum())
    print(f"  역세권 매칭: {n_matched}/{len(merged)}행 ({n_matched / len(merged) * 100:.1f}%)")
    # 반경 안에서 역을 못 찾은 확정 케이스는 반경값으로 채움(모르는 게 아니라 "멀다"는 확정 정보)
    merged.loc[matched_mask & merged["dist_subway_m"].isna(), "dist_subway_m"] = SUBWAY_SEARCH_RADIUS_M
    known_vals = merged.loc[matched_mask, "dist_subway_m"]
    median_dist = float(known_vals.median()) if not known_vals.empty else 500.0
    # 아직 동기화 자체가 안 된(매칭 자체가 안 된) 행만 중앙값 폴백
    merged["dist_subway_m"] = merged["dist_subway_m"].fillna(median_dist)
    merged["log_dist_subway"] = np.log(merged["dist_subway_m"] + 100)  # +100: 매우 가까운 경우도 log(0) 방지
    merged = merged.drop(columns=["_cache_key", "cache_key", "dist_subway_m"], errors="ignore")
    match_rate = n_matched / len(merged) if len(merged) else 0.0
    return merged, median_dist, match_rate


def build_school_lookup():
    """school_info(sync-school.mjs가 채움)에서 (region, dong)별 초등학교/중학교 개수를 집계함.
    ⚠️ 실제 학업성취도/진학률 데이터가 아니라 "밀집도 근사치"임(모듈 상단 설명 참고) - 학교
    수가 많다고 반드시 학군이 좋다는 뜻은 아니지만, 초등학교 도보통학권/중학교 배정권 개념과
    상관관계가 있어 참고 지표로 씀. 아직 지오코딩(region/dong 채우기) 안 된 학교는 자동으로
    제외됨(région/dong이 null이라 groupby에서 빠짐) - sync-school.mjs Phase B가 진행될수록
    커버리지가 늘어남."""
    raw = fetch_all_rows("school_info", cols="school_type,region,dong")
    if raw.empty:
        print("  school_info: 데이터 없음 - 아직 sync-school.mjs가 한 번도 안 돌았거나 초기 단계")
        return None
    raw = raw.dropna(subset=["region", "dong", "school_type"])
    if raw.empty:
        print("  school_info: 지오코딩(region/dong) 완료된 행이 아직 없음")
        return None
    counts = raw.groupby(["region", "dong", "school_type"]).size().unstack(fill_value=0)
    counts = counts.reset_index()
    for col in ("초등학교", "중학교"):
        if col not in counts.columns:
            counts[col] = 0
    counts = counts.rename(columns={"초등학교": "elem_count", "중학교": "middle_count"})
    print(f"  school_info: 지오코딩 완료 {len(raw)}건 → {len(counts)}개 법정동에 집계")
    return counts[["region", "dong", "elem_count", "middle_count"]]


def attach_school_features(df: pd.DataFrame, school_lookup):
    """df에 (region,dong) 기준 초/중학교 개수를 조인함. count=0은 "그 동네에 학교가 없다"는
    실제 정보일 수도, 아직 지오코딩이 안 끝나 비어 보이는 것일 수도 있음 - 다만 log(1+count)를
    쓰므로(count=0이어도 log(1)=0으로 안전, K-apt의 log(0) 문제 자체가 구조적으로 발생 안 함)
    별도 중앙값 폴백 없이 그대로 0으로 둬도 회귀가 깨지지 않음(초기엔 신호가 약하다가
    sync-school.mjs가 더 돌수록 자연히 정보량이 늘어나는 구조)."""
    df = df.copy()
    if school_lookup is None or school_lookup.empty:
        df["log_elem_count"] = 0.0
        df["log_middle_count"] = 0.0
        return df
    merged = df.merge(school_lookup, on=["region", "dong"], how="left")
    merged["elem_count"] = merged["elem_count"].fillna(0)
    merged["middle_count"] = merged["middle_count"].fillna(0)
    n_matched = int((merged["elem_count"] + merged["middle_count"] > 0).sum())
    print(f"  학군(밀집도) 매칭: {n_matched}/{len(merged)}행에서 1개 이상 학교 확인 ({n_matched / len(merged) * 100:.1f}%)")
    merged["log_elem_count"] = np.log1p(merged["elem_count"])
    merged["log_middle_count"] = np.log1p(merged["middle_count"])
    merged = merged.drop(columns=["elem_count", "middle_count"], errors="ignore")
    return merged


def build_month_dummies(df: pd.DataFrame):
    """#299: 거래연월(YYYYMM) 더미변수를 추가함. 기존 time_trend(선형 추세 하나, 기울기 1개)
    만으로는 실제 시장의 비선형 변동(정책 발표·금리 급변·계절성 등으로 특정 달에만 확 튀는
    경우)을 못 잡음 - 월별 더미를 추가하면 "그 달엔 선형추세가 예측한 값보다 얼마나 더/덜
    비쌌는가"를 달마다 독립적으로 추정해 학습기간 내부의 적합도를 세분화함.
    가장 이른 달(time_trend의 기준일이 속한 달)을 기준(reference)으로 빼서 더미변수 함정
    (dummy trap - 모든 달을 다 넣으면 절편과 완전공선성)을 피함.
    ⚠️ 예측 시점(항상 "오늘")은 학습 데이터의 마지막 달보다 미래라 이 달 더미들 중 어떤
    것에도 해당하지 않음(전부 0). avmPredict가 모델에 없는 계수/모델엔 있지만 features에
    없는 키를 자동으로 0 취급하도록 이미 일반화돼 있어서(K-apt 연동 때 Object.keys(coefs)
    패턴으로 바꿔둠) 서버(data-coverage.js) 쪽 코드 변경이 전혀 필요 없음 - 예측은 항상
    time_trend의 선형 연장분만 적용되고, 월별 더미는 과거 데이터 적합에만 기여함(K-apt
    세대수가 표본충분 단지에서 그룹고정효과에 흡수돼 기여가 0이 되는 것과 같은 구조로,
    "지금 당장 서빙에 값이 없어도 안전하게 무시됨"을 이용한 설계)."""
    df = df.copy()
    deal_month_num = (df["deal_date"] // 100 % 100).astype(int)
    deal_ym = df["deal_year"] * 100 + deal_month_num
    months = sorted(deal_ym.unique())
    ref_month = months[0]
    dummy_cols = []
    for ym in months:
        if ym == ref_month:
            continue
        col = f"ym_{ym}"
        df[col] = (deal_ym == ym).astype(float)
        dummy_cols.append(col)
    print(f"  월별 시점보정: {len(months)}개월 구간(기준월 {ref_month}) → 더미 {len(dummy_cols)}개 추가")
    return df, dummy_cols


def _attach_floor_tier_features(df: pd.DataFrame, top_floor_col, median_top_floor):
    """면적/연식처럼 매끄러운 곡선(log_size, age/age^2)으로는 못 잡는 지하/1층/탑층의
    불연속적 가격차를 반영하는 피처 4개를 추가함(2026-08, AVM 정확도 개선 - 경매 비교물건
    매칭에 이미 쓰던 getFloorTier 개념과 같은 통찰을 회귀모델에도 반영). floor/floor^2 하나만
    으로는 "5층짜리 건물의 5층(탑층)"과 "20층짜리 건물의 5층(중간층)"을 구분 못 함(절대
    층수만 같고 건물 높이 정보가 없어서) - top_floor(K-apt 최고층수)로 상대적 위치를 알아야
    구분 가능함.
      - floor_ratio: 층/최고층수(0~1에 가까울수록 고층) - 건물 높이와 무관하게 "얼마나
        꼭대기에 가까운지"를 반영하는 연속값
      - is_top_floor: 탑층 여부(누수·단열 리스크로 통상 할인되는 불연속 요인)
      - is_ground_floor: 1층 여부(사생활·소음 우려로 통상 할인 - floor^2 곡선의 매끄러운
        추세만으로는 못 잡는 1층 특유의 튐)
      - is_basement: 반지하 이하 여부(가장 큰 폭의 할인) - floor<=0 관례는 이 앱 다른 곳
        (JS의 getFloorTier/clExtractFloor)과 동일
    top_floor를 못 구한 행은 median_top_floor로 폴백함(households와 동일한 원칙) - 그마저도
    없으면(K-apt 자체가 비어있는 초기 상태) floor_ratio/is_top_floor는 0(중립값)으로 안전하게
    무력화됨."""
    df = df.copy()
    floor = df["floor"]
    df["is_basement"] = (floor <= 0).astype(float)
    df["is_ground_floor"] = (floor == 1).astype(float)
    if top_floor_col is not None and top_floor_col in df.columns:
        top = pd.to_numeric(df[top_floor_col], errors="coerce")
        if median_top_floor is not None:
            top = top.fillna(median_top_floor)
        valid = top.notna() & (top > 0) & (floor > 0)
        ratio = pd.Series(0.0, index=df.index)
        ratio.loc[valid] = (floor[valid] / top[valid]).clip(upper=1.2)
        df["floor_ratio"] = ratio
        top_flag = pd.Series(0.0, index=df.index)
        top_flag.loc[valid] = (floor[valid] >= top[valid]).astype(float)
        df["is_top_floor"] = top_flag
    else:
        df["floor_ratio"] = 0.0
        df["is_top_floor"] = 0.0
    return df


def attach_kapt_features(df: pd.DataFrame, kapt_lookup):
    """df(house_trades 기반)에 K-apt 세대수(log_households)와 최고층수 기반 상대층 피처
    4개(_attach_floor_tier_features 참고)를 추가함. 매칭 안 되는 행(K-apt 미등록 단지, 이름
    표기 차이 등)은 세대수/최고층수 모두 전체 매칭분의 중앙값으로 대체함(회귀에서 상수
    취급되어 실질적으로 정보가 없는 것과 같게 처리됨 - 잘못된 값을 지어내지 않으면서도
    컬럼 자체는 항상 숫자로 채워둬야 행렬 연산이 되므로).
    반환: (컬럼 추가된 df, 사용된 중앙값 세대수, 사용된 중앙값 최고층수(top_floor 정보가
    전혀 없으면 None) - 둘 다 서버 예측 시 미매칭 폴백에 재사용됨)"""
    df = df.copy()
    if kapt_lookup is None or kapt_lookup.empty:
        median_hh = 500  # 매칭 자료 자체가 없으면 전 행이 이 상수라 회귀에 실질적 영향 없음
        df["log_households"] = np.log(median_hh)
        df = _attach_floor_tier_features(df, top_floor_col=None, median_top_floor=None)
        return df, median_hh, None
    df["_danji_norm"] = df["danji"].fillna("").map(normalize_complex_name)
    merged = df.merge(kapt_lookup, left_on=["region", "dong", "_danji_norm"],
                       right_on=["region", "dong", "_name_norm"], how="left")
    # 방어적 처리: kapt_lookup은 이미 households>0만 남겼지만, 혹시라도 0/음수가 섞여
    # 들어오면 np.log가 -inf/NaN을 내며 회귀 전체를 깨뜨리므로 여기서도 한 번 더 결측 취급.
    merged.loc[merged["households"] <= 0, "households"] = np.nan
    n_matched = int(merged["households"].notna().sum())
    print(f"  K-apt 세대수 매칭: {n_matched}/{len(merged)}행 ({n_matched / len(merged) * 100:.1f}%)")
    matched_vals = merged.loc[merged["households"].notna(), "households"]
    median_hh = float(matched_vals.median()) if not matched_vals.empty else 500.0
    if median_hh <= 0:
        median_hh = 500.0
    merged["households"] = merged["households"].fillna(median_hh)
    merged["log_households"] = np.log(merged["households"])

    matched_top = merged.loc[merged["top_floor"].notna() & (merged["top_floor"] > 0), "top_floor"]
    median_top_floor = float(matched_top.median()) if not matched_top.empty else None
    n_top_matched = int((merged["top_floor"].notna() & (merged["top_floor"] > 0)).sum())
    print(f"  K-apt 최고층수 매칭: {n_top_matched}/{len(merged)}행 ({n_top_matched / len(merged) * 100:.1f}%)")
    merged = _attach_floor_tier_features(merged, top_floor_col="top_floor", median_top_floor=median_top_floor)

    merged = merged.drop(columns=["_danji_norm", "_name_norm", "households", "top_floor"], errors="ignore")
    return merged, median_hh, median_top_floor


def clean_and_featurize(df: pd.DataFrame, use_danji: bool) -> pd.DataFrame:
    df = df.copy()
    # ⚠️ 2026-08(villa_v1 버그 수정): villa_trades+single_trades처럼 테이블 두 개를 concat하면,
    # 한쪽 테이블에서 특정 컬럼이 전부 null(JSON null)인 경우(예: 단독다가구는 "floor" 개념이
    # 없어 single_trades.floor가 전부 null) pandas가 그 컬럼을 dtype object로 잡고, 다른
    # 테이블의 float64 컬럼과 concat되면 합쳐진 컬럼 전체가 object dtype이 됨. 이후 floor**2 같은
    # 산술 연산까지는 통과하지만(object라도 원소가 숫자면 pow는 동작) 최종적으로 fit_fwl()에서
    # .to_numpy()로 numpy 배열을 만들 때 dtype object가 그대로 남아 np.linalg.lstsq가
    # "Cannot cast ... dtype('O') to dtype('float64')"로 실패함(house_trades는 테이블이
    # 하나뿐이라 이 문제가 없었음 - villa_v1 학습에서 실제로 발생 확인). price/size/floor/
    # build_year를 여기서 명시적으로 숫자형 변환해 원천 차단.
    for col in ("price", "size", "floor", "build_year"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # ⚠️ 2026-08(단독주택 학습 제외 버그 수정): is_single_house=1인 행(single_trades,
    # 단독/다가구)은 floor 개념 자체가 없어 원본이 항상 null인데, 바로 아래 dropna가
    # floor를 필수 필드로 요구해 이 행들을 전부 걸러내고 있었음 - villa_v1이 "villa_trades+
    # single_trades를 합쳐 학습한다"는 문서/주석과 달리 실제로는 단독주택이 단 한 건도
    # 학습되지 않고 있었음(사용자 피드백으로 발견). 임의의 층수를 지어내는 대신 "층 개념
    # 없음"을 뜻하는 중립값 1(1층 취급, floor^2도 1로 왜곡 최소화)로 채우고, is_single_house
    # 더미(아래 train_one에서 feature_cols에 추가됨)로 다세대/연립과의 평균 가격수준 차이를
    # 회귀가 별도 계수로 직접 추정하게 함.
    if "is_single_house" in df.columns:
        single_mask = df["is_single_house"] == 1
        df.loc[single_mask, "floor"] = df.loc[single_mask, "floor"].fillna(1.0)
    # 필수 필드 결측/이상치 제거
    df = df.dropna(subset=["price", "size", "floor", "deal_date", "region", "dong"])
    df = df[(df["price"] > 0) & (df["size"] > 0)]
    df["deal_date"] = pd.to_numeric(df["deal_date"], errors="coerce")
    df = df.dropna(subset=["deal_date"])
    df["deal_year"] = (df["deal_date"] // 10000).astype(int)

    # build_year 결측치는 이 행을 통째로 버리지 않고 "연식 unknown" 그룹으로 표시만 하고
    # 회귀에서는 제외(연식 변수가 없으면 age를 만들 수 없으므로) - 결측 아닌 나머지 변수는
    # 어차피 이 스크립트가 아니라 서버 쪽 폴백(getCompEstValue 등)에서 이미 처리하고 있음.
    df = df.dropna(subset=["build_year"])
    df["build_year"] = pd.to_numeric(df["build_year"], errors="coerce")
    df = df.dropna(subset=["build_year"])
    df["age"] = df["deal_year"] - df["build_year"]
    df = df[(df["age"] >= 0) & (df["age"] <= MAX_AGE_YEARS)]

    df["ppp"] = df["price"] / df["size"] * 3.305785  # 평당가(만원/평)
    df = df[df["ppp"] > 0]
    df["y"] = np.log(df["ppp"])
    df["log_size"] = np.log(df["size"])
    df["floor2"] = df["floor"] ** 2
    df["age2"] = df["age"] ** 2

    min_date = df["deal_date"].min()
    min_dt = datetime.strptime(str(int(min_date)), "%Y%m%d")

    def days_since_min(d):
        dt = datetime.strptime(str(int(d)), "%Y%m%d")
        return (dt - min_dt).days / 365.0

    df["time_trend"] = df["deal_date"].apply(days_since_min)

    # region은 "서울특별시 강남구"처럼 이미 시군구 단위 문자열 - 그대로 그룹키의 최상위
    # 단계(최후의 폴백)로 씀.
    df["dong_key"] = df["region"].astype(str) + "|" + df["dong"].astype(str)
    # ⚠️ 2026-08(법정동+평형대+연식단계 중간 그룹) - danji/grid와 plain dong 사이에 끼워 넣을
    # 중간 단계 키. 위 PYEONG_TIER_BOUNDS/AGE_TIER_BOUNDS 참고.
    df["pyeong_tier"] = df["size"].apply(_pyeong_tier_from_size)
    df["age_tier"] = df["age"].apply(_age_tier_from_age)
    df["tier_key"] = df["dong_key"] + "|" + df["pyeong_tier"] + "|" + df["age_tier"]

    if use_danji:
        # 1단계: 단지(danji) 단위로 최대한 세분화 - 단지명 결측/공란은 "(단지미상)"으로 묶어
        # 최소한 법정동 단위 폴백과 동급 취급되게 함(단지가 없으면 danji_key === dong_key와
        # 사실상 동치가 되어 굳이 별도 승격 로직이 없어도 자연스럽게 동일하게 동작함).
        danji_col = df["danji"].fillna("").astype(str)
        danji_col = danji_col.where(danji_col.str.strip() != "", "(단지미상)")
        df["danji_key"] = df["dong_key"] + "|" + danji_col
        df["group_key"] = df["danji_key"]
        danji_counts = df["group_key"].value_counts()
        small_danji = danji_counts[danji_counts < MIN_DANJI_SAMPLES].index
        # ⚠️ 표본부족 단지는 곧장 법정동(dong_key)이 아니라 법정동+평형대+연식단계(tier_key)로
        # 먼저 승격함 - 아래 "1.5단계"에서 이 tier_key도 표본이 부족하면 다시 dong_key로
        # 승격되므로, 최종 결과는 기존과 같거나(표본이 있으면) 더 세분화됨(표본이 있으면).
        df.loc[df["group_key"].isin(small_danji), "group_key"] = df.loc[df["group_key"].isin(small_danji), "tier_key"]
    else:
        # 연립다세대(grid를 쓰지 않는 경우)도 danji와 동일한 이유로 dong_key 대신 tier_key에서
        # 시작함 - use_grid=True인 모델은 이후 attach_spatial_grid_grouping()이 grid 표본이
        # 부족한 행만 이 tier_key(원본 group_key)로 되돌리므로 자동으로 grid→tier→dong→region
        # 4단계 승격 사슬이 완성됨.
        df["group_key"] = df["tier_key"]

    # 1.5단계: (단지/grid 승격 후 남은, 혹은 애초에 danji/grid를 안 쓰는 경우의) 법정동+평형대+
    # 연식단계 그룹도 표본이 부족하면 법정동(dong) 단위로 승격. group_key가 여전히 "tier_key
    # 그 자체"인 행들만 대상으로 함(이미 danji/grid로 세분화된 표본충분 그룹은 건드리지 않음).
    is_tier_level = df["group_key"] == df["tier_key"]
    tier_counts = df.loc[is_tier_level, "group_key"].value_counts()
    small_tier = tier_counts[tier_counts < MIN_TIER_SAMPLES].index
    promote_tier_mask = is_tier_level & df["group_key"].isin(small_tier)
    df.loc[promote_tier_mask, "group_key"] = df.loc[promote_tier_mask, "dong_key"]

    # 2단계: (위에서 남은, 혹은 애초에 danji/grid/tier를 안 쓰는 경우의) 법정동 단위 그룹도
    # 표본이 부족하면 시/군/구(region)로 한 번 더 승격. group_key가 여전히 "dong_key 그
    # 자체"인 행들만 대상으로 함(이미 더 세분화된 표본충분 그룹은 건드리지 않음).
    is_dong_level = df["group_key"] == df["dong_key"]
    dong_counts = df.loc[is_dong_level, "group_key"].value_counts()
    small_dong = dong_counts[dong_counts < MIN_DONG_SAMPLES].index
    promote_mask = is_dong_level & df["group_key"].isin(small_dong)
    df.loc[promote_mask, "group_key"] = df.loc[promote_mask, "region"]

    return df


FEATURE_COLS = ["log_size", "floor", "floor2", "age", "age2", "time_trend"]


def fit_fwl(df: pd.DataFrame, feature_cols):
    """Frisch-Waugh-Lovell 고정효과 회귀. 반환: (beta dict, group_effects dict, r_squared, n)
    ⚠️ 2026-08(K-apt 연동): feature_cols를 모듈 상수 대신 파라미터로 받도록 일반화함 - 아파트는
    log_households(세대수)까지 포함한 7개, 연립다세대는 기존 6개(FEATURE_COLS) 그대로라
    모델별로 변수 개수가 달라짐.

    ⚠️ 2026-08(경험적 베이즈 수축(empirical Bayes shrinkage) 도입 - 빌라 AVM 오차범위 근본개선):
    지금까지 그룹별 절편(group_effects)은 "그 그룹 표본의 y평균 - X평균·β"를 그대로 썼는데,
    이건 표본이 적을수록(MIN_GRID_SAMPLES=5처럼 최소치를 겨우 넘긴 그룹) 그 평균 자체가
    우연한 노이즈에 크게 휘둘림(동전을 5번 던진 앞면 비율이 500번 던진 것보다 훨씬 들쭉날쭉한
    것과 같은 원리). 아파트는 danji가 표본이 넉넉한 경우가 많아 이 노이즈가 상대적으로
    덜 문제였지만, 연립다세대는 grid(공간격자)/법정동 그룹이 최소표본(5건) 근처에 훨씬 자주
    몰려있어 이 노이즈가 villa_v1의 홀드아웃 오차(±36%)를 키우는 핵심 원인 중 하나로 추정됨
    (MIN_TRANSIT_MATCH_RATE 같은 개별 변수 단위 임시방편으로는 이 구조적 문제 자체를 못 고침).
    고전적인 축소추정(James-Stein/empirical Bayes, Efron & Morris 1975)을 적용해 표본이 적은
    그룹일수록 전체 평균(theta_bar) 쪽으로 더 많이 끌어당김:
      1) sigma2_w(그룹 내 개별 관측치 노이즈 분산)를 그룹별 잔차제곱합을 자유도(n_i-1)로
         풀링해 추정 - "설명 안 되는 개별 매물 편차"의 크기.
      2) v_i = sigma2_w / n_i - 그룹 i의 표본평균(raw effect)이 갖는 표준오차의 분산(그룹
         표본이 적을수록 v_i가 커짐 = 그 그룹 추정치를 믿을 수 없다는 뜻).
      3) tau2(그룹 간 "진짜" 차이의 분산)를 DerSimonian-Laird 방법(메타분석에서 쓰는 표준
         적률법)으로 추정.
      4) 수축가중치 B_i = tau2/(tau2+v_i) - v_i가 크면(표본↓) B_i가 0에 가까워져 grand mean
         쪽으로 많이 끌려가고, v_i가 작으면(표본↑) B_i가 1에 가까워져 원래 raw 평균을 거의
         그대로 씀. 표본이 큰 그룹은 사실상 원래와 거의 동일하게 동작하므로 아파트 쪽 정확도를
         해칠 위험은 낮고, 표본이 작은 그룹(villa에 훨씬 흔함)에서만 선택적으로 안정화됨.
    R^2도 이 수축된 효과로 채점함(그룹이 많을수록 낙관적으로 부풀던 in-sample R^2가 더 정직한
    값으로 낮아지는 부수효과가 있음 - 모듈 상단 "정확도 보완" 취지와 일치)."""
    group_means = df.groupby("group_key")[["y"] + feature_cols].transform("mean")
    y_tilde = (df["y"] - group_means["y"]).to_numpy()
    X_tilde = (df[feature_cols] - group_means[feature_cols]).to_numpy()

    # 최소제곱해 (X_tilde^T X_tilde) beta = X_tilde^T y_tilde (기울기 계수는 그대로 OLS - 수축은
    # 그룹 절편에만 적용함. 기울기까지 수축하면 "표본이 적은 그룹의 면적/연식 효과까지 다른
    # 그룹과 강제로 비슷해진다"는 의미가 되어 원래 FWL의 취지(그룹 고유 수준차만 분리)를 벗어남)
    beta, residuals, rank, sv = np.linalg.lstsq(X_tilde, y_tilde, rcond=None)
    beta_dict = {name: float(b) for name, b in zip(feature_cols, beta)}

    # 그룹별 raw 절편 = 그 그룹의 y평균 - 그 그룹의 X평균·beta
    group_agg = df.groupby("group_key")[feature_cols + ["y"]].mean()
    group_agg["pred_no_intercept"] = group_agg[feature_cols].to_numpy() @ beta
    group_agg["effect_raw"] = group_agg["y"] - group_agg["pred_no_intercept"]
    n_by_group = df.groupby("group_key").size()
    group_agg["n"] = n_by_group

    # sigma2_w 추정 - 그룹 고유효과(raw)까지 반영한 개별 관측치 잔차의 그룹내 제곱합을
    # 전체 자유도(sum of (n_i-1))로 풀링. raw effect가 정의상 그룹평균이라 그룹 내 잔차평균은
    # 항상 0이므로, 이 잔차의 분산이 곧 "그 그룹 평균만으로는 설명 안 되는 개별 노이즈" 크기.
    df_tmp = df[["group_key"] + feature_cols + ["y"]].copy()
    df_tmp["_effect_raw"] = df_tmp["group_key"].map(group_agg["effect_raw"])
    df_tmp["_pred"] = df_tmp[feature_cols].to_numpy() @ beta + df_tmp["_effect_raw"].to_numpy()
    df_tmp["_resid"] = df_tmp["y"] - df_tmp["_pred"]
    resid_ss_by_group = df_tmp.groupby("group_key")["_resid"].apply(lambda s: float((s ** 2).sum()))
    dof = (n_by_group - 1).clip(lower=0)
    total_dof = float(dof.sum())
    sigma2_w = float(resid_ss_by_group.sum() / total_dof) if total_dof > 0 else float(df_tmp["_resid"].var())
    if not np.isfinite(sigma2_w) or sigma2_w <= 0:
        sigma2_w = max(float(df_tmp["_resid"].var()), 1e-6)  # 극단적으로 표본이 다 n=1인 방어적 폴백

    v_i = sigma2_w / n_by_group.clip(lower=1)  # 그룹평균(raw effect)의 표본오차 분산
    theta_hat = group_agg["effect_raw"]
    w_i = 1.0 / v_i
    theta_bar = float((w_i * theta_hat).sum() / w_i.sum())  # 가중평균("grand mean") - 수축 종착점
    K = len(theta_hat)
    if K > 1:
        Q = float((w_i * (theta_hat - theta_bar) ** 2).sum())
        dof_k = K - 1
        denom = float(w_i.sum() - (w_i ** 2).sum() / w_i.sum())
        tau2 = max(0.0, (Q - dof_k) / denom) if denom > 0 else 0.0
    else:
        tau2 = 0.0

    if tau2 > 0:
        B_i = tau2 / (tau2 + v_i)
    else:
        # tau2==0: 그룹 간 진짜 차이가 통계적으로 안 잡히는 극단적 경우 - 전부 grand mean으로
        # 완전히 수축(모든 그룹이 사실상 같은 수준이라는 뜻이므로 안전함)
        B_i = pd.Series(0.0, index=theta_hat.index)
    group_effects = (B_i * theta_hat + (1 - B_i) * theta_bar).to_dict()

    # 전체 예측치로 R^2 계산 (수축된 효과 기준 - 실제 서빙에 쓰는 값으로 채점해야 정직함)
    df2 = df.copy()
    df2["group_effect"] = df2["group_key"].map(group_effects)
    y_pred = df2[feature_cols].to_numpy() @ beta + df2["group_effect"].to_numpy()
    ss_res = float(np.sum((df2["y"].to_numpy() - y_pred) ** 2))
    ss_tot = float(np.sum((df2["y"].to_numpy() - df2["y"].mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else None

    return beta_dict, {str(k): float(v) for k, v in group_effects.items()}, r_squared, len(df2)


def _predict_with_fallback(df: pd.DataFrame, feature_cols, beta: dict, group_effects: dict, default_effect: float):
    """beta/group_effects로 df를 예측(로그 평단가). group_key가 group_effects에 없으면(=이
    학습에 안 쓰인 그룹) 실서빙 때(data-coverage.js avmPredict의 dong_effects.__default__
    폴백)와 동일하게 default_effect로 대체함 - 홀드아웃 평가가 실제 서빙 조건과 최대한
    같아야 의미가 있으므로."""
    beta_vec = np.array([beta[c] for c in feature_cols])
    group_effect = df["group_key"].map(group_effects).fillna(default_effect).to_numpy()
    return df[feature_cols].to_numpy() @ beta_vec + group_effect


def remove_residual_outliers(df: pd.DataFrame, feature_cols):
    """전체 데이터로 1차 학습 후, 그 잔차의 IQR 기준(RESIDUAL_IQR_MULT배) 밖인 행을 제외함.
    반환: (필터링된 df, 제외된 행 수)"""
    beta0, group_effects0, _, _ = fit_fwl(df, feature_cols)
    default0 = float(np.mean(list(group_effects0.values()))) if group_effects0 else 0.0
    resid = df["y"].to_numpy() - _predict_with_fallback(df, feature_cols, beta0, group_effects0, default0)
    q1, q3 = np.percentile(resid, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return df, 0
    lo, hi = q1 - RESIDUAL_IQR_MULT * iqr, q3 + RESIDUAL_IQR_MULT * iqr
    keep = (resid >= lo) & (resid <= hi)
    n_removed = int((~keep).sum())
    if n_removed == 0:
        return df, 0
    return df[keep].reset_index(drop=True), n_removed


def evaluate_holdout(df: pd.DataFrame, feature_cols):
    """무작위 80/20 분할 - train만으로 재학습해서 test(모델이 한 번도 못 본 거래)를 얼마나 잘
    맞히는지 측정함. 학습 스크립트가 자체 보고하는 R^2(전체 데이터로 학습한 뒤 그 데이터로
    다시 채점하는 in-sample 값)는 항상 실제보다 낙관적으로 나오므로(그룹 고정효과 모델은
    그룹 수가 많을수록 원래 R^2가 잘 나올 수밖에 없음), 이 홀드아웃 지표가 "새 물건 예측이
    실제로 얼마나 정확한지"에 대한 훨씬 정직한 추정치임. 표본 부족 시 None을 반환함."""
    if len(df) < MIN_HOLDOUT_SAMPLES:
        return None
    rng = np.random.RandomState(HOLDOUT_SEED)
    shuffled_idx = rng.permutation(len(df))
    n_test = max(1, int(len(df) * HOLDOUT_FRACTION))
    test_idx, train_idx = shuffled_idx[:n_test], shuffled_idx[n_test:]
    df_train = df.iloc[train_idx].reset_index(drop=True)
    df_test = df.iloc[test_idx].reset_index(drop=True)
    if len(df_train) < MIN_HOLDOUT_SAMPLES:
        return None
    beta_t, group_effects_t, _, _ = fit_fwl(df_train, feature_cols)
    default_t = float(np.mean(list(group_effects_t.values()))) if group_effects_t else 0.0
    y_pred_test = _predict_with_fallback(df_test, feature_cols, beta_t, group_effects_t, default_t)
    resid_test = df_test["y"].to_numpy() - y_pred_test
    # 로그공간 잔차를 실제 %오차로 환산 - exp(로그차이)-1 이 곧 원래 스케일에서의 상대오차 비율임
    pct_err = np.abs(np.exp(resid_test) - 1.0) * 100.0
    return {
        "n": int(len(df_test)),
        "mape_pct": round(float(np.mean(pct_err)), 2),
        "median_ape_pct": round(float(np.median(pct_err)), 2),
        "residual_std_log": round(float(np.std(resid_test)), 5),
    }


def upsert_model(model_id: str, model_type: str, beta: dict, group_effects: dict, r_squared, n_samples: int, feature_ranges: dict):
    default_effect = float(np.mean(list(group_effects.values()))) if group_effects else 0.0
    payload = {
        "id": model_id,
        "model_type": model_type,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": n_samples,
        "r_squared": r_squared,
        "global_coefs": beta,
        "dong_effects": {**group_effects, "__default__": default_effect},
        "feature_ranges": feature_ranges,
    }
    url = f"{SUPABASE_URL}/rest/v1/avm_model_coefs?on_conflict=id"
    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    r = requests.post(url, headers=headers, data=json.dumps([payload]), timeout=30)
    if r.status_code >= 300:
        print(f"  ERROR upsert 실패({model_id}): {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()
    print(f"  {model_id} 저장 완료 - n={n_samples}, R^2={r_squared:.4f}" if r_squared is not None else f"  {model_id} 저장 완료 - n={n_samples}")


def train_one(tables, model_id: str, model_type: str, use_danji: bool, use_grid: bool = False,
              attach_kapt: bool = False, attach_transit: bool = False, attach_school: bool = False,
              attach_month_fe: bool = True):
    # tables: 테이블 하나(str) 또는 여러 개(list) - 연립다세대는 villa_trades(연립다세대)+
    # single_trades(단독다가구) 두 테이블을 합쳐서 하나의 모델로 학습함(이 앱 다른 곳(예:
    # rpc_top_dongs SQL, data-coverage.js getBucketDetailRows)도 "villa" 타입을 이 두 테이블의
    # 합집합으로 다뤄서 같은 관례를 따름).
    if isinstance(tables, str):
        tables = [tables]
    group_desc = '단지→법정동→시군구' if use_danji else ('공간격자→법정동→시군구' if use_grid else '법정동→시군구')
    print(f"[{model_id}] {', '.join(tables)} 학습 시작 (그룹 단위: {group_desc})")
    # attach_transit/use_grid가 True면 cache_key 조합에 필요한 주소 세부 컬럼(bunji/road_name/
    # main_num/sub_num)까지 같이 가져와야 함 - complex_coords/transit_features와 정확히 같은
    # 키를 재구성하려면 이 필드들이 반드시 필요함(warmup-locations.mjs가 저장할 때 쓴 것과 동일).
    cols = "region,dong,danji,price,size,floor,deal_date,build_year"
    if attach_transit or use_grid:
        cols += ",bunji,road_name,main_num,sub_num"
    raw_parts = []
    for t in tables:
        p = fetch_all_rows(t, cols=cols)
        if not p.empty:
            # is_single_house: single_trades(단독/다가구) 행을 표시해두는 더미 - 아래
            # clean_and_featurize의 floor 결측 처리 및 feature_cols 추가에 씀(모듈 내 주석 참고).
            p["is_single_house"] = 1.0 if t == "single_trades" else 0.0
            raw_parts.append(p)
    if not raw_parts:
        print(f"  {', '.join(tables)}: 데이터 없음, 스킵")
        return
    raw = pd.concat(raw_parts, ignore_index=True)
    df = clean_and_featurize(raw, use_danji)

    feature_cols = list(FEATURE_COLS)
    if "is_single_house" in df.columns and df["is_single_house"].nunique() > 1:
        # 단독/다가구와 연립/다세대가 실제로 섞여 학습되는 경우(villa_v1)에만 추가 - 두
        # 유형의 평균 가격수준 차이(단독주택은 층 개념이 없고 대지지분 비중이 다름 등)를
        # 회귀가 별도 계수로 흡수하게 함(다른 하나뿐인 값이면(0만 있음) 의미가 없어 제외).
        feature_cols.append("is_single_house")

    # ⚠️ 2026-08(빌라 반경기반 그룹핑, 사용자 요청): 법정동 대신 좌표 기반 격자를 1차 그룹
    # 단위로 씀 - 모듈 상단 GRID_CELL_KM 설명 참고. 좌표가 없는 행(단독주택 등)은 자동으로
    # 법정동/시군구 폴백을 그대로 유지함.
    if use_grid:
        coords_lookup = build_coords_lookup()
        df = attach_spatial_grid_grouping(df, coords_lookup, cell_km=GRID_CELL_KM, min_grid_samples=MIN_GRID_SAMPLES)

    # ⚠️ 2026-08(K-apt 2단계): 표본충분한 단지는 이미 danji 고정효과가 그 단지 평균을 정확히
    # 반영하므로 세대수 같은 "단지 고유 상수"를 더해도 득이 없음(그룹 내에서 상수라 FWL
    # 중심화 후 0이 되어 계수 추정에 기여를 못 함) - 대신 표본부족으로 dong/region 단위로
    # 승격된 그룹(=지금 "⚠️ 표본부족"으로 표시되는 케이스)에서는 그 그룹 안에 여러 단지가
    # 섞여 세대수가 실제로 달라지므로 거기서 유의미한 계수가 나옴. 즉 지금 신뢰도가 낮은
    # 케이스를 정확히 겨눈 보강 변수임(모듈 docstring 및 sync-kapt.py 참고).
    # ⚠️ 2026-08(층위치 피처 추가 - AVM 정확도 개선): 위 households 설명과 달리 floor_ratio/
    # is_top_floor/is_ground_floor/is_basement는 표본충분한 danji 그룹에서도 그대로 유의미함 -
    # households는 "단지 고유 상수"라 같은 단지 안에서는 항상 같은 값이므로 danji 고정효과가
    # 이미 흡수해버리지만(FWL 중심화 후 0), 층위치는 같은 단지 안에서도 호실마다 다르므로
    # (같은 건물이라도 1층/중간층/탑층이 섞여 거래됨) danji 고정효과로는 전혀 흡수되지 않고
    # 항상 추가 설명력을 가짐. K-apt 매칭 여부와 무관하게 attach_kapt=True 경로에 함께 묶어둔
    # 이유는 top_floor(K-apt 전용 데이터)에 의존하기 때문(households와 조회 경로가 같음).
    # ⚠️ 2026-08(버그 수정 - is_single_house 피처가 회귀에 실제로 반영되지 않던 문제, 빌라 AVM
    # 근본개선): 바로 위(line ~749)에서 feature_cols에 "is_single_house"를 추가해뒀는데
    # (clean_and_featurize의 단독주택 학습 제외 버그 수정과 짝을 이루는 부분), 여기서
    # feature_cols를 list(FEATURE_COLS)로 다시 초기화하며 그 추가분을 그대로 덮어써버리고
    # 있었음 - "단독주택과 연립다세대의 평균 가격수준 차이를 별도 계수로 흡수한다"는 문서상
    # 설계와 달리 실제로는 그 계수 자체가 회귀에 한 번도 들어간 적이 없었음(단독다가구가
    # 연립다세대와 완전히 동일하게 취급되어 옴 - villa_v1이 villa_trades+single_trades를
    # 합쳐 학습하는 만큼 이 버그의 영향이 작지 않았을 것으로 추정). list(FEATURE_COLS)로
    # 되초기화하는 대신 지금까지 쌓인 feature_cols를 그대로 이어감.
    median_households = None
    median_top_floor = None
    # ⚠️ 2026-08(villa 반지하/1층 할인 반영 - 빌라 AVM 근본개선): is_basement/is_ground_floor는
    # top_floor(K-apt 전용 데이터) 없이 floor 컬럼만으로 계산 가능한데, 지금까지
    # _attach_floor_tier_features가 attach_kapt_features 안에서만 호출돼(K-apt가 커버하지 않는
    # villa_v1은 attach_kapt=False라 이 로직 자체가 전혀 적용 안 됨) 연립다세대에서 특히 크고
    # 뚜렷한 가격요인인 반지하/1층 할인을 villa_v1이 하나도 못 잡고 있었음(floor/floor^2
    # 매끄러운 곡선만으론 반지하의 불연속적 대폭할인을 표현 못함 - _attach_floor_tier_features
    # 설명 참고). top_floor_col=None으로 먼저 무조건 호출해 is_basement/is_ground_floor만
    # 확보하고(floor_ratio/is_top_floor는 top_floor 정보가 없으니 0으로 중립화), attach_kapt=True
    # (아파트)면 아래에서 attach_kapt_features가 실제 top_floor로 다시 덮어써 floor_ratio/
    # is_top_floor까지 마저 채움(is_basement/is_ground_floor는 중복 추가 방지를 위해 거기서는
    # feature_cols에 다시 넣지 않음).
    df = _attach_floor_tier_features(df, top_floor_col=None, median_top_floor=None)
    feature_cols = feature_cols + ["is_basement", "is_ground_floor"]
    if attach_kapt:
        kapt_lookup = build_kapt_lookup()
        df, median_households, median_top_floor = attach_kapt_features(df, kapt_lookup)
        feature_cols = feature_cols + ["log_households", "floor_ratio", "is_top_floor"]

    # ⚠️ 2026-08(역세권/학군 연동): K-apt와 같은 이유로 표본충분한 단지는 danji 고정효과가
    # 이미 "그 위치"를 반영하므로 지하철역 거리도 그룹 내에서는 상수에 가까워 득이 적지만,
    # dong/region으로 승격된 그룹에서는 같은 그룹 안에 위치가 다른 여러 단지가 섞여 유의미한
    # 신호가 남음.
    # ⚠️ 2026-08(빌라 오차범위 개선 - 역세권 확대 적용): 처음엔 "연립다세대는 danji를
    # 안 써서(dong 고정효과) 단지 단위 좌표 커버리지 비용 대비 효용이 낮다"는 이유로
    # 아파트만 적용했었음. 그런데 이제 villa_v1도 grid(공간격자, danji보다도 더 촘촘한
    # 단위) 고정효과를 쓰게 되면서 오히려 사정이 반대가 됨 - 격자 내에서도 역과의 거리는
    # 여전히 달라질 수 있고, complex_coords는 villa_trades 좌표도 이미 갖고 있어(웜업
    # 스크립트가 아파트+빌라를 함께 지오코딩함) 추가 좌표화 비용 없이 바로 쓸 수 있음
    # (sync-transit.mjs가 지하철역-거리 동기화 우선순위를 아파트 위주로 둬서 빌라 커버리지가
    # 아직 얕을 수 있지만, 매칭 안 되는 행은 기존처럼 중앙값으로 안전하게 폴백됨).
    # ⚠️ 2026-08(버그 수정 - 파주 야당동 빌라 AVM 20억 오추정 사례로 발견): 매칭률(coverage)이
    # 극히 낮으면(예: 빌라 역세권 동기화 초기 단계 - 172,264행 중 19행, 0.01%) log_dist_subway
    # 값이 99.99%의 행에서 똑같은 중앙값 상수라, 회귀가 이 계수를 사실상 그 소수의 매칭된
    # 행(19건)만으로 추정하게 됨 - 표본이 극단적으로 적어 계수가 불안정/과적합되기 쉽고,
    # 실제로 매칭된(=중앙값이 아닌 진짜 거리값을 쓰는) 물건에 그 불안정한 계수가 곱해지면
    # 추정가가 크게 튈 수 있음(사용자 실측 사례로 확인). MIN_TRANSIT_MATCH_RATE 미만이면
    # 아예 변수 자체를 추가하지 않음(danji/grid 표본부족 시 상위 단위로 승격하는 것과 같은
    # 안전장치) - sync-transit.mjs가 매주 조금씩 매칭을 늘려가므로, 커버리지가 쌓이면 다음
    # 재학습부터 자동으로 다시 포함됨(코드를 다시 안 고쳐도 됨).
    MIN_TRANSIT_MATCH_RATE = 0.05  # 최소 5% 매칭돼야 계수를 안정적으로 추정할 수 있다고 봄
    median_dist_subway = None
    if attach_transit:
        transit_lookup = build_transit_lookup()
        df, median_dist_subway, transit_match_rate = attach_transit_features(df, transit_lookup)
        if transit_match_rate >= MIN_TRANSIT_MATCH_RATE:
            feature_cols = feature_cols + ["log_dist_subway"]
        else:
            print(f"  역세권 매칭률({transit_match_rate*100:.2f}%)이 {MIN_TRANSIT_MATCH_RATE*100:.0f}% 미만이라 "
                  f"log_dist_subway를 이번 학습에서 제외합니다(계수 불안정 방지 - 커버리지가 쌓이면 자동 재포함).")

    # 학군(밀집도 근사치)은 danji가 아니라 (region,dong) 단위 집계라 아파트/연립다세대 모두
    # 적용 가능함(단지 좌표 커버리지와 무관 - school_info는 학교 위치만 있으면 됨).
    if attach_school:
        school_lookup = build_school_lookup()
        df = attach_school_features(df, school_lookup)
        feature_cols = feature_cols + ["log_elem_count", "log_middle_count"]

    # #299: 월별 시점보정 더미 - 외부 데이터 동기화가 필요없는(house_trades 자체의 deal_date만
    # 씀) 순수 모델링 개선이라 기본값 True(위 build_month_dummies 설명 참고).
    if attach_month_fe:
        df, month_cols = build_month_dummies(df)
        feature_cols = feature_cols + month_cols

    print(f"  전처리 후 {len(df)}행 (그룹 {df['group_key'].nunique()}개, 변수 {len(feature_cols)}개)")
    if len(df) < 200:
        print(f"  표본이 너무 적어({len(df)}행) 학습을 건너뜁니다(최소 200건 필요).")
        return

    # 이상치 제거(잔차 IQR 기준) - 모듈 상단 "정확도 보완" 주석 참고
    df, n_outliers_removed = remove_residual_outliers(df, feature_cols)
    if n_outliers_removed > 0:
        print(f"  이상치(잔차 IQR×{RESIDUAL_IQR_MULT} 밖) {n_outliers_removed}건 제외 → {len(df)}행 남음")

    # 홀드아웃 검증(무작위 80/20) - 최종 서빙 모델은 아래에서 전체(이상치 제거된) 데이터로
    # 다시 학습하지만, 이 지표는 "새 물건 예측이 실제로 얼마나 정확한지"를 미리 가늠하는 용도
    holdout = evaluate_holdout(df, feature_cols)
    if holdout:
        print(f"  홀드아웃 검증(무작위 20%, {holdout['n']}건): 평균오차 {holdout['mape_pct']}% / 중앙값오차 {holdout['median_ape_pct']}%")
    else:
        print(f"  홀드아웃 검증: 표본 부족으로 건너뜀")

    beta, group_effects, r_squared, n = fit_fwl(df, feature_cols)
    # time_origin: time_trend 계산의 기준일(가장 오래된 거래일, YYYYMMDD 정수). 예측 시점(서버)
    # 에서도 "오늘 - time_origin" 일수로 같은 time_trend를 계산해야 학습 때와 정의가 일치하므로
    # 반드시 같이 저장해야 함(빠뜨리면 시점보정 계수가 엉뚱한 기준으로 적용되는 버그가 됨).
    feature_ranges = {
        "size": [float(df["size"].min()), float(df["size"].max())],
        "floor": [float(df["floor"].min()), float(df["floor"].max())],
        "age": [float(df["age"].min()), float(df["age"].max())],
        "time_origin": int(df["deal_date"].min()),
        # feature_cols를 그대로 저장해둬야 서버(data-coverage.js)가 이 모델이 log_households를
        # 쓰는지 여부를 하드코딩 없이 global_coefs 키 존재만으로 판단할 수 있음.
        "feature_cols": feature_cols,
    }
    if median_households is not None:
        # 예측 시점에 주어진 물건이 K-apt에서 못 찾아지는 경우(신축이라 아직 미등록, 이름
        # 표기 차이 등) 서버가 학습 때와 같은 중앙값으로 안전하게 폴백하기 위함 - 학습/서빙이
        # 서로 다른 임의값을 쓰면 계수 해석이 어긋나므로 반드시 같은 값을 공유해야 함.
        feature_ranges["median_households"] = median_households
    if median_dist_subway is not None:
        # K-apt와 같은 이유 - 예측 시점에 transit_features 매칭이 안 되는 물건은 서버가
        # 이 중앙값으로 폴백함(학습 때와 같은 값이어야 계수 해석이 어긋나지 않음).
        feature_ranges["median_dist_subway"] = median_dist_subway
    if median_top_floor is not None:
        # households/역세권과 같은 이유 - 예측 시점에 K-apt에서 top_floor를 못 찾는 물건은
        # 서버가 이 중앙값으로 폴백함(floor_ratio/is_top_floor 계산에 필요).
        feature_ranges["median_top_floor"] = median_top_floor
    if use_grid:
        # ⚠️ 서버(data-coverage.js)가 예측 시점에 물건 좌표로 grid_key를 재계산할 때 반드시
        # 같은 격자 크기를 써야 group_key가 일치함 - 하드코딩 대신 학습 때 실제 쓴 값을
        # 저장해 서버가 그대로 읽어쓰게 함(GRID_CELL_KM을 나중에 튜닝해도 서버 코드를
        # 따로 안 고쳐도 되는 부수효과도 있음).
        feature_ranges["grid_cell_km"] = GRID_CELL_KM
    # 정확도 보완(2026-08) - feature_ranges는 이미 jsonb라 스키마 변경 없이 새 키를 추가할 수
    # 있음(위 모듈 상단 주석 참고). 서버(data-coverage.js)가 이 값들을 읽어 point estimate와
    # 함께 "검증된" 오차범위를 같이 내려줌 - in-sample r_squared만 보여주는 것보다 훨씬 정직함.
    feature_ranges["outliers_removed"] = n_outliers_removed
    if holdout:
        feature_ranges["holdout_mape_pct"] = holdout["mape_pct"]
        feature_ranges["holdout_median_ape_pct"] = holdout["median_ape_pct"]
        feature_ranges["holdout_n"] = holdout["n"]
        feature_ranges["residual_std_log"] = holdout["residual_std_log"]
    upsert_model(model_id, model_type, beta, group_effects, r_squared, n, feature_ranges)


def main():
    # 아파트: 단지(danji) 단위까지 고정효과를 세분화(위 모듈 docstring "그룹(고정효과 단위)"
    # 참고) - 동일 법정동 내 단지 간 편차(준공연도·브랜드)를 직접 반영해 예측 정확도를 높임.
    # attach_kapt=True: K-apt 세대수를 추가 변수로 반영(위 train_one 안 주석 참고).
    # attach_transit=True: 지하철역 거리(역세권) 추가 변수 반영 - 단지 좌표(complex_coords)
    # 커버리지가 필요해 아파트만 적용. attach_school=True: (region,dong) 초/중학교 밀집도
    # 근사치 반영(#298 - 실제 학업성취도 API는 공개돼 있지 않아 밀집도로 근사, 모듈 상단 참고).
    # attach_month_fe=True(기본값): 월별 시점보정 더미 추가(#299 - build_month_dummies 참고).
    train_one("house_trades", "apt_v1", "apt", use_danji=True, attach_kapt=True,
              attach_transit=True, attach_school=True, attach_month_fe=True)
    # ⚠️ 2026-08(villa_v1 추가): 연립다세대·단독다가구는 villa_trades(연립다세대)+
    # single_trades(단독다가구) 두 테이블을 합쳐서 학습함(이 앱의 다른 집계 로직(rpc_top_dongs,
    # getBucketDetailRows 등)도 "villa" 타입을 이 두 테이블의 합집합으로 다뤄서 같은 관례를
    # 따름). K-apt도 연립다세대는 등록 대상이 아니라(공동주택 300세대 이상 등 요건)
    # attach_kapt=False로 둠. attach_school은 (region,dong) 집계라 연립다세대에도 그대로 적용.
    # ⚠️ 2026-08(빌라 오차범위 개선, ±36.1%→개선 목표 - 사용자 피드백): danji(단지) 개념이
    # 없는 빌라는 use_danji=False 그대로 두되, 대신 use_grid=True로 좌표 기반 약 1km 격자를
    # 1차 그룹 단위로 씀(법정동 행정구역 경계 대신 실제 거리 기준 - 모듈 상단 GRID_CELL_KM
    # 설명 참고). attach_transit=True로 바꿔 역세권도 이제 반영(과거엔 아파트만 적용했었는데,
    # complex_coords가 이미 빌라 좌표도 갖고 있어 추가 비용 없이 켤 수 있음 - train_one 내
    # 주석 참고). 이 3가지 변경 + is_single_house 버그 수정(clean_and_featurize 참고)이
    # 이번 개선의 전부임 - use_danji는 여전히 False(단지 단위로 쪼개면 표본이 너무 잘게
    # 쪼개져 불안정해지는 문제는 격자 그룹핑과 무관하게 그대로 유효).
    train_one(["villa_trades", "single_trades"], "villa_v1", "villa", use_danji=False, use_grid=True,
              attach_kapt=False, attach_transit=True, attach_school=True, attach_month_fe=True)


if __name__ == "__main__":
    main()
