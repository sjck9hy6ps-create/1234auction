#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K-apt(공동주택관리정보시스템) 단지특성 동기화 스크립트 - 2026-08 신규

## 왜 필요한가
AVM(train-avm.py)이 지금 쓰는 변수는 면적/층/연식/거래시점/위치(법정동·단지) 다섯 가지뿐임.
같은 단지·같은 평형이어도 세대수(대단지 프리미엄 - #232/#233에서 이미 규모보정 기능으로
효과가 실측된 바 있음)·시공사·난방방식 같은 "단지 자체의 특성"은 전혀 안 잡힘. 특히 이
효과는 표본이 부족해서 법정동/시군구 평균으로 승격(promote)된 신규·소규모 단지 예측에서
가장 크게 도움이 됨(표본이 충분한 단지는 이미 그 단지 자체 평균을 쓰므로 추가 정보가 필요
없음 - 아래 "왜 여기서 끝나는가" 참고).

## 이 스크립트가 하는 일 (1단계: 데이터 수집만)
국토교통부_공동주택 단지 목록제공 서비스(getSigunguAptList3)로 시군구별 단지 목록(단지코드+
단지명)을 가져오고, 국토교통부_공동주택 기본 정보제공 서비스(getAphusBassInfoV4)로 단지코드별
세대수·동수·난방방식·시공사·사용승인일·최고층수를 가져와 Supabase kapt_complex_info 테이블에
저장함. train-avm.py가 이 테이블을 조인해서 실제로 회귀 변수에 반영하는 건 다음 단계(2단계) -
먼저 이 스크립트로 실제 데이터가 어떤 모양으로 들어오는지(특히 as1~as4 필드가 정확히 무엇을
가리키는지 - 공식 문서에 필드별 설명이 없어 실제 응답으로 확인해야 함) 확인한 뒤 매칭 로직을
짜는 게 안전함.

## 왜 이걸로 AVM 오차가 줄어드는가 (danji가 아닌 dong/region으로 승격된 그룹에서만)
train-avm.py는 아파트를 danji(단지) 단위로 고정효과를 주는데, 세대수·시공사 등은 "그 단지의
불변 속성"이라 danji가 그대로 그룹키인 행들에서는 그룹 평균으로 이미 완전히 흡수되어 있음(같은
그룹 안에서 상수인 값은 FWL 중심화 후 정확히 0이 되어 회귀계수 추정에 아무 기여도 못 함).
반대로 danji 표본부족으로 dong/region 단위로 승격된 그룹(=지금 "⚠️ 표본부족" 경고가 뜨는 바로 그
경우)에서는 세대수 같은 변수가 그룹 내에서도 단지마다 다르게 남아있어 실제로 설명력을 가짐 -
즉 이 기능은 정확히 지금 신뢰도가 떨어지는 케이스를 보강하는 목적임.

## 페이지네이션/할당량 처리
실제 활용신청 결과 이 두 API 모두 일일 트래픽 5,000회로 승인됨(2026-08). 전국 약 250개
시군구 × 시군구당 수십~수백 개 단지(전국 총 1만5천~2만 개 추정)를 감안해 DAILY_DETAIL_CAP을
넉넉히 잡아도 여러 날에 걸쳐 나눠 처리하는 게 안전함(getSigunguAptList3 목록조회 호출도
같은 계정 트래픽을 같이 쓰므로). kapt_sync_state 테이블에 "현재 처리 중인 시군구 인덱스"를
저장해두고, 매 실행마다 DAILY_DETAIL_CAP개까지만 상세정보를 가져온 뒤 이어서 다음 실행에서
계속하는 방식으로 설계함(GitHub Actions 스케줄로 매일 자동 실행 - 전국 1회 완주에 약 1~2주
예상, 이후엔 그 상태로 월 1회씩 갱신해도 충분함 - 단지 특성은 거의 안 바뀌므로).

## 사용법
  python sync-kapt.py
