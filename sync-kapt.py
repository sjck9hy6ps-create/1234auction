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
국토교통부_공동주택 단지 목록제공 서비스(getSigunguAptList4)로 시군구별 단지 목록(단지코드+
단지명)을 가져오고, 국토교통부_공동주택 기본 정보제공 서비스(getAphusBassInfoV5)로 단지코드별
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
넉넉히 잡아도 여러 날에 걸쳐 나눠 처리하는 게 안전함(getSigunguAptList4 목록조회 호출도
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
import time
from datetime import datetime, timezone

import requests

# ⚠️ 2026-08(K-apt 2단계 준비): train-avm.py도 같은 시군구코드→지역명 매핑이 필요해져서
# lawd_codes_py.py 공용 모듈로 뺐음(이 파일에 직접 박아두면 두 스크립트가 어긋날 위험).
from lawd_codes_py import LAWD_CODES, LEGACY_CODES_BY_NAME

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
# "Base URL: apis.data.go.kr/1613000/"만 보고 짐작하면 서비스명 세그먼트(AptListService4/
# AptBasisInfoServiceV5)가 빠져 404가 남. 두 API가 서비스명이 서로 달라 base를 분리함.
# ⚠️ 2026-09(사용자 요청 "매도가능성 진단" 작업 중 발견 - 전 시군구 100% "400 Bad Request"
# 재현으로 판명): 이 스크립트를 처음 작성한 시점엔 AptListService3/getSigunguAptList3,
# AptBasisInfoServiceV4/getAphusBassInfoV4가 최신 버전이었는데, 그 뒤 공공데이터포털이 각각
# V4/V5로 버전을 올리면서 구버전 엔드포인트를 막아버림(활용신청 화면에서 실제 승인된
# End Point를 사용자가 직접 확인해줌: AptListService4, AptBasisInfoServiceV5). 새 버전으로
# 맞춰줌 - kaptdaCnt(세대수)/kaptDongCnt(동수)/codeHeatNm(난방방식)/kaptBcompany(시공사)/
# kaptUsedate(사용승인일) 필드명은 활용신청 화면의 V5 상세기능 설명과 일치해 그대로 둠.
# 다만 kaptTopFloor(최고층수)는 V5 설명 목록에 명시적으로 보이지 않아 확실하지 않음 - 이번
# 실행 로그(또는 [진단] 응답 본문)로 실제 응답에 이 필드가 있는지 한 번 더 확인 필요.
KAPT_LIST_BASE = "https://apis.data.go.kr/1613000/AptListService4"
KAPT_BASS_BASE = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV5"
DAILY_DETAIL_CAP = 4000  # 2026-10: 2,000→4,000(목록조회 최대 60건 포함해도 일일 승인 5,000건 이내)  # 실행 1회당 getAphusBassInfoV5(상세정보) 최대 호출 수 - 일일 트래픽 5,000건 승인분 내에서 여유있게 설정


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


class QuotaExceededError(Exception):
    """공공데이터포털 일일 호출 한도(resultCode=22) 초과 - 재시도/시군구 건너뛰기로는
    해결이 안 되므로 이번 실행 자체를 즉시 멈추는 용도의 전용 예외."""
    pass


def kapt_get(base: str, endpoint: str, params: dict):
    params = {**params, "serviceKey": PUBLIC_DATA_API_KEY}
    # ⚠️ 2026-09(버그 수정): 실제 GitHub Actions 실행 로그로 확인 - 253개 시군구 중 인덱스
    # 10(서울 노원구)에서 apis.data.go.kr 접속이 타임아웃으로 실패하면 예외가 그대로 위로
    # 전파되어 그날 실행 전체가 크래시했음(재시도 없음). sigungu_idx는 실패 시 안 넘어가서
    # 다음날 다시 같은 시군구부터 재시도는 되지만, 공공데이터포털 서버가 간헐적으로 느리거나
    # 일시적으로 응답이 늦는 경우(해외/CI 환경에서 흔함) 매번 그 순간에 걸리면 영영 못 넘어갈
    # 수 있음 - 그래서 딱 이 지점(네트워크 요청 자체)에만 지수백오프 재시도를 추가함. 성공한
    # 이후의 로직(응답 파싱 등)은 원래대로 그대로 두고 예외를 던짐.
    last_err = None
    for attempt in range(4):  # 최대 4회 시도(최초 1회 + 재시도 3회)
        try:
            r = requests.get(f"{base}/{endpoint}", params=params, timeout=45)
            # ⚠️ 2026-09(사용자 요청 "매도가능성 진단" 작업 중 발견 - 실제 GitHub Actions 로그로
            # 확인): 253개 시군구 전부가 예외 없이 매번 "400 Client Error: Bad Request"로
            # 실패하고 있었음(일부만 실패하는 할당량/네트워크 문제가 아니라 100% 재현). 기존
            # 코드는 r.raise_for_status()가 던진 requests.exceptions.HTTPError의 기본 메시지만
            # 로그에 남겨서 "왜" 거부됐는지(서비스키 미등록/활용신청 미승인/키 형식 오류 등)를
            # 전혀 알 수 없었음 - 공공데이터포털은 이런 인증 단계 오류를 200+JSON이 아니라
            # HTTP 400/401 + XML 본문(SERVICE_KEY_IS_NOT_REGISTERED_ERROR 등)으로 돌려주는
            # 경우가 흔해서, 아래 resultCode 분기(라인 133~)에 도달하기도 전에 raise_for_status()
            # 에서 막혀버림. 그래서 4xx/5xx일 때는 재시도 전에 실제 응답 본문(r.text)을 먼저
            # 출력해서, 다음 실행 로그만 보면 정확한 원인이 바로 드러나게 함(추측성 진단 반복을
            # 막기 위함). 4xx는 재시도해도 같은 이유로 계속 실패할 뿐이므로(네트워크 일시
            # 장애가 아니라 인증/설정 문제) 즉시 예외를 던지고 재시도 루프를 돌지 않음 - 5xx만
            # (일시적 서버 문제일 수 있으므로) 기존처럼 재시도함.
            if r.status_code >= 400:
                print(f"    [진단] {endpoint} HTTP {r.status_code} 응답 본문: {r.text[:1000]}", file=sys.stderr)
                if r.status_code < 500:
                    r.raise_for_status()  # 4xx는 재시도해도 의미 없음 - 바로 위로 던짐
            r.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 3:
                wait = 5 * (attempt + 1)  # 5s, 10s, 15s
                print(f"    [재시도 {attempt + 1}/3] {endpoint} 요청 실패({e.__class__.__name__}) - {wait}초 후 재시도", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raw = r.json()
    # ⚠️ 2026-08(버그 수정): 공공데이터포털 API는 최상위에 "response" 래퍼가 있는 것과 없는 것이
    # 섞여 있음 - Swagger 문서의 예시 스키마는 래퍼 없이 {"header":..,"body":..}만 보여주지만
    # 실제 응답은 {"response":{"header":..,"body":..}}로 오는 경우가 흔함(첫 실행에서 서울
    # 종로구가 "0건 조회됨"으로 나온 원인 - 래퍼를 못 벗겨서 body를 못 찾았던 것으로 추정).
    # 둘 다 처리하도록 방어.
    data = raw.get("response", raw) if isinstance(raw, dict) else {}
    result_code = data.get("header", {}).get("resultCode")
    if result_code not in (None, "00", "0"):
        # ⚠️ (2026-09, 사용자 문의 대응 - "할당량 등 과거 에러 다 보완됐냐"): 공공데이터포털은
        # 일일 호출 한도를 다 쓰면 HTTP 에러가 아니라 200 응답 안에 resultCode="22"
        # (LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR)를 담아서 줌 - 이 경우는 재시도
        # 해봐야(위 kapt_get 백오프는 네트워크 예외에만 걸림) 절대 안 풀리고, 이 시군구만
        # 건너뛰는 것도 의미 없음(오늘 남은 모든 호출이 다 이 코드로 실패할 것이므로). 이런
        # 단지별로 계속 실패 호출을 쌓는 대신, 별도 예외로 구분해서 위(process_one_sigungu/
        # main)에서 오늘 실행 자체를 즉시 멈추게 함 - 이미 처리한 진행분은 그대로 저장돼
        # 있으므로 내일 이어서 하면 됨(getSigunguAptList4/getAphusBassInfoV5는 같은 계정
        # 트래픽을 공유하므로, 다른 스크립트가 먼저 할당량을 많이 썼다면 이 코드가 실제로
        # 발생할 수 있음).
        if result_code == "22":
            raise QuotaExceededError(f"{endpoint} 일일 호출 한도 초과(resultCode=22)")
        raise RuntimeError(f"{endpoint} 실패: {data.get('header')}")
    body = data.get("body") or {}
    if not body:
        print(f"  [디버그] {endpoint} body 없음 - 원본 응답: {json.dumps(raw, ensure_ascii=False)[:1500]}")
    return body


def fetch_sigungu_complex_list(sigungu_code: str) -> list:
    """getSigunguAptList4 - 시군구 내 전체 단지 목록(단지코드+단지명+주소필드)을 페이지네이션으로 수집."""
    items = []
    page = 1
    while True:
        body = kapt_get(KAPT_LIST_BASE, "getSigunguAptList4", {
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
    """getAphusBassInfoV5 - 단지코드로 세대수/동수/난방방식/시공사/사용승인일/최고층수 조회."""
    body = kapt_get(KAPT_BASS_BASE, "getAphusBassInfoV5", {"kaptCode": kapt_code})
    return body.get("item") or {}


def to_int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


MAX_SIGUNGU_PER_RUN = 60  # 안전장치 - 상세정보가 이미 다 채워진 시군구(재순환 구간)가 여러 개
# 연달아 나오면 detail 호출이 거의 없어 순식간에 다음 시군구로 넘어가므로, list 조회
# (getSigunguAptList4)만 너무 많이 쏘지 않도록 한 실행에서 처리하는 시군구 수 자체에도 상한을 둠.


def process_one_sigungu(sigungu_idx: int, detail_budget: int):
    """시군구 하나를 처리함(목록 확보 + 상세정보를 최대 detail_budget건까지).
    반환: (이번에 실제로 사용한 상세조회 건수, 이 시군구를 완료했는지 여부, 일일 할당량
    초과를 만났는지 여부).
    완료 = households가 아직 null인 단지가 이 시군구에 하나도 안 남음. 목록조회 자체가
    (할당량 문제가 아닌 이유로) 실패한 경우도 "완료" 취급해 다음 시군구로 넘어감(다음 전국
    순환 때 다시 시도되므로 영구 누락은 아님 - 기존 단일 시군구 로직과 동일한 정책)."""
    sigungu_code, sigungu_name = LAWD_CODES[sigungu_idx]
    print(f"[sync-kapt] 진행 인덱스 {sigungu_idx}/{len(LAWD_CODES)} - {sigungu_code} {sigungu_name}")

    # 1) 이 시군구의 단지 목록을 우선 확보(기존에 없는 단지만 기본행 upsert, 상세정보는 아직 null)
    # ⚠️ 2026-09(2차 버그 수정): 재시도(위 kapt_get의 4회 백오프)를 추가했는데도 서울 노원구
    # (11350)에서 매번 4번 다 타임아웃으로 실패 - 이건 "가끔 느림" 수준이 아니라 이 시군구
    # 하나가 지속적으로 막혀있다는 뜻(원인은 apis.data.go.kr 쪽 문제로 추정, 이 코드로는 통제
    # 불가). 문제는 이 목록조회 자체가 예외를 던지면 sigungu_idx가 절대 못 넘어가서 전체
    # 파이프라인이 이 시군구 하나에 영원히 멈춰버림(대장아파트는 늘 존재해야 한다는 설계
    # 원칙과 동일하게, 이 동기화도 한 시군구 때문에 전체가 멈추면 안 됨) - 그래서 목록조회
    # 실패는 더 이상 크래시시키지 않고, 이 시군구를 이번 실행만 건너뛰고 다음 시군구로 진행함
    # (다음 달 전국 재순환 때 다시 시도되므로 영구 누락은 아님).
    try:
        complex_list = fetch_sigungu_complex_list(sigungu_code)
        # ⚠️ 2026-10: 행정구역 개편(전남광주 통합, 강원·전북 특별자치도, 화성 분구)으로 국토부 실거래는 새
        # 코드가 됐지만 K-apt는 옛 코드로만 단지가 나오는 지역이 있음 - 새 코드로 0건이면 옛 코드로 다시 조회.
        # 저장은 항상 새 코드(sigungu_code)로 함(data-coverage.js가 새 코드로 세대수를 찾음).
        if not complex_list:
            for old_code in LEGACY_CODES_BY_NAME.get(sigungu_name, []):
                got = fetch_sigungu_complex_list(old_code)
                print(f"  새 코드로 0건 → 옛 코드 {old_code}로 {len(got)}건 조회")
                complex_list.extend(got)
    except QuotaExceededError:
        # ⚠️ 할당량 초과는 "이 시군구만의 문제"가 아니라 오늘 남은 모든 호출이 다 같은 이유로
        # 실패할 상황임 - 이 시군구는 하나도 진행 못 했으니 인덱스도 그대로 두고(done=False),
        # quota_hit=True로 main()에 알려 오늘 실행을 여기서 멈추게 함.
        print(f"  일일 할당량 초과로 {sigungu_code} {sigungu_name} 목록조회부터 실패 - 오늘 실행을 멈춥니다.", file=sys.stderr)
        return 0, False, True
    except Exception as e:
        print(f"  ERROR 단지 목록 조회 실패({sigungu_code} {sigungu_name}): {e}", file=sys.stderr)
        print(f"  이 시군구는 이번 실행에서 건너뛰고 다음 시군구로 진행합니다(다음 순환에서 재시도됨).")
        return 0, True, False
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

    # 2) 이 시군구에서 아직 상세정보(households) 없는 단지를, 이번 실행에 남은 예산까지만 채움
    pending = sb_get(
        f"kapt_complex_info?sigungu_code=eq.{sigungu_code}&households=is.null&select=kapt_code&limit={max(detail_budget, 0)}"
    )
    print(f"  상세정보 미조회 단지 {len(pending)}건 (이번 실행에 남은 상세조회 한도 {detail_budget}건)")
    detailed = 0
    quota_hit = False
    for row in pending:
        kapt_code = row["kapt_code"]
        try:
            detail = fetch_complex_detail(kapt_code)
        except QuotaExceededError:
            # ⚠️ 상세조회 도중 할당량이 바닥나면, 남은 단지들도 다 같은 이유로 실패할 것이므로
            # 헛되이 계속 호출하지 않고 여기서 바로 중단함 - 지금까지 성공한 detailed건수는
            # 그대로 유지되어 저장되고, 이 시군구는 아래 "완료 여부" 체크에서 자연히
            # done=False(할 일이 남음)로 판정돼 다음 실행(내일, 할당량이 리셋된 뒤) 같은
            # 인덱스로 이어서 처리됨.
            print(f"    상세조회 중 일일 할당량 초과 감지 - 이번 실행을 여기서 멈춥니다(내일 이어서 처리됨).", file=sys.stderr)
            quota_hit = True
            break
        except Exception as e:
            print(f"    {kapt_code} 상세조회 실패: {e}", file=sys.stderr)
            continue
        if not detail or not detail.get("kaptCode"):
            # ⚠️ 2026-10: 상세정보가 비어 오는 단지(예: 아산 'test001' 같은 시험용 등록)는 영원히 안 채워져서
            # 이 시군구가 "미완료"로 남고 매일 같은 자리만 다시 도는 문제가 있었음(9/28부터 정지) - 세대수 0으로
            # 표시해 "확인함" 처리하고 넘어감(0은 회전율 계산에서 자동 제외됨).
            requests.patch(f"{SUPABASE_URL}/rest/v1/kapt_complex_info?kapt_code=eq.{kapt_code}", headers=SB_HEADERS,
                           data=json.dumps({"households": 0, "updated_at": datetime.now(timezone.utc).isoformat()}), timeout=30)
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

    # 3) 이 시군구를 다 처리했는지 확인
    remaining = sb_get(
        f"kapt_complex_info?sigungu_code=eq.{sigungu_code}&households=is.null&select=kapt_code&limit=1"
    )
    done = not remaining
    status = "완료, 다음 시군구로 진행" if done else "이어서 처리 예정(한도 초과)"
    print(f"[sync-kapt] {sigungu_code} {sigungu_name} {status}")
    return detailed, done, quota_hit


def main():
    # ⚠️ (2026-09, 사용자 문의 대응 - "전국 완주 언제 되냐"): 원래 이 함수는 실행 1번마다
    # 시군구를 딱 1개만 처리하고 끝났음(그 시군구 단지가 하루 한도(2,000건)보다 훨씬 적어도
    # 다음 시군구로 안 넘어가고 그냥 종료) - 진짜 병목이 "하루 API 할당량"이 아니라 "하루에
    # 한 번 도는 실행 자체"였음. 실측 확인 결과 253개 시군구 중 19개만 처리된 상태(하루 1개
    # 페이스와 일치) - 이대로면 전국 1회 완주에 약 230일(7개월+)이 걸려, 스크립트 설계
    # 당시의 목표치("1~2주")와 완전히 어긋남. 승인받은 일일 상세조회 한도(DAILY_DETAIL_CAP=
    # 2,000건)를 실제로 다 쓸 때까지 여러 시군구를 이어서 처리하도록 while 루프로 바꿈 -
    # 시군구 하나를 처리할 때마다 곧바로 kapt_sync_state를 갱신해두므로(기존과 동일), 중간에
    # 실행이 죽어도(타임아웃 등) 이미 처리한 시군구만큼은 그대로 보존됨. list 조회
    # (getSigunguAptList4)가 시군구마다 1번씩 추가로 붙지만, MAX_SIGUNGU_PER_RUN(60개)
    # 상한을 같이 둬서 list+detail 합계가 일일 승인량(5,000건)을 넘지 않도록 안전하게 잡음.
    state = sb_get("kapt_sync_state?id=eq.1&select=sigungu_idx")
    sigungu_idx = state[0]["sigungu_idx"] if state else 0
    if os.environ.get("KAPT_START_IDX", "").strip().isdigit():
        sigungu_idx = int(os.environ["KAPT_START_IDX"].strip())
        print(f"[sync-kapt] 시작 인덱스를 {sigungu_idx}로 지정해 실행")
    if sigungu_idx >= len(LAWD_CODES):
        sigungu_idx = 0  # 전국 완주 후 처음부터 다시(월 1회 갱신 목적)

    total_detail_used = 0
    sigungu_run_count = 0
    while total_detail_used < DAILY_DETAIL_CAP and sigungu_run_count < MAX_SIGUNGU_PER_RUN:
        if sigungu_idx >= len(LAWD_CODES):
            sigungu_idx = 0  # 이번 실행 중에 전국을 다 돌았으면 처음부터 다시

        remaining_budget = DAILY_DETAIL_CAP - total_detail_used
        detail_used, done, quota_hit = process_one_sigungu(sigungu_idx, remaining_budget)
        total_detail_used += detail_used
        sigungu_run_count += 1

        next_idx = (sigungu_idx + 1) if done else sigungu_idx
        # 시군구 하나 끝날 때마다 즉시 저장 - 이번 실행이 도중에 실패해도 이미 처리한 진행분은
        # 유지됨(예전처럼 실행 맨 끝에서 한 번만 저장하면, 중간에 죽었을 때 이번 실행에서
        # 처리한 시군구들이 전부 다시 처리돼야 함).
        patch_url = f"{SUPABASE_URL}/rest/v1/kapt_sync_state?id=eq.1"
        requests.patch(patch_url, headers=SB_HEADERS, data=json.dumps({
            "sigungu_idx": next_idx % len(LAWD_CODES), "updated_at": datetime.now(timezone.utc).isoformat(),
        }), timeout=30)

        if quota_hit:
            # ⚠️ (2026-09, 사용자 문의 대응 - "할당량 에러까지 다 보완됐냐"): 일일 할당량이
            # 이미 바닥난 상태에서 남은 시군구를 계속 시도해봐야 전부 같은 이유로 실패할 뿐이라,
            # 여기서 즉시 실행을 끝냄(다음 시군구 목록조회조차 하지 않음 - 불필요한 실패 호출을
            # 더 쌓지 않기 위함). 할당량은 하루 단위로 리셋되므로 내일 실행이 같은 인덱스로
            # 자동으로 이어서 처리함 - 별도 조치 필요 없음.
            print("[sync-kapt] 일일 할당량 초과로 이번 실행을 조기 종료합니다 - 내일 자동으로 이어서 처리됩니다.")
            break
        if not done:
            # 이 시군구 하나가 이번 실행의 남은 상세조회 예산을 다 써버려서 못 끝났다는 뜻
            # (그만큼 큰 시군구) - 여기서 실행을 마치고, 다음 실행이 같은 인덱스로 이어서 처리함.
            break
        sigungu_idx = next_idx

    print(f"[sync-kapt] 이번 실행 요약: 시군구 {sigungu_run_count}개 처리, 상세조회 {total_detail_used}건 사용"
          f"(한도 {DAILY_DETAIL_CAP}건) - 다음 실행 시작 인덱스: {sigungu_idx % len(LAWD_CODES)}")


if __name__ == "__main__":
    main()
