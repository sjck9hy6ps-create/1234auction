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
  1) 종속변수(y)와 설명변수(X)를 각각 "자기 법정동 평균"만큼 빼서 중심화(demean)함
  2) 중심화된 데이터로 회귀하면, 법정동 더미를 실제로 넣은 것과 수학적으로 완전히 동일한
     계수(β)가 나옴(고전적인 패널데이터 계량경제학 기법) - 그런데 계산량은 훨씬 적음
  3) 법정동별 절편(그 동네 고유의 기본 수준)은 "그 동네 y 평균 - 그 동네 X 평균·β"로 뒤에서
     따로 구함
이렇게 하면 "법정동 고정효과 + 연속변수(면적/층/연식/시점) 회귀"를 동시에 반영하면서도
행렬 크기는 변수 개수(6개)만큼만 유지됨.

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
import sys
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

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

# ⚠️ 표본이 극단적으로 적은 법정동(< MIN_DONG_SAMPLES)은 FWL 중심화 자체가 불안정해짐
# (거래 1~2건짜리 동은 "그 동의 평균"이 곧 그 거래 자체라 회귀에 아무 정보도 안 남음).
# 이런 동은 법정동 자체를 시/군/구 단위로 묶어(더 큰 그룹) 표본을 확보함.
MIN_DONG_SAMPLES = 5
MAX_AGE_YEARS = 60  # 이보다 오래된 건 데이터 오류로 보고 제외
PAGE_SIZE = 1000


def fetch_all_rows(table: str) -> pd.DataFrame:
    """Supabase REST API에서 페이지네이션으로 전체 행을 가져옴."""
    cols = "region,dong,danji,price,size,floor,deal_date,build_year"
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


def clean_and_featurize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
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

    # 표본 부족 동은 시/군/구(region) 단위로 그룹을 승격 - region은 "서울특별시 강남구"
    # 처럼 이미 시군구 단위 문자열이라 이 자체를 그룹키로 씀.
    df["group_key"] = df["region"].astype(str) + "|" + df["dong"].astype(str)
    counts = df["group_key"].value_counts()
    small_groups = counts[counts < MIN_DONG_SAMPLES].index
    df.loc[df["group_key"].isin(small_groups), "group_key"] = df.loc[df["group_key"].isin(small_groups), "region"]

    return df


FEATURE_COLS = ["log_size", "floor", "floor2", "age", "age2", "time_trend"]


def fit_fwl(df: pd.DataFrame):
    """Frisch-Waugh-Lovell 고정효과 회귀. 반환: (beta dict, group_effects dict, r_squared, n)"""
    group_means = df.groupby("group_key")[["y"] + FEATURE_COLS].transform("mean")
    y_tilde = (df["y"] - group_means["y"]).to_numpy()
    X_tilde = (df[FEATURE_COLS] - group_means[FEATURE_COLS]).to_numpy()

    # 최소제곱해 (X_tilde^T X_tilde) beta = X_tilde^T y_tilde
    beta, residuals, rank, sv = np.linalg.lstsq(X_tilde, y_tilde, rcond=None)
    beta_dict = {name: float(b) for name, b in zip(FEATURE_COLS, beta)}

    # 그룹별 절편 = 그 그룹의 y평균 - 그 그룹의 X평균·beta
    group_agg = df.groupby("group_key")[FEATURE_COLS + ["y"]].mean()
    group_agg["pred_no_intercept"] = group_agg[FEATURE_COLS].to_numpy() @ beta
    group_agg["effect"] = group_agg["y"] - group_agg["pred_no_intercept"]
    group_effects = group_agg["effect"].to_dict()

    # 전체 예측치로 R^2 계산
    df2 = df.copy()
    df2["group_effect"] = df2["group_key"].map(group_effects)
    y_pred = df2[FEATURE_COLS].to_numpy() @ beta + df2["group_effect"].to_numpy()
    ss_res = float(np.sum((df2["y"].to_numpy() - y_pred) ** 2))
    ss_tot = float(np.sum((df2["y"].to_numpy() - df2["y"].mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else None

    return beta_dict, {str(k): float(v) for k, v in group_effects.items()}, r_squared, len(df2)


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


def train_one(table: str, model_id: str, model_type: str):
    print(f"[{model_id}] {table} 학습 시작")
    raw = fetch_all_rows(table)
    if raw.empty:
        print(f"  {table}: 데이터 없음, 스킵")
        return
    df = clean_and_featurize(raw)
    print(f"  전처리 후 {len(df)}행 (그룹 {df['group_key'].nunique()}개)")
    if len(df) < 200:
        print(f"  표본이 너무 적어({len(df)}행) 학습을 건너뜁니다(최소 200건 필요).")
        return
    beta, group_effects, r_squared, n = fit_fwl(df)
    # time_origin: time_trend 계산의 기준일(가장 오래된 거래일, YYYYMMDD 정수). 예측 시점(서버)
    # 에서도 "오늘 - time_origin" 일수로 같은 time_trend를 계산해야 학습 때와 정의가 일치하므로
    # 반드시 같이 저장해야 함(빠뜨리면 시점보정 계수가 엉뚱한 기준으로 적용되는 버그가 됨).
    feature_ranges = {
        "size": [float(df["size"].min()), float(df["size"].max())],
        "floor": [float(df["floor"].min()), float(df["floor"].max())],
        "age": [float(df["age"].min()), float(df["age"].max())],
        "time_origin": int(df["deal_date"].min()),
    }
    upsert_model(model_id, model_type, beta, group_effects, r_squared, n, feature_ranges)


def main():
    # ⚠️ 2026-08 v1: 아파트(house_trades)만 우선 학습함. 연립다세대(villa_trades/single_trades)는
    # 거래 빈도가 원래 낮아 그룹별(동별) 표본이 훨씬 더 부족함 - v1 배포 후 실제 R^2·표본수를
    # 보고 별도로 그룹 승격 기준(MIN_DONG_SAMPLES)을 더 크게 잡아 재검토할 예정.
    train_one("house_trades", "apt_v1", "apt")


if __name__ == "__main__":
    main()