환경변수 SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, PUBLIC_DATA_API_KEY 필요(GitHub Actions
시크릿으로 주입 - PUBLIC_DATA_API_KEY는 Vercel에 이미 등록된 것과 동일한 값을 GitHub Secrets에도
추가로 등록해야 함, train-avm.yml의 SUPABASE_* 시크릿과 같은 이유).
"""
import os
import sys
import json
from datetime import datetime, timezone

import requests

# ⚠️ 2026-08(K-apt 2단계 준비): train-avm.py도 같은 시군구코드→지역명 매핑이 필요해져서
# lawd_codes_py.py 공용 모듈로 뺐음(이 파일에 직접 박아두면 두 스크립트가 어긋날 위험).
from lawd_codes_py import LAWD_CODES

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
PUBLIC_DATA_API_KEY = os.environ.get("PUBLIC_DATA_API_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.", file=sys.stderr)
    sys.exit(1)
if not PUBLIC_DATA_API_KEY:
    print("ERROR: PUBLIC_DATA_API_KEY 환경변수가 필요합니다(GitHub Secrets에 추가 필요).", file=sys.stderr)
    sys.exit(1)

SB_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}
# ⚠️ 실제 활용신청 승인 화면(End Point)으로 확인한 정확한 경로 - Swagger 문서의
# "Base URL: apis.data.go.kr/1613000/"만 보고 짐작하면 서비스명 세그먼트(AptListService3/
# AptBasisInfoServiceV4)가 빠져 404가 남. 두 API가 서비스명이 서로 달라 base를 분리함.
KAPT_LIST_BASE = "https://apis.data.go.kr/1613000/AptListService3"
KAPT_BASS_BASE = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4"
DAILY_DETAIL_CAP = 2000  # 실행 1회당 getAphusBassInfoV4(상세정보) 최대 호출 수 - 일일 트래픽 5,000건 승인분 내에서 여유있게 설정


def sb_get(path: str):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def sb_upsert(table: str, rows: list, on_conflict: str):
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates"}
    r = requests.post(url, headers=headers, data=json.dumps(rows), timeout=30)
    if r.status_code >= 300:
        print(f"  ERROR upsert 실패({table}): {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()


def kapt_get(base: str, endpoint: str, params: dict):
    params = {**params, "serviceKey": PUBLIC_DATA_API_KEY}
    r = requests.get(f"{base}/{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    raw = r.json()
    # ⚠️ 2026-08(버그 수정): 공공데이터포털 API는 최상위에 "response" 래퍼가 있는 것과 없는 것이
    # 섞여 있음 - Swagger 문서의 예시 스키마는 래퍼 없이 {"header":..,"body":..}만 보여주지만
    # 실제 응답은 {"response":{"header":..,"body":..}}로 오는 경우가 흔함(첫 실행에서 서울
    # 종로구가 "0건 조회됨"으로 나온 원인 - 래퍼를 못 벗겨서 body를 못 찾았던 것으로 추정).
    # 둘 다 처리하도록 방어.
    data = raw.get("response", raw) if isinstance(raw, dict) else {}
    result_code = data.get("header", {}).get("resultCode")
    if result_code not in (None, "00", "0"):
        raise RuntimeError(f"{endpoint} 실패: {data.get('header')}")
    body = data.get("body") or {}
    if not body:
        print(f"  [디버그] {endpoint} body 없음 - 원본 응답: {json.dumps(raw, ensure_ascii=False)[:1500]}")
    return body


def fetch_sigungu_complex_list(sigungu_code: str) -> list:
    """getSigunguAptList3 - 시군구 내 전체 단지 목록(단지코드+단지명+주소필드)을 페이지네이션으로 수집."""
    items = []
    page = 1
    while True:
        body = kapt_get(KAPT_LIST_BASE, "getSigunguAptList3", {
            "sigunguCode": sigungu_code, "pageNo": page, "numOfRows": 200,
        })
        batch = body.get("items") or []
        # 공공데이터포털 응답은 item이 1건일 때 list가 아니라 dict로 오는 경우가 있어 방어
        if isinstance(batch, dict):
            batch = [batch]
        if not batch:
            break
        items.extend(batch)
        total = int(body.get("totalCount") or 0)
        if len(items) >= total or len(batch) < 200:
            break
        page += 1
    return items


def fetch_complex_detail(kapt_code: str) -> dict:
    """getAphusBassInfoV4 - 단지코드로 세대수/동수/난방방식/시공사/사용승인일/최고층수 조회."""
    body = kapt_get(KAPT_BASS_BASE, "getAphusBassInfoV4", {"kaptCode": kapt_code})
    return body.get("item") or {}


def to_int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


def main():
    state = sb_get("kapt_sync_state?id=eq.1&select=sigungu_idx")
    sigungu_idx = state[0]["sigungu_idx"] if state else 0
    if sigungu_idx >= len(LAWD_CODES):
        sigungu_idx = 0  # 전국 완주 후 처음부터 다시(월 1회 갱신 목적)

    sigungu_code, sigungu_name = LAWD_CODES[sigungu_idx]
    print(f"[sync-kapt] 진행 인덱스 {sigungu_idx}/{len(LAWD_CODES)} - {sigungu_code} {sigungu_name}")

    # 1) 이 시군구의 단지 목록을 우선 확보(기존에 없는 단지만 기본행 upsert, 상세정보는 아직 null)
    complex_list = fetch_sigungu_complex_list(sigungu_code)
    print(f"  단지 목록 {len(complex_list)}건 조회됨")
    if complex_list:
        # 첫 실행 디버그용 - as1~as4가 실제로 무엇을 담고 있는지 로그로 확인(문서에 필드 설명이 없음)
        sample = complex_list[0]
        print(f"  샘플 원본 응답: {json.dumps(sample, ensure_ascii=False)}")
        base_rows = [{
            "kapt_code": c.get("kaptCode"),
            "kapt_name": c.get("kaptName"),
            "sigungu_code": sigungu_code,
            "as1": c.get("as1"), "as2": c.get("as2"), "as3": c.get("as3"), "as4": c.get("as4"),
            "bjd_code": c.get("bjdCode"),
        } for c in complex_list if c.get("kaptCode")]
        # ignore-duplicates로 기존 상세정보(households 등)를 덮어쓰지 않음 - 이 upsert는 신규 단지
        # 등록 전용이고, 상세정보 채우기는 아래 2)단계에서 별도 update로 처리함.
        headers = {**SB_HEADERS, "Prefer": "resolution=ignore-duplicates"}
        url = f"{SUPABASE_URL}/rest/v1/kapt_complex_info?on_conflict=kapt_code"
        r = requests.post(url, headers=headers, data=json.dumps(base_rows), timeout=30)
        if r.status_code >= 300:
            print(f"  ERROR 기본행 upsert 실패: {r.status_code} {r.text}", file=sys.stderr)

    # 2) 이 시군구에서 아직 상세정보(households) 없는 단지를 하루 한도까지 채움
    pending = sb_get(
        f"kapt_complex_info?sigungu_code=eq.{sigungu_code}&households=is.null&select=kapt_code&limit={DAILY_DETAIL_CAP}"
    )
    print(f"  상세정보 미조회 단지 {len(pending)}건 (이번 실행 한도 {DAILY_DETAIL_CAP}건)")
    detailed = 0
    for row in pending:
        kapt_code = row["kapt_code"]
        try:
            detail = fetch_complex_detail(kapt_code)
        except Exception as e:
            print(f"    {kapt_code} 상세조회 실패: {e}", file=sys.stderr)
            continue
        if not detail:
            continue
        update_row = {
            "households": to_int(detail.get("kaptdaCnt")),
            "dong_cnt": to_int(detail.get("kaptDongCnt")),
            "heat_method": detail.get("codeHeatNm"),
            "construction_company": detail.get("kaptBcompany"),
            "use_approval_date": detail.get("kaptUsedate"),
            "top_floor": to_int(detail.get("kaptTopFloor")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        url = f"{SUPABASE_URL}/rest/v1/kapt_complex_info?kapt_code=eq.{kapt_code}"
        r = requests.patch(url, headers=SB_HEADERS, data=json.dumps(update_row), timeout=30)
        if r.status_code >= 300:
            print(f"    {kapt_code} 저장 실패: {r.status_code} {r.text}", file=sys.stderr)
        else:
            detailed += 1
    print(f"  상세정보 {detailed}건 저장 완료")

    # 3) 이 시군구를 다 처리했으면 다음 시군구로, 아니면(한도 초과로 남았으면) 같은 인덱스 유지
    remaining = sb_get(
        f"kapt_complex_info?sigungu_code=eq.{sigungu_code}&households=is.null&select=kapt_code&limit=1"
    )
    next_idx = sigungu_idx if remaining else sigungu_idx + 1
    patch_url = f"{SUPABASE_URL}/rest/v1/kapt_sync_state?id=eq.1"
    requests.patch(patch_url, headers=SB_HEADERS, data=json.dumps({
        "sigungu_idx": next_idx, "updated_at": datetime.now(timezone.utc).isoformat(),
    }), timeout=30)
    status = "이어서 처리 예정(한도 초과)" if remaining else "완료, 다음 시군구로 진행"
    print(f"[sync-kapt] {sigungu_code} {sigungu_name} {status} - 다음 실행 인덱스: {next_idx % len(LAWD_CODES)}")


if __name__ == "__main__":
    main()
