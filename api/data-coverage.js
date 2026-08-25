/* ════════════════════════════════════
   데이터 수집 범위 조회 API
   - 아파트 매매/전월세, 연립다세대·단독다가구 매매/전월세 4개 카테고리의
     최소~최대 deal_date(수집된 데이터 범위)와 건수를 반환합니다.
   - 프론트엔드 지도 화면에 "데이터 수집 범위" 표시 + 과거 데이터 추가 시
     알림 기능에 사용됩니다.

   ── mode=baseRate: 한국은행 기준금리 추세 (2026-08 추가) ──
   예상매도가 계산(calcMarketAdjustedSalePrice, index.html)의 "호가 반영비중"은 지금
   매물재고÷월평균실거래건수(재고월수)로만 정해지는데, 이건 순전히 개별 물건 주변의
   국지적 수급 신호라 "금리가 오르는 중이라 매수심리 전체가 위축되고 있다" 같은 거시적
   흐름은 못 잡아냄. 한국은행 ECOS 기준금리(통계표코드 722Y001, 항목코드 0101000)를
   최근 13개월치 가져와서 "1년 전 대비 오름세/내림세/보합"을 판정해두면, 프론트에서
   금리 상승기엔 호가 반영비중을 살짝 낮추고(매도자 눈높이가 아직 안 낮춰졌을 가능성을
   경계) 하락기엔 살짝 올리는 식의 참고용 보정치로 쓸 수 있음. 통계적으로 검증된
   관계식이 아니라 정성적 방향성만 참고하는 용도라, 프론트 반영 시에도 아주 작은
   폭(예: marketFactor ±0.05)으로만 조정하고 "참고용" 표시를 반드시 같이 해야 함.
   ⚠️ 기준금리는 통화정책방향회의(연 8회, 약 1.5개월 간격)에서만 바뀌므로 자주 조회할
   필요가 없음 - Supabase에 24시간 캐시.
   ⚠️ 아래 SQL을 Supabase에 먼저 한 번 실행해서 캐시 테이블을 만들어야 합니다:
     create table if not exists ecos_base_rate_cache (
       id text primary key,
       current_rate numeric,
       rate_time text,
       rate_12m_ago numeric,
       trend text,
       history jsonb,
       fetched_at timestamptz
     );
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import { LAWD_CODES } from '../scripts/lawd-codes.mjs';
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

// 테이블이 아직 없거나(예: villa_rent/single_rent 생성 전) 비어있어도 에러 없이 null로 처리
// min/max/count를 서로 독립적으로 조회함 - 행이 많은 테이블(house_trades 등)에서
// count 쿼리 하나가 느리거나 실패해도 min/max까지 같이 null이 되지 않도록 함
// ⚠️ 2026-08: house_rent가 count(87만여건)는 정상인데 min/max만 계속 null로 나오는 현상이
// 있었음 - 원인이 console.warn(서버 로그, 프론트에선 못 봄)에만 찍혀서 진단이 안 됐던 것이라,
// 실패 시 이유를 result.warnings에 담아 응답 JSON에도 그대로 노출시킴(임시 디버그용이 아니라
// 앞으로도 이런 조회 실패를 화면에서 바로 알아챌 수 있게 상시 유지).
async function getRange(table) {
  const result = { min: null, max: null, count: 0, warnings: [] };

  try {
    const { data: minRow, error: e1 } = await supabase
      .from(table).select('deal_date').not('deal_date', 'is', null)
      .order('deal_date', { ascending: true }).limit(1);
    if (e1) { console.warn(`data-coverage: ${table} min 조회 실패 -`, e1.message); result.warnings.push(`min 조회 실패: ${e1.message}`); }
    else if (minRow && minRow[0]) result.min = minRow[0].deal_date;
    else result.warnings.push('min 조회는 성공했으나 결과 행이 0건(deal_date가 전부 null이거나 데이터 없음)');
  } catch (e) { console.warn(`data-coverage: ${table} min 조회 예외 -`, e.message); result.warnings.push(`min 조회 예외: ${e.message}`); }

  try {
    const { data: maxRow, error: e2 } = await supabase
      .from(table).select('deal_date').not('deal_date', 'is', null)
      .order('deal_date', { ascending: false }).limit(1);
    if (e2) { console.warn(`data-coverage: ${table} max 조회 실패 -`, e2.message); result.warnings.push(`max 조회 실패: ${e2.message}`); }
    else if (maxRow && maxRow[0]) result.max = maxRow[0].deal_date;
    else result.warnings.push('max 조회는 성공했으나 결과 행이 0건(deal_date가 전부 null이거나 데이터 없음)');
  } catch (e) { console.warn(`data-coverage: ${table} max 조회 예외 -`, e.message); result.warnings.push(`max 조회 예외: ${e.message}`); }

  try {
    // 'exact'는 큰 테이블에서 느려서 타임아웃 위험이 있어 'estimated'(추정치, 빠름)로 변경
    const { count, error: e3 } = await supabase
      .from(table).select('*', { count: 'estimated', head: true });
    if (e3) { console.warn(`data-coverage: ${table} count 조회 실패 -`, e3.message); result.warnings.push(`count 조회 실패: ${e3.message}`); }
    else result.count = count || 0;
  } catch (e) { console.warn(`data-coverage: ${table} count 조회 예외 -`, e.message); result.warnings.push(`count 조회 예외: ${e.message}`); }

  return result;
}

function mergeRanges(a, b) {
  const mins = [a.min, b.min].filter(v => v !== null);
  const maxs = [a.max, b.max].filter(v => v !== null);
  return {
    min: mins.length ? Math.min(...mins) : null,
    max: maxs.length ? Math.max(...maxs) : null,
    count: (a.count || 0) + (b.count || 0),
    warnings: [...(a.warnings || []), ...(b.warnings || [])],
  };
}

/* ════════════════════════════════════
   한국은행 ECOS 기준금리 추세 (mode=baseRate) - 파일 상단 주석 참고
════════════════════════════════════ */
const ECOS_API_KEY = process.env.ECOS_API_KEY;
const ECOS_BASE_URL = 'https://ecos.bok.or.kr/api/StatisticSearch';
const BASE_RATE_STAT_CODE = '722Y001'; // 한국은행 기준금리
const BASE_RATE_ITEM_CODE = '0101000';
const BASE_RATE_CACHE_ID = 'latest'; // 단일 값(지역 구분 없음)이라 캐시 테이블에 행 1개만 씀
const BASE_RATE_FRESH_MS = 1000 * 60 * 60 * 24; // 24시간 - 통화정책방향회의(연 8회)때만 바뀌는 값이라 자주 조회할 필요 없음

function yyyymm(d) {
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/* ECOS StatisticSearch 응답은 정상일 때 {StatisticSearch:{row:[...]}}, 인증키 오류나
   데이터 없음일 때 {RESULT:{CODE,MESSAGE}}로 형태 자체가 달라짐 - 둘 다 방어적으로 처리. */
async function fetchEcosBaseRateHistory() {
  const end = new Date();
  const start = new Date(end.getFullYear(), end.getMonth() - 13, 1); // 여유있게 14개월치 요청(최소 13개월 필요)
  const url = `${ECOS_BASE_URL}/${ECOS_API_KEY}/json/kr/1/100/${BASE_RATE_STAT_CODE}/M/${yyyymm(start)}/${yyyymm(end)}/${BASE_RATE_ITEM_CODE}`;
  let data;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
    data = await r.json();
  } catch (e) {
    return { error: 'ECOS 호출 실패: ' + e.message };
  }
  if (data && data.RESULT) {
    return { error: 'ECOS 오류: ' + (data.RESULT.MESSAGE || data.RESULT.CODE), raw: data };
  }
  const rows = data && data.StatisticSearch && data.StatisticSearch.row;
  if (!Array.isArray(rows) || !rows.length) {
    return { error: 'ECOS 응답에 데이터가 없습니다.', raw: data };
  }
  const sorted = rows.slice().sort((a, b) => String(a.TIME).localeCompare(String(b.TIME)));
  const history = sorted.map(row => ({ time: row.TIME, value: parseFloat(row.DATA_VALUE) })).filter(h => Number.isFinite(h.value));
  if (!history.length) return { error: 'ECOS 응답 값을 숫자로 변환하지 못했습니다.', raw: data };
  const current = history[history.length - 1];
  const yearAgo = history.length >= 13 ? history[history.length - 13] : history[0];
  let trend = 'flat';
  if (current.value > yearAgo.value) trend = 'up';
  else if (current.value < yearAgo.value) trend = 'down';
  return {
    currentRate: current.value, currentTime: current.time,
    rate12mAgo: yearAgo.value, trend, history,
  };
}

async function getBaseRateTrend(force) {
  if (!ECOS_API_KEY) return { error: 'ECOS_API_KEY 환경변수가 없습니다. ecos.bok.or.kr에서 발급받은 인증키를 Vercel에 추가해 주세요.' };
  if (!force) {
    try {
      const { data: cached, error } = await supabase
        .from('ecos_base_rate_cache').select('*').eq('id', BASE_RATE_CACHE_ID).maybeSingle();
      if (error) console.warn('ecos_base_rate_cache 조회 실패:', error.message);
      else if (cached && (Date.now() - new Date(cached.fetched_at).getTime()) < BASE_RATE_FRESH_MS) {
        return {
          currentRate: cached.current_rate, currentTime: cached.rate_time,
          rate12mAgo: cached.rate_12m_ago, trend: cached.trend, history: cached.history, cached: true,
        };
      }
    } catch (e) { console.warn('ecos_base_rate_cache 조회 예외:', e.message); }
  }
  const fresh = await fetchEcosBaseRateHistory();
  if (fresh.error) return fresh;
  try {
    const { error: upsertErr } = await supabase.from('ecos_base_rate_cache').upsert({
      id: BASE_RATE_CACHE_ID,
      current_rate: fresh.currentRate, rate_time: fresh.currentTime,
      rate_12m_ago: fresh.rate12mAgo, trend: fresh.trend, history: fresh.history,
      fetched_at: new Date().toISOString(),
    });
    if (upsertErr) console.warn('ecos_base_rate_cache 저장 실패:', upsertErr.message);
  } catch (e) { console.warn('ecos_base_rate_cache 저장 예외:', e.message); }
  return { ...fresh, cached: false };
}

/* ════════════════════════════════════
   한국부동산원 R-ONE 매매/전세가격지수 추세 (mode=roneIndex) - 2026-08 추가
   ECOS 기준금리와 같은 취지 - 실거래 기반 비교물건 시세는 그 지역의 "최근 실거래"만
   반영하므로, R-ONE이 매월 공식 발표하는 전국/시도 단위 매매·전세가격지수로 "그 시/도
   전체가 최근 1년간 얼마나 올랐는지"라는 광역 추세를 보완함. 참고용 정성적 보정치로만
   씀(marketFactor ±0.05, ECOS와 합쳐도 ±0.08로 상한).
   ⚠️ 아래는 실제 라이브 호출로 확인한 내용(2026-08):
   - 요청: https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do?STATBL_ID=...&DTACYCLE_CD=MM
     &WRTTIME_IDTFR_ID=YYYYMM&Type=json&KEY=인증키
   - 통계표코드: 아파트 매매지수(지역별)=A_2024_00178, 아파트 전세지수(지역별)=A_2024_00182
     (사용자가 업로드한 OpenAPI_통계코드.xls에서 확인)
   - 정상 응답: {"SttsApiTblData":[{"head":[...]},{"row":[{...,"CLS_ID":500001,
     "CLS_NM":"전국",...,"DTA_VAL":128.7...,"WRTTIME_DESC":"2026년 1월"},...]}]}
   - 데이터없음 응답: {"RESULT":{"CODE":"INFO-200","MESSAGE":"해당하는 데이터가 없습니다."}}
     - 발표 지연으로 최근 몇 개월은 데이터가 없는 경우가 흔함(라이브 테스트 시 당월부터
     역순으로 6개월치가 전부 없었음) - 최대 12개월 역순으로 값이 나올 때까지 시도함.
   - CLS_ID(지역 분류코드, 라이브 응답에서 직접 확인): 500001=전국, 500007=서울, 500008=부산,
     500009=대구, 500010=인천, 500011=광주, 500012=대전, 500013=울산, 500014=세종,
     500015=경기, 500016=강원, 500017=충북, 500018=충남, 500019=전북, 500020=전남,
     500021=경북, 500022=경남, 500023=제주. 시/군/구 단위 세분류는 없음(서울만 5개 권역
     세분류 있음 - 이 앱에서는 안 씀).
   ⚠️ 아래 SQL을 Supabase에 먼저 한 번 실행:
     create table if not exists rone_index_cache (
       id text primary key,
       latest_month text,
       latest_data jsonb,
       year_ago_month text,
       year_ago_data jsonb,
       fetched_at timestamptz
     );
════════════════════════════════════ */
const RONE_API_KEY = process.env.RONE_API_KEY;
const RONE_BASE_URL = 'https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do';
const RONE_STAT_CODES = { sale: 'A_2024_00178', jeonse: 'A_2024_00182' };
const RONE_SIDO_CLS = {
  '전국': 500001, '서울': 500007, '부산': 500008, '대구': 500009, '인천': 500010,
  '광주': 500011, '대전': 500012, '울산': 500013, '세종': 500014, '경기': 500015,
  '강원': 500016, '충북': 500017, '충남': 500018, '전북': 500019, '전남': 500020,
  '경북': 500021, '경남': 500022, '제주': 500023,
};
const RONE_FRESH_MS = 1000 * 60 * 60 * 24; // 24시간 - 월 1회만 갱신되는 값

function shiftYyyymm(yyyymm, deltaMonths) {
  const y = parseInt(String(yyyymm).slice(0, 4), 10), m = parseInt(String(yyyymm).slice(4, 6), 10);
  const total = y * 12 + (m - 1) + deltaMonths;
  const ny = Math.floor(total / 12), nm = total - ny * 12;
  return `${ny}${String(nm + 1).padStart(2, '0')}`;
}

// ⚠️ 실패 이유(네트워크 예외 / 인증키 오류 / 진짜 데이터없음)를 구분해 last.reason에 남김 -
// 예전엔 무조건 null만 반환해서 "12개월 내 데이터를 찾지 못했습니다"라는 뭉뚱그려진 메시지만
// 나왔는데, 실제로는 원인이 완전히 다른 문제(예: 키 오류)일 수도 있어 진단이 안 됐던 문제가
// 있었음(라이브 배포 후 발견) - 이제 마지막으로 시도한 실패 이유를 그대로 응답에 노출시킴.
async function fetchRoneMonth(statblId, yyyymm) {
  const url = `${RONE_BASE_URL}?STATBL_ID=${statblId}&DTACYCLE_CD=MM&WRTTIME_IDTFR_ID=${yyyymm}&Type=json&KEY=${RONE_API_KEY}`;
  let data;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
    data = await r.json();
  } catch (e) {
    console.warn(`R-ONE(${statblId},${yyyymm}) 호출 예외 -`, e.message);
    return { month: yyyymm, byCls: null, reason: 'R-ONE 호출 실패(네트워크): ' + e.message };
  }
  const rows = data && data.SttsApiTblData && data.SttsApiTblData[1] && data.SttsApiTblData[1].row;
  if (!Array.isArray(rows) || !rows.length) {
    // 인증키 오류 등은 {RESULT:{CODE,MESSAGE}} 형태로 옴(SttsApiTblData 래핑이 아예 없음).
    // ⚠️ 2026-08(버그 수정): 처음엔 메시지 문자열에 "데이터없음"이 포함되는지로 "재시도해도
    // 되는 실패인지"를 판정했는데, 실제 R-ONE의 진짜 데이터없음 메시지는 "해당하는 데이터가
    // 없습니다"라 그 부분 문자열이 아예 다르게 나와서(라이브 배포 후 발견) 매번 첫 달만
    // 시도하고 바로 포기해버리는 문제가 있었음 - CODE 값(INFO-200=데이터없음, 재시도 가치
    // 있음)으로 명확히 판정하도록 수정.
    const resultInfo = data && data.RESULT;
    const retryable = !resultInfo || resultInfo.CODE === 'INFO-200';
    const reason = resultInfo
      ? `R-ONE 오류(${resultInfo.CODE}): ${resultInfo.MESSAGE}`
      : `R-ONE(${yyyymm}) 데이터없음`;
    if (resultInfo && resultInfo.CODE !== 'INFO-200') console.warn(`R-ONE(${statblId},${yyyymm}) 오류 -`, resultInfo.CODE, resultInfo.MESSAGE);
    return { month: yyyymm, byCls: null, reason, retryable };
  }
  const byCls = {};
  rows.forEach(row => { byCls[row.CLS_ID] = { name: row.CLS_NM, value: row.DTA_VAL }; });
  return { month: yyyymm, byCls, reason: null, retryable: false };
}

// 최근월부터 최대 12개월 역순으로 시도 - 발표 지연으로 최근 몇 개월은 데이터가 없는 경우가 흔함(라이브 확인).
async function fetchLatestRoneMonth(statblId) {
  const now = new Date();
  let yyyymm = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}`;
  let lastReason = null;
  for (let i = 0; i < 12; i++) {
    const result = await fetchRoneMonth(statblId, yyyymm);
    if (result.byCls) return result;
    lastReason = result.reason;
    // 인증키/네트워크 오류처럼 달을 바꿔봐야 소용없는 실패는 즉시 중단(불필요한 12회 반복 방지)
    if (!result.retryable) return { month: null, byCls: null, reason: lastReason };
    yyyymm = shiftYyyymm(yyyymm, -1);
  }
  return { month: null, byCls: null, reason: lastReason || '최근 12개월 모두 데이터없음' };
}

async function fetchRoneTrendForStat(statblId) {
  const latest = await fetchLatestRoneMonth(statblId);
  if (!latest.byCls) return { error: 'R-ONE 조회 실패: ' + (latest.reason || '알 수 없는 오류') };
  const yearAgoMonth = shiftYyyymm(latest.month, -12);
  const yearAgo = await fetchRoneMonth(statblId, yearAgoMonth);
  return {
    latestMonth: latest.month, latestData: latest.byCls,
    yearAgoMonth: yearAgo.byCls ? yearAgo.month : null, yearAgoData: yearAgo.byCls,
  };
}

async function getRoneTrend(force) {
  if (!RONE_API_KEY) return { error: 'RONE_API_KEY 환경변수가 없습니다. reb.or.kr(R-ONE)에서 발급받은 인증키를 Vercel에 추가해 주세요.' };
  const result = {};
  for (const kind of Object.keys(RONE_STAT_CODES)) {
    if (!force) {
      try {
        const { data: cached, error } = await supabase.from('rone_index_cache').select('*').eq('id', kind).maybeSingle();
        if (!error && cached && (Date.now() - new Date(cached.fetched_at).getTime()) < RONE_FRESH_MS) {
          result[kind] = { latestMonth: cached.latest_month, latestData: cached.latest_data, yearAgoMonth: cached.year_ago_month, yearAgoData: cached.year_ago_data, cached: true };
          continue;
        }
      } catch (e) { console.warn('rone_index_cache 조회 예외:', e.message); }
    }
    const fresh = await fetchRoneTrendForStat(RONE_STAT_CODES[kind]);
    if (fresh.error) { result[kind] = fresh; continue; }
    try {
      const { error: upsertErr } = await supabase.from('rone_index_cache').upsert({
        id: kind, latest_month: fresh.latestMonth, latest_data: fresh.latestData,
        year_ago_month: fresh.yearAgoMonth, year_ago_data: fresh.yearAgoData, fetched_at: new Date().toISOString(),
      });
      if (upsertErr) console.warn('rone_index_cache 저장 실패:', upsertErr.message);
    } catch (e) { console.warn('rone_index_cache 저장 예외:', e.message); }
    result[kind] = { ...fresh, cached: false };
  }
  return result;
}

// roneResult(sale/jeonse 각각 latestData/yearAgoData 포함)를 특정 시/도 기준 YoY 변화율로 요약
function roneTrendForSido(roneResult, sido) {
  const clsId = RONE_SIDO_CLS[sido] || RONE_SIDO_CLS['전국'];
  const out = {};
  Object.keys(RONE_STAT_CODES).forEach(kind => {
    const r = roneResult[kind];
    if (!r || r.error || !r.latestData || !r.yearAgoData) { out[kind] = r && r.error ? { error: r.error } : null; return; }
    const latest = r.latestData[clsId], base = r.yearAgoData[clsId];
    if (!latest || !base || !base.value) { out[kind] = null; return; }
    const pct = Math.round((latest.value - base.value) / base.value * 1000) / 10;
    let trend = 'flat';
    if (pct > 0.3) trend = 'up'; else if (pct < -0.3) trend = 'down';
    out[kind] = { regionName: latest.name, latestMonth: r.latestMonth, yearAgoMonth: r.yearAgoMonth, pct, trend };
  });
  return out;
}

/* ════════════════════════════════════
   KOSIS(국가통계포털) 시군구 인구·세대수 증감 (mode=population) - 2026-08 추가
   ⚠️ 아래는 사용자가 data.go.kr에서 "국가데이터처_KOSIS 통계자료 조회 서비스"(별도
   활용신청 필요 - 처음엔 "통계목록" 서비스만 신청되어 있어 SERVICE_KEY_IS_NOT_REGISTERED_
   ERROR가 났었음)를 추가로 활용신청한 뒤 실제 라이브 호출로 전부 확인한 내용(2026-08):
   - 통계표ID: 인구수=DT_1B040A3("행정구역(시군구)별, 성별 인구수"), 세대수=DT_1B040B3
     ("행정구역(시군구)별 주민등록세대수"), 둘 다 orgId=101(통계청/국가데이터처).
   - itmId는 ALL로 주면 인구수 표는 총인구수(T20)/남자(T21)/여자(T22) 3종류가 섞여서
     나오므로, 원하는 값만 정확히 받으려면 반드시 항목코드를 지정해야 함: 인구수 표는
     itmId=T20(총인구수), 세대수 표는 itmId=T1(세대수)만 쓰는 단일 항목이라 T1 고정.
   - objL1(분류1=시군구코드)은 통계청 표준 5자리 행정구역코드(이 앱이 이미 쓰는
     LAWD_CODES와 완전히 같은 체계) - 예: 28245(인천 계양구)로 조회하면 C1_NM:"계양구"로
     정확히 매칭됨(라이브 확인). objL1=ALL이면 전국+시/도+시/군/구가 전부 섞여서 나옴.
   - newEstPrdCnt=N이면 최근 N개 기간을 PRD_DE 오름차순으로 반환함(가장 최근이 배열 끝).
   - 정상 응답: {"response":{"header":{"resultCode":"00",...},"body":{"items":{"item":
     [{...,"C1":"28245","C1_NM":"계양구","PRD_DE":"202607","DT":"276125",...}]}}}}
   - 오류 응답(활용신청 안 된 오퍼레이션 호출 시): {"OpenAPI_ServiceResponse":{
     "cmmMsgHeader":{"errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR",...}}}
   ⚠️ Supabase 캐시 SQL:
     create table if not exists kosis_population_cache (
       id text primary key,
       latest_prd text,
       latest_value numeric,
       year_ago_prd text,
       year_ago_value numeric,
       fetched_at timestamptz
     );
════════════════════════════════════ */
// ⚠️ 별도 KOSIS_API_KEY를 새로 안 만들고 기존 PUBLIC_DATA_API_KEY(국토부 실거래가 수집 등에
// 이미 쓰는 data.go.kr 공공데이터포털 키)를 재사용함 - KOSIS도 같은 data.go.kr 계정 소속이라
// "일반 인증키" 값이 동일함(사용자가 캡처해 보내준 두 KOSIS 서비스 페이지에서 같은 키 값 확인).
const KOSIS_API_KEY = process.env.PUBLIC_DATA_API_KEY;
const KOSIS_DATA_URL = 'https://apis.data.go.kr/1240000/statisticsData/getStatisticsData';
const KOSIS_TBL = { population: { tblId: 'DT_1B040A3', itmId: 'T20' }, households: { tblId: 'DT_1B040B3', itmId: 'T1' } };
const KOSIS_FRESH_MS = 1000 * 60 * 60 * 24;

async function fetchKosisLatest(tblId, itmId, sigunguCd) {
  const url = `${KOSIS_DATA_URL}?serviceKey=${encodeURIComponent(KOSIS_API_KEY)}&format=json&orgId=101&tblId=${tblId}`
    + `&objL1=${sigunguCd}&itmId=${itmId}&prdSe=M&newEstPrdCnt=13`;
  let data;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
    data = await r.json();
  } catch (e) { return { error: 'KOSIS 호출 실패: ' + e.message }; }
  if (data && data.OpenAPI_ServiceResponse) {
    const h = data.OpenAPI_ServiceResponse.cmmMsgHeader || {};
    return { error: 'KOSIS 오류: ' + (h.returnAuthMsg || h.errMsg || '알 수 없는 오류'), raw: data };
  }
  const items = data && data.response && data.response.body && data.response.body.items && data.response.body.items.item;
  if (!Array.isArray(items) || !items.length) return { error: 'KOSIS 응답에 데이터가 없습니다(objL1 시군구코드가 안 맞을 수 있음).', raw: data };
  const sorted = items.slice().sort((a, b) => String(a.PRD_DE).localeCompare(String(b.PRD_DE)));
  const history = sorted.map(it => ({ prd: it.PRD_DE, value: parseFloat(it.DT) })).filter(h => Number.isFinite(h.value));
  if (!history.length) return { error: 'KOSIS 응답 값을 숫자로 변환하지 못했습니다.', raw: data };
  const latest = history[history.length - 1];
  const yearAgo = history.length >= 13 ? history[history.length - 13] : history[0];
  return { latestPrd: latest.prd, latestValue: latest.value, yearAgoPrd: yearAgo.prd, yearAgoValue: yearAgo.value };
}

async function getKosisTrend(sigunguCd, force) {
  if (!KOSIS_API_KEY) return { error: 'PUBLIC_DATA_API_KEY 환경변수가 없습니다. data.go.kr에서 발급받은 인증키를 Vercel에 추가해 주세요.' };
  const result = {};
  for (const kind of Object.keys(KOSIS_TBL)) {
    const cacheId = kind + '|' + sigunguCd;
    if (!force) {
      try {
        const { data: cached, error } = await supabase.from('kosis_population_cache').select('*').eq('id', cacheId).maybeSingle();
        if (!error && cached && (Date.now() - new Date(cached.fetched_at).getTime()) < KOSIS_FRESH_MS) {
          result[kind] = { latestPrd: cached.latest_prd, latestValue: cached.latest_value, yearAgoPrd: cached.year_ago_prd, yearAgoValue: cached.year_ago_value, cached: true };
          continue;
        }
      } catch (e) { console.warn('kosis_population_cache 조회 예외:', e.message); }
    }
    const fresh = await fetchKosisLatest(KOSIS_TBL[kind].tblId, KOSIS_TBL[kind].itmId, sigunguCd);
    if (fresh.error) { result[kind] = fresh; continue; }
    try {
      const { error: upsertErr } = await supabase.from('kosis_population_cache').upsert({
        id: cacheId, latest_prd: fresh.latestPrd, latest_value: fresh.latestValue,
        year_ago_prd: fresh.yearAgoPrd, year_ago_value: fresh.yearAgoValue, fetched_at: new Date().toISOString(),
      });
      if (upsertErr) console.warn('kosis_population_cache 저장 실패:', upsertErr.message);
    } catch (e) { console.warn('kosis_population_cache 저장 예외:', e.message); }
    result[kind] = { ...fresh, cached: false };
  }
  return result;
}

/* ════════════════════════════════════
   헤도닉 회귀모델(AVM, Automated Valuation Model) 예측 (mode=avmEstimate) - 2026-08 추가
   - index.html의 getCompEstValue()(비교물건 몇 건의 평단가 평균/중앙값)를 대체하는 게
     아니라 "독립적인 교차검증용 참고치"로 나란히 보여주기 위한 것. 표본이 적은 물건(나홀로
     아파트 등)에서 비교물건 자체가 몇 건 없어 우연한 편차에 휘둘리는 문제를, 전체
     house_trades(28만+건)를 다 써서 학습한 회귀계수로 보완함.
   - 학습(무거운 연산)은 이 서버리스 함수가 아니라 GitHub Actions(주 1회, train-avm.py)에서
     오프라인으로 돌리고, 여기서는 이미 학습된 계수(avm_model_coefs 테이블)를 읽어 가벼운
     내적(dot product) 계산만 함(요청마다 재학습하면 느리고 비용도 큼).
   - 방법론(Frisch-Waugh-Lovell 고정효과 회귀), 변수 정의는 train-avm.py 상단 주석 참고.
     같은 정의를 여기서도 그대로 써야 함(예측식이 학습식과 어긋나면 안 됨):
       y = log(평당가) = global_coefs·[log(size), floor, floor^2, age, age^2, time_trend]
           + dong_effects[키]
     ⚠️ 2026-08(단지 단위 세분화): 처음엔 "키"가 항상 region|dong(법정동)이었는데, 실제
     배포 후 확인해보니 같은 법정동 안에서도 단지별 편차가 커서(예: 고잔동 실측 - 준공연도
     다른 단지 섞이며 평단가 3.4배 차이) 오차가 컸음. 아파트는 이제 danji(단지명)까지 포함한
     3단계 폴백 체인으로 키를 찾음: region|dong|danji(단지 표본 충분) → region|dong(그 단지
     표본부족 시 학습 때 법정동 단위로 승격됨) → region(그 법정동조차 표본부족 시 시군구로
     승격) → dong_effects["__default__"](전국 평균, 완전히 새 지역일 때만). 연립다세대는
     아직 danji 단계 없이 region|dong → region 2단계만 씀(train-avm.py MIN_DANJI_SAMPLES
     주석 참고 - 거래 자체가 뜸해 단지 단위로 쪼개면 오히려 불안정해짐).
   ⚠️ 아래 SQL을 Supabase에 먼저 한 번 실행해서 테이블을 만들어야 합니다:
     create table if not exists avm_model_coefs (
       id text primary key,
       model_type text,
       trained_at timestamptz,
       n_samples int,
       r_squared numeric,
       global_coefs jsonb,
       dong_effects jsonb,
       feature_ranges jsonb
     );
   ⚠️ train-avm.py를 최소 한 번(GitHub Actions 또는 로컬)은 실행해서 이 테이블에 apt_v1/
   villa_v1 행이 채워져 있어야 mode=avmEstimate가 정상 응답함 - 비어 있으면 "AVM 모델이
   아직 학습되지 않았습니다" 에러를 그대로 반환함(폴백으로 조용히 다른 값을 지어내지 않음).
════════════════════════════════════ */
// ⚠️ 2026-08(villa_v1 추가): 처음엔 아파트(apt_v1)만 학습했는데, 프론트가 물건 유형과
// 무관하게 항상 type=apt로만 AVM을 조회하는 버그가 있었음(연립다세대 물건도 아파트
// 시세로 계산돼 비교물건 대비 몇 배 높게 나옴 - 실제 배포 후 안산 이동 530-21로 테스트해
// 발견) - 버그를 고치면서 "그럼 연립다세대는 왜 AVM이 아예 안 되나"라는 질문에 답하며
// villa_v1도 추가함(train-avm.py 참고 - villa_trades+single_trades 합쳐 법정동 단위로 학습).
const AVM_MODEL_ID_BY_TYPE = { apt: 'apt_v1', villa: 'villa_v1' };
const AVM_CURRENT_YEAR_FALLBACK = () => new Date().getFullYear();

// ⚠️ 2026-08(K-apt 2단계): train-avm.py의 normalize_complex_name()과 반드시 동일한 로직이어야
// 함(학습 시점과 예측 시점의 정규화가 어긋나면 매칭이 조용히 실패함). 공백 제거 +
// "아파트"/"단지" 접미사 제거만 하는 보수적 정규화 - 괄호까지 지우면 "이촌코오롱(A)"/
// "이촌코오롱(B)"처럼 실제로 다른 단지를 같은 단지로 잘못 묶을 위험이 있어 피함.
function normalizeComplexName(name) {
  if (!name) return '';
  let s = String(name).trim().replace(/\s+/g, '');
  for (const suf of ['아파트', '단지']) {
    if (s.endsWith(suf)) s = s.slice(0, -suf.length);
  }
  return s;
}

// train-avm.py의 fit_fwl()과 반드시 같은 정의를 씀 - 여기서 정의가 어긋나면(예: age 계산
// 기준이 다르거나 time_trend 기준일이 다르면) 학습된 계수를 엉뚱한 값에 곱하게 되어 예측이
// 조용히 틀려버림(에러 없이 그럴듯한 숫자만 나와 알아채기 어려운 위험한 버그 유형).
// ⚠️ 2026-08(K-apt 2단계): log_households(세대수) 추가 - apt_v1만 이 항을 쓰고(villa_v1은
// global_coefs에 이 키가 없어 avmPredict에서 자동으로 무시됨) logHouseholds가 없으면(K-apt
// 미매칭) 0을 넣지 않고 호출부(getAvmEstimate)가 모델 학습 때와 같은 중앙값 폴백을 미리
// 계산해서 넘겨줌 - 0을 넣으면 "세대수 1채" 취급이 되어 계수가 터무니없이 왜곡되므로 주의.
// ⚠️ 2026-08(역세권/학군 연동): log_dist_subway(지하철역 거리)/log_elem_count·
// log_middle_count(초/중학교 밀집도) 추가 - K-apt와 같은 이유로, 이 값들이 null이면(호출부가
// 계산 못한 경우) 0을 넣지 않고 반드시 모델 학습 때와 같은 폴백값을 미리 계산해 넘겨야 함
// (0을 넣으면 "지하철역이 100m 거리다"/"학교가 1개다"처럼 엉뚱한 값으로 왜곡됨).
// ⚠️ 2026-08(AVM 정확도 개선 - 층위치 피처): floor/floor^2 곡선만으로는 "5층짜리 건물의
// 5층(탑층)"과 "20층짜리 건물의 5층(중간층)"을 구분 못 함(절대 층수만 같고 건물 높이 정보가
// 없어서) - train-avm.py의 _attach_floor_tier_features와 반드시 같은 정의를 써야 함(비교물건
// 매칭에 쓰는 getFloorTier와 같은 통찰: 지하/1층/탑층은 매끄러운 곡선이 아니라 불연속적
// 할인 요인). is_ground_floor/is_basement는 floor만 있으면 항상 계산 가능하지만(topFloor
// 불필요), floor_ratio/is_top_floor는 topFloor(K-apt 최고층수)가 있어야만 의미가 있어 topFloor가
// 없으면(K-apt 미매칭이고 학습 때 median_top_floor도 없던 초기 상태) 0(중립값)으로 둠 - 어차피
// villa_v1처럼 이 계수 자체가 없는 모델에서는 avmPredict가 Object.keys(coefs) 순회 방식이라
// 이 값이 있어도 무시됨(무해).
function avmFeatureVector({ size, floor, buildYear, timeOrigin, logHouseholds, logDistSubway, logElemCount, logMiddleCount, topFloor }) {
  const dealYear = AVM_CURRENT_YEAR_FALLBACK(); // 예측 시점 = "지금 팔면 얼마" 기준이므로 오늘 연도를 씀
  const age = Math.max(0, dealYear - buildYear);
  const today = todayInt();
  const timeTrend = daysBetweenYyyymmdd(timeOrigin, today) / 365.0;
  const isBasement = floor <= 0 ? 1 : 0;
  const isGroundFloor = floor === 1 ? 1 : 0;
  let floorRatio = 0, isTopFloor = 0;
  if (floor > 0 && topFloor > 0) {
    floorRatio = Math.min(1.2, floor / topFloor);
    isTopFloor = floor >= topFloor ? 1 : 0;
  }
  return {
    log_size: Math.log(size), floor, floor2: floor * floor,
    age, age2: age * age, time_trend: timeTrend,
    log_households: logHouseholds != null ? logHouseholds : 0,
    log_dist_subway: logDistSubway != null ? logDistSubway : 0,
    log_elem_count: logElemCount != null ? logElemCount : 0,
    log_middle_count: logMiddleCount != null ? logMiddleCount : 0,
    floor_ratio: floorRatio, is_top_floor: isTopFloor,
    is_ground_floor: isGroundFloor, is_basement: isBasement,
  };
}
// YYYYMMDD 정수 두 값 사이의 일수 차이(a 기준 → b까지, 음수 가능) - Date 객체로 변환해 계산.
function daysBetweenYyyymmdd(a, b) {
  const toDate = (n) => { const s = String(n); return new Date(`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T00:00:00Z`); };
  return Math.round((toDate(b).getTime() - toDate(a).getTime()) / 86400000);
}

// ⚠️ 2026-08(빌라 반경기반 그룹핑, 사용자 요청): train-avm.py의 _spatial_grid_key()와
// 반드시 같은 공식이어야 함(학습 시점과 예측 시점의 격자 정의가 어긋나면 group_key가 절대
// 일치하지 않음 - K-apt/역세권 cache_key와 같은 종류의 학습/서빙 일치 요구사항).
const GRID_LAT_KM_PER_DEG = 111.0; // 위도 1도 ≈ 111km - train-avm.py의 LAT_KM_PER_DEG와 동일
function spatialGridKey(lat, lon, cellKm) {
  if (lat == null || lon == null || !(cellKm > 0)) return null;
  let lonKmPerDeg = GRID_LAT_KM_PER_DEG * Math.cos((lat * Math.PI) / 180);
  if (!(lonKmPerDeg > 1.0)) lonKmPerDeg = GRID_LAT_KM_PER_DEG; // 극단적 위도 방어(사실상 발생 안 함)
  const latCell = Math.floor((lat * GRID_LAT_KM_PER_DEG) / cellKm);
  const lonCell = Math.floor((lon * lonKmPerDeg) / cellKm);
  return `grid_${latCell}_${lonCell}`;
}

function avmPredict(model, features, region, dong, danji, gridKey) {
  const coefs = model.global_coefs || {};
  // ⚠️ 2026-08(K-apt 2단계): 하드코딩된 6개 목록 대신 실제 저장된 계수의 키를 그대로 씀 -
  // 모델마다(apt_v1엔 log_households가 있고 villa_v1엔 없음) 변수 개수가 달라졌고, 앞으로
  // #298(역세권/학군) 등이 추가돼도 이 함수를 다시 안 고쳐도 되게 하기 위함.
  let logPpp = 0;
  Object.keys(coefs).forEach(k => { logPpp += (coefs[k] || 0) * (features[k] || 0); });
  const logPppFromFeatures = logPpp; // 진단용 - 그룹효과(dong_effects) 더하기 전 값

  const dongEffects = model.dong_effects || {};
  // 진단/신뢰도 표시용 - grid(공간격자, 빌라 전용 1차 단위)/danji(단지) 정확 매칭인지,
  // dong(법정동) 단위인지, region(시군구) 폴백인지, 아예 전국 평균 폴백인지를 그대로
  // 응답에 남겨 프론트에서 "이 값이 얼마나 구체적인 데이터에 기반했는지"를 사용자에게
  // 투명하게 보여줄 수 있게 함. 순서는 train-avm.py의 승격 순서와 반드시 같아야 함
  // (아파트: danji→dong→region, 빌라: grid→dong→region - gridKey는 빌라 예측일 때만
  // 계산되므로 아파트에는 영향이 없고, danjiKey는 빌라 dong_effects에 애초에 존재하지
  // 않는 키 형식이라 둘이 서로 간섭하지 않음).
  let effect, effectUsed;
  const danjiKey = danji ? `${region}|${dong}|${danji}` : null;
  if (gridKey && dongEffects[gridKey] !== undefined) {
    effect = dongEffects[gridKey]; effectUsed = 'grid';
  } else if (danjiKey && dongEffects[danjiKey] !== undefined) {
    effect = dongEffects[danjiKey]; effectUsed = 'danji';
  } else if (dongEffects[`${region}|${dong}`] !== undefined) {
    effect = dongEffects[`${region}|${dong}`]; effectUsed = 'dong';
  } else if (dongEffects[region] !== undefined) {
    effect = dongEffects[region]; effectUsed = 'region_fallback';
  } else {
    effect = dongEffects['__default__'] || 0; effectUsed = 'default_fallback';
  }
  logPpp += effect;

  const ppp = Math.exp(logPpp); // 만원/평
  // groupEffect/logPppFromFeatures는 진단용(getAvmEstimate의 debug 필드로 노출) - 이상하게
  // 큰/작은 추정치가 나왔을 때 "피처(층·연식·역세권 등) 문제인지 그룹효과(그 동네 자체
  // 가격수준) 문제인지"를 DB를 직접 조회하지 않고도 API 응답만으로 구분할 수 있게 함.
  return { ppp: Math.round(ppp * 10) / 10, effectUsed, groupEffect: effect, logPppFromFeatures };
}

async function getAvmEstimate(type, region, dong, size, floor, buildYear, danji, sigunguCode, clientTopFloor, lat, lon) {
  const modelId = AVM_MODEL_ID_BY_TYPE[type];
  if (!modelId) return { error: `AVM v1은 아직 이 매물 유형(${type})을 지원하지 않습니다(아파트·연립다세대·단독만 지원).` };
  if (!(size > 0) || !(floor >= 0) || !(buildYear > 1900)) {
    return { error: 'size(면적), floor(층), buildYear(준공연도)가 유효해야 합니다.' };
  }
  let model;
  try {
    const { data, error } = await supabase.from('avm_model_coefs').select('*').eq('id', modelId).maybeSingle();
    if (error) return { error: 'avm_model_coefs 조회 실패: ' + error.message };
    model = data;
  } catch (e) { return { error: 'avm_model_coefs 조회 예외: ' + e.message }; }
  if (!model) return { error: 'AVM 모델이 아직 학습되지 않았습니다. GitHub Actions(train-avm 워크플로)를 한 번 실행해 주세요.' };

  // ⚠️ 2026-08(K-apt 2단계): 이 모델이 log_households를 실제로 쓰는 경우에만(villa_v1은 안 씀)
  // 조회 비용을 들임 - 물건의 단지(danji)를 kapt_complex_info에서 찾아 세대수를 가져오고,
  // 못 찾으면(K-apt 미등록 단지, 이름 표기 차이 등) train-avm.py가 학습 때 쓴 것과 같은
  // 중앙값(median_households)으로 폴백함 - 학습/서빙이 다른 임의값을 쓰면 계수 해석이
  // 어긋나므로 반드시 모델에 저장된 값을 그대로 재사용함. sigunguCode는 지역명 문자열
  // 매칭보다 신뢰도가 높아(이미 프론트가 좌표 역지오코딩으로 구한 정확한 5자리 코드) 이걸로
  // kapt_complex_info.sigungu_code를 직접 필터링함.
  let logHouseholds = null;
  let topFloorForModel = null;
  const coefs = model.global_coefs || {};
  // ⚠️ 2026-08(버그 수정 - 파주 야당동 AVM 20억 오추정 사례로 발견): 중앙값 폴백이 "danji &&
  // sigunguCode && dong" 조건문 "안쪽"에 있어서, 이 물건에 단지명(danji, a-name 필드)이
  // 비어있으면(단독주택 형태 등) K-apt 조회 자체를 건너뛰면서 폴백조차 실행되지 않고
  // logHouseholds/topFloorForModel이 그대로 null로 남았음. 그러면 avmFeatureVector()가
  // null을 0으로 치환해버리는데, log_households=0은 "이 단지가 세대수 1채"라는 뜻이라
  // 학습 때 본 적 없는 극단치가 되어 계수가 왜곡된 방향으로 크게 튐. 폴백 계산을 조건문
  // "바깥"으로 빼서, 단지명이 없어도(=K-apt 조회를 아예 못 해도) 항상 학습 때와 같은
  // 중앙값으로 채워지도록 수정.
  if (coefs.log_households !== undefined) {
    if (danji && sigunguCode && dong) {
      try {
        const normDanji = normalizeComplexName(danji);
        // ⚠️ 2026-08(층위치 피처): top_floor도 households와 같은 kapt_complex_info 조회
        // 한 번에 같이 가져옴(추가 DB 왕복 없이) - train-avm.py의 build_kapt_lookup과 같은
        // 소스에서 같은 매칭 로직(정규화 단지명)으로 찾아야 학습/서빙 정의가 어긋나지 않음.
        const { data: kaptRows } = await supabase
          .from('kapt_complex_info')
          .select('kapt_name, households, top_floor')
          .eq('sigungu_code', String(sigunguCode))
          .eq('as3', dong)
          .not('households', 'is', null);
        const matched = (kaptRows || []).find((r) => normalizeComplexName(r.kapt_name) === normDanji);
        if (matched && matched.households > 0) logHouseholds = Math.log(matched.households);
        if (matched && matched.top_floor > 0) topFloorForModel = matched.top_floor;
      } catch (e) { /* K-apt 조회 실패해도 AVM 자체를 막지 않고 중앙값 폴백으로 진행 */ }
    }
    if (logHouseholds == null) {
      const medianHh = model.feature_ranges && model.feature_ranges.median_households;
      if (medianHh > 0) logHouseholds = Math.log(medianHh);
    }
    if (topFloorForModel == null) {
      const medianTop = model.feature_ranges && model.feature_ranges.median_top_floor;
      if (medianTop > 0) topFloorForModel = medianTop;
    }
  }
  // ⚠️ 2026-08(빌라 층위치 보정): 클라이언트가 이 특정 건물의 건축HUB 총층수(clientTopFloor)를
  // 보내오면 K-apt 단지명 매칭/중앙값 폴백보다 우선함 - "그 단지의 평균"이 아니라 "이 건물
  // 자체"의 값이라 더 정확함(사용자 요청: 지금 보는 건물의 건축HUB 총층수를 바로 쓰기).
  if (clientTopFloor > 0) topFloorForModel = clientTopFloor;

  // ⚠️ 2026-08(역세권 연동, #298): transit_features.cache_key는 warmup-locations.mjs의
  // buildCacheKey(dong, danji, bunji, road_name, main_num, sub_num)와 완전히 같은 값인데,
  // 예측 대상 물건은 bunji/road_name/main_num/sub_num을 안 받으므로(K-apt처럼 정확한
  // full key 재구성이 불가) dong+danji 두 구간(`동|단지명|`)만으로 접두어(prefix) 매칭함 -
  // 같은 단지면 주소 세부만 다르고 dong+danji는 항상 같은 값이라 안전하게 좁혀짐. 참고로
  // 이 cache_key는 K-apt처럼 아파트/단지명 정규화를 하지 않고 원본 그대로(소문자화만)
  // 저장돼 있음(buildCacheKey 자체가 정규화 없이 원본 필드를 이어붙이는 방식이라 여기서도
  // 동일하게 원본 danji를 그대로 씀 - normalizeComplexName을 쓰면 오히려 어긋남).
  const SUBWAY_SEARCH_RADIUS_M = 2000; // sync-transit.mjs / train-avm.py와 반드시 같은 값
  let logDistSubway = null;
  // ⚠️ 2026-08(버그 수정 - 파주 야당동 AVM 20억 오추정 사례로 발견): 위 log_households와
  // 완전히 같은 유형의 버그. 중앙값 폴백이 "danji && dong" 조건문 안쪽에 있어서, 단지명이
  // 없는 물건(danji가 빈 문자열)이면 역세권 조회 자체를 건너뛰며 폴백도 실행 안 되고
  // logDistSubway가 null로 남음 → avmFeatureVector()가 이걸 0으로 치환. log_dist_subway=0은
  // "역과의 거리가 1m(거의 역 안)"라는 뜻이라(학습식이 log(거리+100)이므로 0=exp(0)-100=-99m)
  // 실제로는 안 가까운 물건도 "역세권 최고 입지"로 잘못 취급돼 값이 크게 부풀려짐. 폴백을
  // 조건문 밖으로 빼서 단지명이 없어도 항상 학습 때와 같은 중앙값 거리로 채워지게 수정.
  if (coefs.log_dist_subway !== undefined) {
    if (danji && dong) {
      try {
        const prefix = `${dong}|${danji}|`.toLowerCase();
        const { data: transitRows } = await supabase
          .from('transit_features')
          .select('dist_subway_m')
          .ilike('cache_key', `${prefix}%`)
          .limit(1);
        if (transitRows && transitRows.length > 0) {
          const distM = transitRows[0].dist_subway_m != null ? transitRows[0].dist_subway_m : SUBWAY_SEARCH_RADIUS_M;
          logDistSubway = Math.log(distM + 100);
        }
      } catch (e) { /* 역세권 조회 실패해도 AVM 자체를 막지 않고 중앙값 폴백으로 진행 */ }
    }
    if (logDistSubway == null) {
      const medianDist = model.feature_ranges && model.feature_ranges.median_dist_subway;
      if (medianDist > 0) logDistSubway = Math.log(medianDist + 100);
    }
  }

  // ⚠️ 2026-08(학군 근사치 연동, #298): school_info는 (region,dong) 단위 집계라 K-apt/역세권과
  // 달리 정확한 개수를 그대로 셀 수 있음(폴백이 필요없음 - 매칭 0건도 "그 동네에 아직 지오코딩
  // 안 된/없는 학교"라는 있는 그대로의 값이고, log1p라 0이어도 안전함 - train-avm.py 주석 참고).
  let logElemCount = null, logMiddleCount = null;
  if (coefs.log_elem_count !== undefined && region && dong) {
    try {
      const { data: schoolRows } = await supabase
        .from('school_info')
        .select('school_type')
        .eq('region', region)
        .eq('dong', dong);
      const elemCount = (schoolRows || []).filter((r) => r.school_type === '초등학교').length;
      const middleCount = (schoolRows || []).filter((r) => r.school_type === '중학교').length;
      logElemCount = Math.log1p(elemCount);
      logMiddleCount = Math.log1p(middleCount);
    } catch (e) { logElemCount = 0; logMiddleCount = 0; }
  }

  const timeOrigin = (model.feature_ranges && model.feature_ranges.time_origin) || 20251201;
  const features = avmFeatureVector({ size, floor, buildYear, timeOrigin, logHouseholds, logDistSubway, logElemCount, logMiddleCount, topFloor: topFloorForModel });
  // ⚠️ 2026-08(빌라 반경기반 그룹핑): 이 모델이 grid_cell_km을 저장해뒀으면(=villa_v1처럼
  // use_grid=True로 학습됨) 물건 좌표로 grid_key를 계산해 avmPredict에 넘김 - 학습 때 실제
  // 쓴 격자 크기를 그대로 재사용해야 group_key가 어긋나지 않음(train-avm.py의
  // feature_ranges["grid_cell_km"] 저장 로직 참고). 좌표가 없으면(lat/lon 미전달) 자동으로
  // null이 되어 기존 법정동 폴백으로 안전하게 넘어감.
  const gridCellKm = model.feature_ranges && model.feature_ranges.grid_cell_km;
  const gridKey = gridCellKm > 0 && lat != null && lon != null
    ? spatialGridKey(parseFloat(lat), parseFloat(lon), gridCellKm) : null;
  const { ppp, effectUsed, groupEffect, logPppFromFeatures } = avmPredict(model, features, region, dong, danji, gridKey);
  let totalPrice = Math.round(ppp * (size / 3.305785));

  // ⚠️ 2026-08(빌라 층위치 보정, 사용자 요청): villa_v1은 K-apt 같은 벌크 데이터가 없어
  // floor_ratio/is_top_floor/is_ground_floor/is_basement 계수를 학습 자체에서 갖지 못함(단독
  // 다세대는 "단지" 개념이 없어 층위치를 대량으로 미리 알 방법이 없음 - 물건을 열 때마다
  // 건축HUB를 그 건물 하나만 조회하는 구조라 학습 시점엔 이 데이터가 없음). 대신 서빙 시점에
  // apt_v1이 이미 학습해 둔 층위치 계수를 "차용"해 배율로 얹음 - 같은 부동산 시장이라 탑층/
  // 1층/반지하 할인·할증의 방향과 크기는 아파트·빌라가 비슷한 패턴을 보인다는 가정.
  // floor_ratio(연속값, 중간층 완만한 곡선)는 일부러 제외함 - villa_v1 자체의 floor/floor^2
  // 곡선과 겹쳐 이중 계산될 위험이 있는 반면, is_top_floor 등 불연속 더미는 villa_v1에 아예
  // 대응 계수가 없어 겹칠 여지가 없음(더 안전하게 차용 가능). apt_v1에 아직 이 계수들이 없는
  // 구버전 모델이면 logAdj가 0이 돼 자동으로 보정 없이(floorTierAdjustment=null) 넘어감.
  let floorTierAdjustment = null;
  if (modelId === 'villa_v1' && clientTopFloor > 0 && floor != null) {
    try {
      const { data: aptModel } = await supabase.from('avm_model_coefs').select('global_coefs').eq('id', 'apt_v1').maybeSingle();
      const aptCoefs = (aptModel && aptModel.global_coefs) || {};
      const isBasement = floor <= 0 ? 1 : 0;
      const isGroundFloor = floor === 1 ? 1 : 0;
      const isTopFloor = floor > 0 && floor >= clientTopFloor ? 1 : 0;
      const logAdj = (aptCoefs.is_top_floor || 0) * isTopFloor
        + (aptCoefs.is_ground_floor || 0) * isGroundFloor
        + (aptCoefs.is_basement || 0) * isBasement;
      if (logAdj !== 0) {
        const multiplier = Math.exp(logAdj);
        const beforeManwon = totalPrice;
        totalPrice = Math.round(totalPrice * multiplier);
        const reasons = [];
        if (isTopFloor) reasons.push('탑층');
        if (isGroundFloor) reasons.push('1층');
        if (isBasement) reasons.push('반지하/지하');
        floorTierAdjustment = {
          multiplierPct: Math.round((multiplier - 1) * 1000) / 10, // ±% - 양수면 할증, 음수면 할인
          beforeManwon, afterManwon: totalPrice,
          reasons, // 어떤 층위치 특성이 반영됐는지(복수 가능 - 예: 총 1층짜리 건물이면 1층+탑층 동시)
          source: 'apt_v1_borrowed', // 아파트 모델 계수를 빌려 썼다는 표시(투명성용)
        };
      }
    } catch (e) { /* apt_v1 계수 조회 실패해도 기본 villa AVM 값은 그대로 반환 */ }
  }

  // ⚠️ 2026-08(정확도 보완) - r_squared는 학습 데이터 자체로 채점한 in-sample 값이라 항상
  // 낙관적으로 나옴(특히 그룹 고정효과가 많은 모델은 그룹 수만으로도 R^2가 잘 나올 수밖에
  // 없음). train-avm.py가 이제 무작위 20% 홀드아웃(모델이 한 번도 안 본 실제 거래)으로
  // 별도 검증해 feature_ranges에 저장해두므로(train-avm.py RESIDUAL_IQR_MULT/evaluate_holdout
  // 주석 참고), 여기서 그 값을 읽어 point estimate와 함께 "검증된" 오차범위를 같이 내려줌.
  // feature_ranges는 이미 jsonb라 구버전 모델(이 필드들이 없는 채로 학습된 경우)에서도
  // undefined로 조용히 빠질 뿐 에러가 나지 않음.
  const fr = model.feature_ranges || {};
  let errorMargin = null;
  if (fr.residual_std_log != null) {
    // 로그공간 표준편차 1개(≈정규분포 근사 시 약 68% 구간)를 원래 스케일 %오차로 환산.
    // exp(std)-1이 곧 "그 표준편차만큼 벗어났을 때의 상대오차 비율"임(로그 잔차의 정의상).
    const marginPct = Math.round((Math.exp(fr.residual_std_log) - 1) * 1000) / 10;
    errorMargin = {
      marginPct, // ± 이 %만큼(약 68% 구간, 정규분포 근사 - 참고용)
      priceRangeManwon: [
        Math.round(totalPrice * (1 - marginPct / 100)),
        Math.round(totalPrice * (1 + marginPct / 100)),
      ],
      holdoutMapePct: fr.holdout_mape_pct != null ? fr.holdout_mape_pct : null, // 홀드아웃 평균 절대오차(%)
      holdoutMedianApePct: fr.holdout_median_ape_pct != null ? fr.holdout_median_ape_pct : null,
      holdoutN: fr.holdout_n != null ? fr.holdout_n : null, // 검증에 쓰인 표본 수
    };
  }

  return {
    pppManwon: ppp, // 예상 평당가(만원/평)
    totalPriceManwon: totalPrice, // 입력한 size 기준 예상 총액(만원)
    effectUsed, // 'danji' | 'dong' | 'region_fallback' | 'default_fallback' - 신뢰도 판단용
    modelId, trainedAt: model.trained_at, nSamples: model.n_samples, rSquared: model.r_squared,
    outliersRemoved: fr.outliers_removed != null ? fr.outliers_removed : null,
    errorMargin, // null이면 구버전 모델(홀드아웃 검증 이전에 학습됨) - 프론트는 이 경우 오차범위를 숨김
    floorTierAdjustment, // 빌라만 채워짐(null이면 미적용) - 아파트 모델 계수를 빌린 층위치 보정 내역
    // ⚠️ 2026-08(진단용, 파주 야당동 20억 오추정 사례로 추가): 추정치가 비정상적으로 크거나
    // 작을 때 "층·연식·역세권 등 피처 문제인지" vs "그룹효과(그 동네 자체 가격수준) 문제인지"를
    // DB를 직접 조회하지 않고도 이 응답만 보고 구분할 수 있게 함. groupKey는 실제 매칭된
    // dong_effects의 키 문자열(디버깅 시 Supabase에서 바로 조회 가능하도록).
    debug: {
      danjiReceived: danji || null,
      groupKeyTier: effectUsed,
      groupEffectLog: groupEffect, // dong_effects[매칭키] 원값(로그 스케일)
      featuresLogContribution: logPppFromFeatures, // 층/연식/역세권 등 피처들의 로그 기여 합
      logDistSubwayUsed: logDistSubway, // null이면 이 모델이 역세권 계수 자체가 없는 것, 0이면 과거 버그 재발 의심
      logHouseholdsUsed: logHouseholds,
    },
    // dong까지는 실제 그 동네 실거래 기반이라 신뢰도 있음 - region_fallback/default_fallback일
    // 때만(단지·법정동 표본 자체가 부족해서 더 넓은 단위로 승격된 경우) 낮은 신뢰도로 표시함.
    lowConfidence: (model.r_squared != null && model.r_squared < 0.3) || effectUsed === 'region_fallback' || effectUsed === 'default_fallback',
  };
}

/* ════════════════════════════════════
   법정동별 거래량 순위(topDongs) + 가격상승모멘텀(priceMomentum, "돈되는 지역") - 2026-08
   - 둘 다 (region,dong) 기준 GROUP BY 집계가 필요한데, PostgREST의 count()/avg() "집계
     임베딩" URL 문법(select=region,dong,cnt:count())은 Supabase 프로젝트에서 기본적으로
     꺼져 있어(Database → API 설정에서 별도로 켜야 하는 기능) 실제로는 매번 빈 배열만
     돌아왔음(에러 없이 조용히 실패) - 배포 후 실동작 테스트에서 발견.
   - 그래서 GROUP BY 자체를 Postgres 함수(RPC)로 옮김. RPC는 일반 SQL 함수라 저 설정과
     무관하게 항상 동작하고, 전체 행을 서버로 끌고 오지 않고 DB 안에서 이미 집계된 결과
     (법정동 개수 정도)만 돌려주므로 전국 단위로 조회해도 가볍고 빠름.
   - ⚠️ 아래 두 함수(rpc_top_dongs, rpc_bucket_avg_price)는 Supabase SQL 편집기에서 딱 한
     번만 실행해서 만들어 두면 됨(마이그레이션). 이미 만들어져 있다면 이 배포에서는 별도
     조치 없이 그대로 동작함.
     ------------------------------------------------------------------
     create or replace function rpc_top_dongs(p_cutoff int, p_sido text, p_type text, p_limit int default 20)
     returns table(region text, dong text, cnt bigint)
     language sql stable as $$
       select region, dong, count(*) as cnt from (
         select region, dong from house_trades
           where p_type = 'apt' and deal_date >= p_cutoff and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong from villa_trades
           where p_type = 'villa' and deal_date >= p_cutoff and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong from single_trades
           where p_type = 'villa' and deal_date >= p_cutoff and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
       ) t
       group by region, dong order by cnt desc limit p_limit;
     $$;

     -- ⚠️ 2026-08(1차): avg_price를 "총 매매가"가 아니라 "평당가(만원/평 = price/size*
     -- 3.305785)"로 바꿈. 국민평형(23~25평)만 보면 단지별 평형 차이를 무시할 수 있어 좋지만,
     -- 그만큼 표본이 작아져서 소도시에서는 우연한 편차가 순위 상위권을 차지하는 문제가
     -- 있었음. 평당가로 정규화하면 모든 평형의 거래를 다 써도 서로 비교 가능해져서 표본이
     -- 훨씬 커짐.
     -- ⚠️ 2026-08(2차): 단순 평균은 신축 프리미엄 건물(아파트는 주변시세 대비 15~20%,
     -- 빌라는 2배 가까이 비싸게 거래되기도 함)이 몇 건만 섞여도 "돈되는 지역"으로 잘못
     -- 뜨는 착시를 만들 수 있어서, build_year 기준 신축 거래는 집계에서 빼고
     -- new_cnt/new_avg_price로 별도 반환하도록 바꿈. 신축을 뺀 나머지도 같은
     -- (region,dong) 평균 대비 표준편차 2.5배를 벗어나는 극단적 이상치는 느슨하게
     -- 추가로 걸러냄(로얄동/로얄층 같은 정상 편차는 이 배수로는 안 걸림). 반환 컬럼이
     -- 늘어나서 이번엔 DROP FUNCTION 후 CREATE로 교체해야 함(CREATE OR REPLACE만으로는
     -- 안 됨).
     -- ⚠️ 2026-08(신축 기준 조정): 처음엔 준공 1년 이내를 신축으로 봤는데, 아파트/빌라는
     -- 프리미엄이 꺼지는 속도가 달라(아파트는 입주 2~3년차까지도 초기 시세가 남아있는
     -- 경우가 많고, 빌라는 신축 프리미엄이 상대적으로 더 오래/크게 남는 경향) 타입별로
     -- 기준을 다르게 둠: 아파트는 준공 2년 이내, 빌라(연립다세대·단독)는 준공 3년 이내를
     -- 신축으로 판단(p_type에 따라 분기).
     -- ⚠️ 2026-08(성능 수정): 처음엔 이상치 기준을 중앙값(percentile_cont, 정렬이 필요한
     -- 무거운 연산)으로 만들었는데, "전국"처럼 시/도 없이 조회하면 (region,dong) 그룹 수가
     -- 훨씬 많아져 정렬 비용이 커지면서 응답이 아예 안 오는 문제가 실제 배포 후 테스트에서
     -- 발견됨(시/도 하나로 좁히면 정상, "전국"만 멈춤). AVG/STDDEV_POP(정렬 불필요한
     -- 단일패스 집계)로 교체해 해결함.
     -- ⚠️ 2026-08(mix-shift 수정): "서울 마포구 아현동"에서 특정 구간에 우연히 저가/구축
     -- 단지 거래가 몰리면서 단지들 시세는 그대로인데 동 평균만 훅 떨어져 보인 사례가 발견됨
     -- ("돈되는 지역"이 실제 가격변동이 아니라 구간별 거래 단지 구성 변화만으로 뽑히는 착시).
     -- danji(단지명)별로도 그룹핑해서 반환하도록 바꾸고, 실제 mix-shift 보정(각 단지를 자기
     -- 자신의 전체기간 평균과 비교하는 상대지수 계산)은 JS(getPriceMomentum)에서 이 함수를
     -- "구간별로" 6번 호출해 받은 danji별 평단가를 그대로 합산해 baseline(6구간 전체기간
     -- 평균)까지 만들어냄 - SQL은 danji별 평단가만 돌려줌. ⚠️ 처음엔 baseline을 위해 이
     -- 함수를 전체 범위로 한 번 더(타입당 7번째) 호출했는데, type=both일 때 (6+1)×2=14개
     -- RPC 호출이 한꺼번에 몰리면서 커넥션이 막혀 "서울 조회가 안 됨"(무한 로딩) 버그가
     -- 실제 배포 후 테스트에서 발견됨 - 6구간을 합치면 곧 전체기간과 정확히 같으므로 별도
     -- 호출 없이 이미 받은 6개 결과를 합산하는 방식으로 바꿔 호출 횟수를 원래(6번)대로
     -- 되돌림.
     drop function if exists rpc_bucket_avg_price(int, int, text, text, int, int);
     create function rpc_bucket_avg_price(p_start int, p_end int, p_sido text, p_type text, p_min_size int, p_max_size int)
     returns table(region text, dong text, danji text, avg_price numeric, cnt bigint, new_cnt bigint, new_avg_price numeric)
     language sql stable as $$
       with raw as (
         select region, dong, coalesce(nullif(danji, ''), '(단지미상)') as danji, price, size, build_year from house_trades
           where p_type = 'apt' and deal_date >= p_start and deal_date < p_end
             and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, coalesce(nullif(danji, ''), '(단지미상)') as danji, price, size, build_year from villa_trades
           where p_type = 'villa' and deal_date >= p_start and deal_date < p_end
             and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, coalesce(nullif(danji, ''), '(단지미상)') as danji, price, size, build_year from single_trades
           where p_type = 'villa' and deal_date >= p_start and deal_date < p_end
             and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
       ),
       tagged as (
         select region, dong, danji,
           (price::numeric / nullif(size, 0)) * 3.305785 as ppp,
           (build_year is not null and build_year >= (extract(year from current_date)::int - case when p_type = 'apt' then 2 else 3 end)) as is_new
         from raw
       ),
       existing as (
         select region, dong, danji, ppp from tagged where not is_new
       ),
       stats as (
         select region, dong, avg(ppp) as mean_ppp, stddev_pop(ppp) as sd_ppp
         from existing group by region, dong
       ),
       clipped as (
         select e.region, e.dong, e.danji, e.ppp
         from existing e
         join stats s on s.region = e.region and s.dong = e.dong
         where e.ppp <= s.mean_ppp + 2.5 * coalesce(s.sd_ppp, 0)
           and e.ppp >= s.mean_ppp - 2.5 * coalesce(s.sd_ppp, 0)
       ),
       new_agg as (
         select region, dong, avg(ppp) as new_avg_price, count(*) as new_cnt
         from tagged where is_new group by region, dong
       )
       select c.region, c.dong, c.danji,
         avg(c.ppp) as avg_price,
         count(*) as cnt,
         coalesce(n.new_cnt, 0) as new_cnt,
         n.new_avg_price
       from clipped c
       left join new_agg n on n.region = c.region and n.dong = c.dong
       group by c.region, c.dong, c.danji, n.new_cnt, n.new_avg_price;
     $$;
     ------------------------------------------------------------------
════════════════════════════════════ */
const SIDO_LIST = ['서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주'];
function sixMonthsAgoInt(months) {
  return monthsAgoInt(months || 6);
}
async function getTopDongs(type, cutoff, sido, limit) {
  try {
    const { data, error } = await supabase.rpc('rpc_top_dongs', {
      p_cutoff: cutoff, p_sido: sido || null, p_type: type, p_limit: limit,
    });
    if (error) { console.warn(`topDongs(rpc): ${type} 조회 실패 -`, error.message); return []; }
    return (data || []).map(r => ({ region: r.region, dong: r.dong, count: Number(r.cnt) }));
  } catch (e) { console.warn(`topDongs(rpc): ${type} 조회 예외 -`, e.message); return []; }
}

// 2026-08: 국민평형(23~25평)만 보던 걸 폐지하고 전체 평형을 다 씀 - 대신 avg_price가
// "평당가"로 바뀌었으니(RPC 참고) 평형이 달라도 그대로 비교 가능함. size 범위는 데이터
// 오류(0㎡ 등) 배제용 최소한의 안전장치일 뿐, 더 이상 특정 평형대를 걸러내는 필터가 아님.
const MOMENTUM_SIZE_MIN = 10;
const MOMENTUM_SIZE_MAX = 300;
// 표본 신뢰도 기준(구간당 거래건수) - 2026-08: 이 값 미만이어도 더 이상 후보에서 완전히
// 빼지 않음(아래 getPriceMomentum 참고). 대신 그 구간에 "표본부족" 플래그를 남겨 프론트에서
// 신뢰도가 낮다고 표시하는 용도로만 씀. 아파트/연립다세대는 원래 거래 빈도 차이가 커서
// (연립다세대가 훨씬 뜸함 - 기존 급등지역 로직도 이걸 감안해 연립다세대는 3개월 대신
// 6개월 단기창을 씀) 기준을 서로 다르게 둠.
const MOMENTUM_MIN_BUCKET_COUNT_APT = 7;
const MOMENTUM_MIN_BUCKET_COUNT_VILLA = 4;
// 구간 길이(일, 타입별로 다름) - 원래 "달력상 1개월"(28~31일, 월마다 길이가 달라짐)이었는데
// 고정폭으로 변경함(총 6구간 × 이 값 = 되돌아보는 총 일수). 날짜 계산도 setDate() 기반이라
// monthsAgoInt()의 월말 오버플로우 문제와 무관하게 항상 정확한 간격이 나옴.
// ⚠️ 2026-08: 아파트는 house_trades 수집 시작일(2025-12-01)에 맞춰 40일(총 240일)로,
// 연립다세대는 원래 거래가 뜸해서 더 넓게 60일(총 360일, 수집 시작일 2025-01-01 안에 넉넉히
// 들어옴)로 서로 다르게 둠.
const MOMENTUM_BUCKET_DAYS_APT = 40;
const MOMENTUM_BUCKET_DAYS_VILLA = 60;
function minBucketCountFor(type) { return type === 'villa' ? MOMENTUM_MIN_BUCKET_COUNT_VILLA : MOMENTUM_MIN_BUCKET_COUNT_APT; }
function bucketDaysFor(type) { return type === 'villa' ? MOMENTUM_BUCKET_DAYS_VILLA : MOMENTUM_BUCKET_DAYS_APT; }
// 추세 일관성 필터 - 6구간(=5번의 구간 전환) 중 상승한 횟수가 이보다 적으면 제외함. 처음↔
// 마지막 구간만 비교하면 중간에 들쭉날쭉해도 "모멘텀"으로 잡히는 문제를 막기 위함.
const MOMENTUM_MIN_UP_TRANSITIONS = 3;
// 거래량 급감 경고 - 직전 구간 대비 거래량이 이 비율 미만으로 줄면 신뢰도가 떨어진다고 보고
// 결과에서 완전히 빼지는 않되(정보 자체는 유의미할 수 있어서) 프론트에 경고로 표시함.
const MOMENTUM_VOLUME_DROP_RATIO = 0.3;
// N개월 전 날짜(YYYYMMDD 정수) - Date.setMonth()을 그냥 쓰면 "그 달에 없는 날짜"로 넘어갈 때
// 다음달로 오버플로우되는 버그가 있음(예: 3/31 - 1개월 => 2월엔 31일이 없어서 JS가 자동으로
// 3/3으로 튕겨버림 - 의도한 "2월 말"보다 한 달 가까이 어긋난 엉뚱한 날짜가 됨). 이게 실제로
// 벌어지면 이 날짜를 구간 경계로 쓰는 돈되는 지역 6구간의 길이가 서로 달라지거나 겹쳐서
// "거래량 급감"처럼 보이는 가짜 신호나 평단가 오류를 만들 수 있어서, 대상 월의 마지막
// 날짜로 클램프하는 방식(예: 3/31 - 1개월 => 2/28)으로 2026-08에 수정함.
function monthsAgoInt(months) {
  const now = new Date();
  const totalMonths = now.getFullYear() * 12 + now.getMonth() - months;
  const y = Math.floor(totalMonths / 12);
  const m = totalMonths - y * 12; // 0-indexed month
  const daysInTargetMonth = new Date(y, m + 1, 0).getDate();
  const day = Math.min(now.getDate(), daysInTargetMonth);
  const mm = String(m + 1).padStart(2, '0'), dd = String(day).padStart(2, '0');
  return parseInt(`${y}${mm}${dd}`, 10);
}
function todayInt() {
  const d = new Date();
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
// N일 전 날짜(YYYYMMDD 정수) - Date.setDate()는 setMonth()와 달리 월/년 경계를 자동으로
// 정확히 처리하므로(예: 3/5 - 10일 => 2/23) 별도 클램프 로직이 필요 없음.
function daysAgoInt(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
function momentumBuckets(type) {
  // 2026-08: 달력상 1개월(28~31일, 월마다 길이가 다름) 구간 → 타입별 고정폭(bucketDaysFor)×6구간
  // 으로 변경. idx 0 = 가장 오래된 구간, idx 5 = 가장 최근 구간
  const bucketDays = bucketDaysFor(type);
  const buckets = [];
  const today = todayInt();
  for (let i = 0; i < 6; i++) {
    const startDays = bucketDays * (6 - i), endDays = bucketDays * (5 - i);
    buckets.push({
      start: daysAgoInt(startDays),
      end: i === 5 ? today + 1 : daysAgoInt(endDays), // 마지막 구간만 오늘까지 포함(미래 날짜 데이터 방지용 +1)
    });
  }
  return buckets;
}
// 진단용: 특정 (region,dong,type) 구간의 rpc_bucket_avg_price 집계 뒤에 숨은
// 원본 거래 목록을 그대로 보여줌 - "왜 이 구간 평단가가 이렇게 나왔는지" 근거자료
// 확인용. 범위가 (region,dong,40~60일)로 좁아서 가볍고 빠름. 신규 서버리스 함수를
// 새로 만들지 않고 기존 mode 분기 방식 그대로 씀.
async function getBucketDetailRows(type, region, dong, start, end) {
  const cols = 'region,dong,danji,price,size,floor,deal_date,build_year';
  let rows = [];
  if (type === 'villa') {
    const [{ data: v, error: e1 }, { data: s, error: e2 }] = await Promise.all([
      supabase.from('villa_trades').select(cols).eq('region', region).eq('dong', dong)
        .gte('deal_date', start).lt('deal_date', end)
        .gte('size', MOMENTUM_SIZE_MIN).lte('size', MOMENTUM_SIZE_MAX),
      supabase.from('single_trades').select(cols).eq('region', region).eq('dong', dong)
        .gte('deal_date', start).lt('deal_date', end)
        .gte('size', MOMENTUM_SIZE_MIN).lte('size', MOMENTUM_SIZE_MAX),
    ]);
    if (e1) throw e1;
    if (e2) throw e2;
    rows = [...(v || []), ...(s || [])];
  } else {
    const { data, error } = await supabase.from('house_trades').select(cols)
      .eq('region', region).eq('dong', dong)
      .gte('deal_date', start).lt('deal_date', end)
      .gte('size', MOMENTUM_SIZE_MIN).lte('size', MOMENTUM_SIZE_MAX);
    if (error) throw error;
    rows = data || [];
  }
  const curYear = new Date().getFullYear();
  return rows
    .map(r => ({
      danji: r.danji, price: r.price, size: r.size, floor: r.floor, deal_date: r.deal_date,
      build_year: r.build_year,
      ppp: r.size ? Math.round((r.price / r.size) * 3.305785 * 10) / 10 : null,
      isNew: r.build_year != null && r.build_year >= curYear - 1,
    }))
    .sort((a, b) => a.deal_date - b.deal_date);
}
// (region,dong) 단위가 아니라 (region,dong,danji) 단위로 평단가/건수를 받아옴 - danji별로
// 나눠 받는 이유는 getPriceMomentum에서 "이 단지가 원래(baseline 기간) 얼마였는지"와
// 비교하는 상대지수 계산을 하기 위함(아래 getPriceMomentum 주석 참고).
async function getBucketDanjiPrices(type, start, end, sido) {
  try {
    const { data, error } = await supabase.rpc('rpc_bucket_avg_price', {
      p_start: start, p_end: end, p_sido: sido || null, p_type: type,
      p_min_size: MOMENTUM_SIZE_MIN, p_max_size: MOMENTUM_SIZE_MAX,
    });
    if (error) { console.warn(`priceMomentum(rpc): ${type} 조회 실패 -`, error.message); return {}; }
    const acc = {};
    (data || []).forEach(r => {
      const key = r.region + '|' + r.dong;
      if (!acc[key]) acc[key] = { region: r.region, dong: r.dong, danjis: {}, newCount: 0, newAvg: null };
      acc[key].danjis[r.danji || '(단지미상)'] = { avg: Number(r.avg_price), count: Number(r.cnt) };
      // newCount/newAvg는 dong 단위 값이라 같은 dong의 danji 행마다 똑같이 반복되어 옴 -
      // 그냥 마지막 값으로 덮어써도 결과는 같음(참고용 정보라 병합 계산과는 무관).
      acc[key].newCount = Number(r.new_cnt) || 0;
      acc[key].newAvg = r.new_avg_price != null ? Number(r.new_avg_price) : null;
    });
    return acc;
  } catch (e) { console.warn(`priceMomentum(rpc): ${type} 조회 예외 -`, e.message); return {}; }
}
// 전국(시/도 미지정) 조회 전용 - dong 단위(danji 없이) 평단가/건수를 받아옴.
// getPriceMomentumSimple에서만 씀(아래 getPriceMomentum 주석 참고).
async function getBucketDongPrices(type, start, end, sido) {
  try {
    const { data, error } = await supabase.rpc('rpc_bucket_avg_price_dong', {
      p_start: start, p_end: end, p_sido: sido || null, p_type: type,
      p_min_size: MOMENTUM_SIZE_MIN, p_max_size: MOMENTUM_SIZE_MAX,
    });
    if (error) { console.warn(`priceMomentum(rpc dong): ${type} 조회 실패 -`, error.message); return {}; }
    const acc = {};
    (data || []).forEach(r => {
      const key = r.region + '|' + r.dong;
      acc[key] = {
        region: r.region, dong: r.dong, avg: Number(r.avg_price), count: Number(r.cnt),
        newCount: Number(r.new_cnt) || 0,
        newAvg: r.new_avg_price != null ? Number(r.new_avg_price) : null,
      };
    });
    return acc;
  } catch (e) { console.warn(`priceMomentum(rpc dong): ${type} 조회 예외 -`, e.message); return {}; }
}
// 2026-08(mix-shift 수정, 전국 폴백): 단지기준 상대지수(아래 getPriceMomentumRelative)는
// danji까지 그룹핑해서 조회하다 보니 그룹 수가 훨씬 커지는데, "전국"(시/도 미지정)처럼
// 조회 범위가 넓으면 이 그룹 수가 감당이 안 될 만큼 커져서 DB 조회가 타임아웃 나
// 아파트 결과가 통째로 빈 배열로 오는 문제가 실제 배포 후 테스트에서 발견됨(연립다세대는
// 거래량 자체가 훨씬 적어 전국이어도 문제없었음 - 아파트만 증상이 있었던 이유). 시/도를
// 하나로 좁히면 정상 동작하는 걸 확인함. 그래서 "전국" 조회에서는 danji 그룹핑 없는
// 가벼운 dong 단위 함수(rpc_bucket_avg_price_dong)로 폴백해 예전 방식(표본부족 구간만
// 직전/직후와 병합, mix-shift 보정 없음)을 그대로 씀 - 시/도를 하나 골라서 보면 최신
// 단지기준 상대지수가 적용된 결과를 볼 수 있음.
// ⚠️ 2026-08(전국 동시조회 타임아웃 수정): 6구간을 Promise.all로 한꺼번에 쏘면(게다가
// mode=priceMomentum 라우터가 apt/villa도 동시에 돌리니 최악의 경우 12개 동시), "전국"
// (시/도 미지정 - region 필터가 없어 house_trades/villa_trades/single_trades 전체를
// 매 구간마다 훑는 가장 무거운 조회 패턴)에서 Supabase 커넥션이 몰려 일부/전체 구간이
// 타임아웃 나고 getBucketDongPrices의 catch가 조용히 {}를 반환 - 결과적으로 "돈되는 지역"
// 전국 조회가 통째로 "데이터가 없다"로 보이는 문제가 실제 배포 후 테스트에서 발견됨.
// (직접 SQL로 rpc_bucket_avg_price_dong을 단독 호출하면 같은 구간이 1000건 넘게 정상
// 반환되는 걸 확인함 - 함수/데이터 자체는 멀쩡하고, 동시요청 부하만 문제였음.) 구간별로
// 순차 호출하도록 바꿔 동시 커넥션 수를 6→1로 줄임(danji 기준 상대지수 경로는 시/도로
// 좁혀서 가벼우니 그대로 Promise.all 유지 - 이 함수는 "전국" 전용 폴백이라 여기만 수정).
async function getPriceMomentumSimple(type, sido, limit) {
  const minCount = minBucketCountFor(type);
  const buckets = momentumBuckets(type);
  const bucketMaps = [];
  for (const b of buckets) {
    bucketMaps.push(await getBucketDongPrices(type, b.start, b.end, sido));
  }
  const allKeys = new Set();
  bucketMaps.forEach(m => Object.keys(m).forEach(k => allKeys.add(k)));
  const rankings = [];
  allKeys.forEach(k => {
    let meta = null;
    for (const m of bucketMaps) { if (m[k]) { meta = m[k]; break; } }
    if (!meta) return;
    const rawCount = bucketMaps.map(m => (m[k] ? m[k].count : 0));
    const rawSum = bucketMaps.map(m => (m[k] ? m[k].avg * m[k].count : 0));
    const newCounts = bucketMaps.map(m => (m[k] ? m[k].newCount : 0));
    const prices = [], lowSample = [];
    for (let i = 0; i < 6; i++) {
      let windowSum = rawSum[i], windowCount = rawCount[i];
      let back = i - 1;
      while (windowCount < minCount && back >= 0) { windowSum += rawSum[back]; windowCount += rawCount[back]; back--; }
      let fwd = i + 1;
      while (windowCount < minCount && fwd < 6) { windowSum += rawSum[fwd]; windowCount += rawCount[fwd]; fwd++; }
      prices.push(windowCount > 0 ? Math.round(windowSum / windowCount) : null);
      lowSample.push(windowCount < minCount);
    }
    const firstValid = prices.find(p => p !== null);
    if (firstValid == null) return;
    for (let i = 0; i < prices.length; i++) { if (prices[i] === null) prices[i] = firstValid; }
    const firstAvg = prices[0], lastAvg = prices[5];
    if (!firstAvg) return;
    let upTransitions = 0;
    for (let i = 1; i < prices.length; i++) { if (prices[i] > prices[i - 1]) upTransitions++; }
    let volumeDrop = false;
    for (let i = 1; i < rawCount.length; i++) { if (rawCount[i - 1] > 0 && rawCount[i] < rawCount[i - 1] * MOMENTUM_VOLUME_DROP_RATIO) volumeDrop = true; }
    const newCntTotal = newCounts.reduce((a, b) => a + b, 0);
    rankings.push({
      region: meta.region,
      dong: meta.dong,
      prices, counts: rawCount, lowSample, newCounts, newCntTotal,
      upTransitions, volumeDrop,
      momentumPct: Math.round((lastAvg - firstAvg) / firstAvg * 1000) / 10,
    });
  });
  const filtered = rankings.filter(r => r.upTransitions >= MOMENTUM_MIN_UP_TRANSITIONS);
  filtered.sort((a, b) => b.momentumPct - a.momentumPct);
  return filtered.slice(0, limit);
}
async function getPriceMomentum(type, sido, limit) {
  // 전국(시/도 미지정)은 성능 때문에 danji 없는 단순 버전으로 폴백 - 위 주석 참고.
  if (!sido) return getPriceMomentumSimple(type, sido, limit);
  return getPriceMomentumRelative(type, sido, limit);
}
async function getPriceMomentumRelative(type, sido, limit) {
  const minCount = minBucketCountFor(type);
  const buckets = momentumBuckets(type);
  // ⚠️ 2026-08(mix-shift 수정, 1차 시도 롤백): baseline(6구간 전체기간 평균)을 구하려고
  // 처음엔 구간별 조회와 별도로 "전체 범위"를 한 번 더(타입당 7번째) 조회했는데, 이 7번째
  // 호출이 배포 후 "서울 조회가 안 됨"(무한 로딩, 데이터 부족으로 표시) 버그를 일으킴 -
  // type=both면 아파트/빌라 합쳐 (6+1)×2=14개의 Supabase RPC 호출이 한꺼번에 몰리면서
  // 커넥션이 막혀 응답이 아예 안 오는 문제가 실제 배포 후 테스트에서 발견됨. 6구간 경계가
  // 서로 딱 맞닿아 있어 6개 구간을 합치면 곧 전체 기간과 정확히 같으므로, 별도 쿼리 없이
  // 이미 받아온 bucketMaps(6개)를 그대로 합산해서 baseline을 만듦(DB 호출 그대로 6번 유지 -
  // 이전 버전과 동일한 부하로 되돌림).
  const bucketMaps = await Promise.all(buckets.map(b => getBucketDanjiPrices(type, b.start, b.end, sido)));
  // 2026-08(4차, mix-shift 수정): "서울 마포구 아현동" 사례에서, 특정 구간에 우연히 저가/구축
  // 단지(애오개아이파크·예미원 등) 거래가 몰리면서 단지들 자체 시세는 그대로인데 동 전체
  // 평균만 훅 떨어져 보이는 문제가 발견됨. 단순히 그 구간에 거래된 모든 건을 평균내면 "이번에
  // 어떤 단지가 거래됐는지"에 따라 평단가가 출렁여서, 실제 가격변동이 아닌데도 "돈되는 지역"
  // 순위에 잘못 뽑히는 착시가 생길 수 있음.
  // → 각 거래를 "그 단지의 baseline(6구간 전체기간) 평균 대비 몇 배(상대비율)"로 바꾼 뒤,
  //   그 상대비율들을 구간별로 평균냄. 이러면 "이번 구간엔 원래 싼 단지가 많이 거래됐다"는
  //   사실 자체가 지수에 거의 영향을 못 줌(각 단지가 자기 자신의 기준가 대비 얼마나
  //   움직였는지만 잡아내기 때문 - 반복거래/헤도닉 지수와 같은 원리). 화면엔 이 상대지수에
  //   그 동의 baseline 평균 평단가(dongBaseline)를 다시 곱해서 "만원/평" 단위로 환산해
  //   보여줌(지수 자체는 무차원 비율이라 그대로 보여주면 이해하기 어려움).
  // ⚠️ 표본부족(minCount 미달) 구간을 직전 구간과 합치는 로직은 그대로 유지하되, 이제
  //   "원본 평단가 합계"가 아니라 "원본 상대비율 합계"를 합침(방식은 동일, 대상만 바뀜).
  //   거래량(counts)은 지금처럼 병합과 무관하게 항상 그 구간의 실제 원본 거래건수를 보여줌.
  const allKeys = new Set();
  bucketMaps.forEach(m => Object.keys(m).forEach(k => allKeys.add(k)));
  const rankings = [];
  allKeys.forEach(k => {
    let meta = null;
    for (const m of bucketMaps) { if (m[k]) { meta = m[k]; break; } }
    if (!meta) return;
    // baseDanjis = 6구간을 다 합친 단지별 baseline(전체기간 평균) - 별도 쿼리 없이 이미
    // 받아온 6개 bucketMaps를 단지별로 합산해서 만듦(위 주석 참고).
    const baseDanjis = {};
    bucketMaps.forEach(m => {
      const danjis = (m[k] || {}).danjis || {};
      Object.entries(danjis).forEach(([danjiName, d]) => {
        if (!baseDanjis[danjiName]) baseDanjis[danjiName] = { sum: 0, count: 0 };
        baseDanjis[danjiName].sum += d.avg * d.count;
        baseDanjis[danjiName].count += d.count;
      });
    });
    Object.values(baseDanjis).forEach(b => { b.avg = b.count > 0 ? b.sum / b.count : 0; });
    // 그 동의 baseline 평균 평단가(모든 단지를 거래건수 가중평균) - 상대지수를 다시
    // "만원/평" 단위로 환산해 보여주기 위한 눈금(scale)으로만 쓰임.
    let dongBaseSum = 0, dongBaseCnt = 0;
    Object.values(baseDanjis).forEach(b => { dongBaseSum += b.avg * b.count; dongBaseCnt += b.count; });
    const dongBaseline = dongBaseCnt > 0 ? dongBaseSum / dongBaseCnt : null;
    if (!dongBaseline) return; // baseline 자체가 없으면(이론상 불가능 - 후보가 됐다면 어딘가 거래가 있음) 스킵

    const rawCount = bucketMaps.map(m => {
      const danjis = (m[k] || {}).danjis || {};
      return Object.values(danjis).reduce((sum, d) => sum + d.count, 0);
    });
    // relSum[i] = 구간 i의 "단지별 상대비율(그 단지 평단가 / 그 단지 baseline 평단가) ×
    //   건수"의 합 - 이 값을 rawCount로 나누면 구간 i의 "상대지수 평균"이 됨. baseline은
    //   그 단지의 전체기간(이 구간 포함) 평균이라 값이 항상 존재함(표본 1건짜리 단지는
    //   baseline과 자기 자신이 같아 상대비율이 정확히 1.0이 되어 왜곡을 만들지 않음).
    const relSum = bucketMaps.map(m => {
      const danjis = (m[k] || {}).danjis || {};
      let sum = 0;
      Object.entries(danjis).forEach(([danjiName, d]) => {
        const base = baseDanjis[danjiName];
        const rel = (base && base.avg > 0) ? (d.avg / base.avg) : 1;
        sum += rel * d.count;
      });
      return sum;
    });
    const newCounts = bucketMaps.map(m => (m[k] ? m[k].newCount : 0));

    const prices = [], lowSample = [];
    for (let i = 0; i < 6; i++) {
      let windowRelSum = relSum[i], windowCount = rawCount[i];
      let back = i - 1;
      while (windowCount < minCount && back >= 0) { windowRelSum += relSum[back]; windowCount += rawCount[back]; back--; }
      // 과거 방향(직전 구간들)을 다 끌어와도 부족하면(주로 맨 첫 구간) 미래 방향으로도 보충
      let fwd = i + 1;
      while (windowCount < minCount && fwd < 6) { windowRelSum += relSum[fwd]; windowCount += rawCount[fwd]; fwd++; }
      // 상대지수 평균 × dongBaseline = "만원/평" 단위로 환산한 표시용 평단가
      prices.push(windowCount > 0 ? Math.round((windowRelSum / windowCount) * dongBaseline) : null);
      lowSample.push(windowCount < minCount);
    }
    // 이론상 allKeys에 있으면 최소 한 구간엔 데이터가 있어 null이 안 남지만, 혹시 몰라 방어적으로 처리
    const firstValid = prices.find(p => p !== null);
    if (firstValid == null) return;
    for (let i = 0; i < prices.length; i++) { if (prices[i] === null) prices[i] = firstValid; }
    const firstAvg = prices[0], lastAvg = prices[5];
    if (!firstAvg) return;
    // 추세 일관성: 5번의 구간 전환(idx0→1, 1→2, ..., 4→5) 중 상승한 횟수
    let upTransitions = 0;
    for (let i = 1; i < prices.length; i++) { if (prices[i] > prices[i - 1]) upTransitions++; }
    // 거래량 급감 경고: 실제 거래가 있던 직전 구간 대비 급격히 줄어든 경우만 표시
    let volumeDrop = false;
    for (let i = 1; i < rawCount.length; i++) { if (rawCount[i - 1] > 0 && rawCount[i] < rawCount[i - 1] * MOMENTUM_VOLUME_DROP_RATIO) volumeDrop = true; }
    const newCntTotal = newCounts.reduce((a, b) => a + b, 0);
    rankings.push({
      region: meta.region,
      dong: meta.dong,
      prices, // 6구간 평당가(만원/평) 흐름 - 단지 baseline 대비 상대지수를 환산한 값(표본부족 구간은 인접 구간과 합산)
      counts: rawCount, // 6구간 실제 거래건수 흐름(병합과 무관, 그 구간의 원본 건수 그대로)
      lowSample, // 병합 후에도 표본이 minCount 미만이었는지
      newCounts, // 6구간 각각 신축(준공1년내)이라 위 prices/counts 집계에서 빠진 거래 건수(참고용)
      newCntTotal, // newCounts 합계 - 프론트에서 "신축 거래 별도" 배지 표시 여부 판단용
      upTransitions, // 5번의 구간 전환 중 상승한 횟수(0~5)
      volumeDrop,
      momentumPct: Math.round((lastAvg - firstAvg) / firstAvg * 1000) / 10,
    });
  });
  const filtered = rankings.filter(r => r.upTransitions >= MOMENTUM_MIN_UP_TRANSITIONS);
  filtered.sort((a, b) => b.momentumPct - a.momentumPct);
  return filtered.slice(0, limit);
}

/* ════════════════════════════════════
   법정동(읍면동) 경계 폴리곤 조회 - 2026-08: 원래 api/get-boundary.js라는 별도
   함수였는데, Vercel Hobby 12개 함수 한도에 이미 꽉 차 있어서(auction.js,
   data-coverage.js, export-table.js, get-building.js, get-coords.js,
   get-house.js, get-official-price.js, import-csv-batch.js, parse-auction.js,
   parse-registry.js, save-coord.js, search-complex.js = 12개) 새 파일을 추가할
   수 없었음. data-coverage.js가 이미 mode 분기 방식(topDongs/priceMomentum)을
   쓰고 있어서 여기에 mode=boundary로 합침. 로직 자체는 get-boundary.js와 동일:
   VWorld Data API(LT_C_ADEMD_INFO 레이어)를 시군구코드(sggCd) 단위로 조회하고,
   dong_boundaries 테이블에 영구 캐시(법정동 경계는 거의 안 바뀜) - 이후 같은
   시군구는 VWorld 재호출 없이 DB에서 바로 반환됨.
   ════════════════════════════════════ */
async function getBoundary(sggCd, wantRaw) {
  // 1순위: DB에 이미 저장된 경계가 있으면 VWorld를 호출하지 않고 바로 반환
  try {
    const { data: cached, error: cacheErr } = await supabase
      .from('dong_boundaries')
      .select('emd_cd, emd_nm, geometry')
      .eq('sgg_cd', sggCd);
    if (cacheErr) console.error('dong_boundaries 조회 에러:', cacheErr.message);
    if (cached && cached.length > 0) {
      const boundaries = cached.map((row) => ({ emdCd: row.emd_cd, emdNm: row.emd_nm, geometry: row.geometry }));
      return { status: 200, body: { boundaries, source: 'db' } };
    }
  } catch (e) {
    console.error('dong_boundaries 조회 실패:', e.message);
    // DB 조회가 실패해도 아래 VWorld 호출로 계속 진행 (캐시 미스와 동일하게 취급)
  }

  const VWORLD_KEY = process.env.VWORLD_API_KEY;
  if (!VWORLD_KEY) {
    return { status: 500, body: { error: 'VWORLD_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' } };
  }

  // domain은 VWorld 키 발급 시 등록한 도메인과 반드시 일치해야 함
  const DOMAIN = 'https://1234auction.vercel.app';

  // ⚠️ 2026-08: LT_C_ADEMD_INFO 레이어는 attrFilter로 걸 수 있는 필드가
  // [emd_eng_nm, ag_geom, emd_kor_nm, full_nm, emd_cd] 뿐이라 원래 쓰던
  // "sggCd:=:..." 필터는 VWorld가 INVALID_RANGE 에러로 거부함(실제 배포 후
  // 라이브 호출로 확인) - 애초에 이 필터가 안 먹혀서 법정동 경계선 기능이
  // 한 번도 정상 동작한 적이 없었던 것. emd_cd(10자리 법정동코드 = 앞5자리
  // 시군구코드+뒤5자리 동코드)를 LIKE로 앞자리(sggCd) 일치 검색하는 방식으로 교체.
  const url = `https://api.vworld.kr/req/data?service=data&request=GetFeature&data=LT_C_ADEMD_INFO`
    + `&key=${encodeURIComponent(VWORLD_KEY)}&domain=${encodeURIComponent(DOMAIN)}`
    + `&attrFilter=emd_cd:like:${sggCd}&size=200&format=json&crs=EPSG:4326`;

  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const data = await r.json();

    if (data?.response?.status !== 'OK') {
      return {
        status: 502,
        body: { error: 'VWorld 응답 오류: ' + (data?.response?.status || 'UNKNOWN'), raw: data?.response?.error || null },
      };
    }

    const features = data?.response?.result?.featureCollection?.features || [];
    // ⚠️ VWorld 응답의 속성 필드명은 데이터셋 버전에 따라 emd_cd/emdCd, emd_kor_nm/emdKorNm 등으로
    // 다를 수 있습니다. wantRaw=true로 한 번 호출해서 실제 필드명을 확인할 수 있음.
    const boundaries = features.map((f) => {
      const p = f.properties || {};
      return {
        emdCd: p.emd_cd || p.emdCd || p.EMD_CD || '',
        emdNm: p.emd_kor_nm || p.emdKorNm || p.EMD_KOR_NM || p.full_nm || '',
        geometry: f.geometry,
      };
    });

    if (wantRaw) return { status: 200, body: { raw: data } };

    // DB에 영구 저장 - 다음부터는 이 시군구는 VWorld 재호출 없이 DB에서 바로 반환됨
    const rows = boundaries
      .filter((b) => b.emdCd && b.geometry)
      .map((b) => ({ emd_cd: b.emdCd, sgg_cd: sggCd, emd_nm: b.emdNm, geometry: b.geometry }));
    if (rows.length > 0) {
      const { error: upsertErr } = await supabase
        .from('dong_boundaries')
        .upsert(rows, { onConflict: 'emd_cd' });
      if (upsertErr) console.error('dong_boundaries 저장 에러:', upsertErr.message);
    }

    return { status: 200, body: { boundaries, source: 'vworld' } };
  } catch (err) {
    return { status: 500, body: { error: err.message } };
  }
}

export default async function handler(req, res) {
  if (req.query.mode === 'transitBatch') {
    // 저장/등록 시점에만 호출되는 배치조회라 캐시 불필요
    res.setHeader('Cache-Control', 'no-store');
    try {
      if (req.method !== 'POST') {
        return res.status(405).json({ error: 'POST로 {cacheKeys:[...]} 를 보내주세요.' });
      }
      const cacheKeys = Array.isArray(req.body?.cacheKeys) ? req.body.cacheKeys.filter(Boolean) : [];
      if (cacheKeys.length === 0) {
        return res.status(400).json({ error: 'cacheKeys 배열이 필요합니다.' });
      }
      const results = {};
      cacheKeys.forEach((k) => { results[k] = null; }); // 아직 미동기화(sync-transit 대상)면 null 유지
      const CHUNK = 200; // PostgREST .in() URL 길이 한도를 넘지 않도록 청크 분할
      for (let i = 0; i < cacheKeys.length; i += CHUNK) {
        const chunk = cacheKeys.slice(i, i + CHUNK);
        const { data, error } = await supabase
          .from('transit_features')
          .select('cache_key,dist_subway_m,nearest_station,station_lat,station_lon')
          .in('cache_key', chunk);
        if (error) { console.warn('data-coverage: transitBatch 조회 실패 -', error.message); continue; }
        (data || []).forEach((row) => {
          // dist_subway_m/nearest_station이 null인 행은 "동기화됐지만 반경 밖(역세권 아님)"으로
          // 구분되는 유의미한 결과라, null이 아니라 필드가 채워진 객체(값 자체는 null)로 내려줌.
          results[row.cache_key] = {
            distM: row.dist_subway_m,
            stationName: row.nearest_station,
            stationLat: row.station_lat,
            stationLon: row.station_lon,
          };
        });
      }
      return res.status(200).json({ results });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'boundary') {
    res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate=604800');
    const sggCd = req.query.sggCd;
    if (!sggCd || String(sggCd).length !== 5) {
      return res.status(400).json({ error: 'sggCd(5자리 시군구코드)가 필요합니다.' });
    }
    try {
      const { status, body } = await getBoundary(String(sggCd), req.query.raw === 'true');
      return res.status(status).json(body);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'bucketDetail') {
    // 진단용 - "돈되는 지역" 특정 구간 평단가의 근거가 된 원본 거래를 그대로 보여줌.
    // 캐시하지 않음(디버깅용, 최신 상태를 바로바로 봐야 함).
    res.setHeader('Cache-Control', 'no-store');
    const { region, dong, type, start, end } = req.query;
    if (!region || !dong || !start || !end) {
      return res.status(400).json({ error: 'region, dong, start, end 쿼리파라미터가 필요합니다.' });
    }
    try {
      const rows = await getBucketDetailRows(
        type === 'villa' ? 'villa' : 'apt', region, dong, parseInt(start, 10), parseInt(end, 10)
      );
      return res.status(200).json({ region, dong, start, end, count: rows.length, rows });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'priceMomentum') {
    // 6구간 병렬조회라도 무거운 집계라 캐시를 넉넉히(1시간) 둠
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');
    try {
      const sido = (req.query.sido || '').trim();
      const typeParam = req.query.type === 'apt' || req.query.type === 'villa' ? req.query.type : 'both';
      const result = {};
      // 2026-08(사용자 요청: "규제지역/비규제지역 나눠서 순위 보고 싶다"): 프론트에서
      // "비규제지역만" 토글을 누르면 규제지역을 걸러낸 뒤에도 상위 20개가 남아있어야 하는데,
      // 여기서 20개만 내려주면 규제지역이 앞쪽을 많이 차지하는 지역(예: 서울/경기 조회)에서는
      // 필터링 후 표시할 게 거의 안 남을 수 있음. getPriceMomentum이 어차피 전체를 계산한 뒤
      // 마지막에 slice(0, limit)만 하는 구조라(SQL 자체 연산량과 무관) limit을 20→50으로
      // 올려도 서버 부하는 거의 늘지 않음 - 응답 payload만 조금 커짐.
      const RANK_LIMIT = 50;
      // 2026-08: apt/villa를 순차 await하면 "전국"처럼 무거운 조회에서 둘의 시간이
      // 그대로 합산돼 더 느려짐 - Promise.all로 병렬 실행해 전체 응답시간을 줄임.
      const jobs = [];
      if (typeParam === 'both' || typeParam === 'apt') jobs.push(getPriceMomentum('apt', sido, RANK_LIMIT).then(r => { result.apt = r; }));
      if (typeParam === 'both' || typeParam === 'villa') jobs.push(getPriceMomentum('villa', sido, RANK_LIMIT).then(r => { result.villa = r; }));
      await Promise.all(jobs);
      return res.status(200).json({ sidoList: SIDO_LIST, sido: sido || null, ...result });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'topDongs') {
    // 30분 캐시 - 실거래 신고는 매일 여러 번 안 바뀌므로 매번 무겁게 재집계할 필요 없음
    res.setHeader('Cache-Control', 's-maxage=1800, stale-while-revalidate=3600');
    try {
      const months = parseInt(req.query.months, 10) || 6;
      const cutoff = sixMonthsAgoInt(months);
      const sido = (req.query.sido || '').trim();
      const typeParam = req.query.type === 'apt' || req.query.type === 'villa' ? req.query.type : 'both';
      const result = {};
      // 2026-08: priceMomentum과 동일한 이유(규제지역 필터링 후에도 20개가 남도록) limit을
      // 20→50으로 상향. rpc_top_dongs는 SQL의 LIMIT절로 직접 쓰이지만, 이미 GROUP BY·ORDER BY로
      // 집계된 결과에서 몇 개를 더 잘라오는 차이일 뿐이라 부하 증가는 미미함.
      const RANK_LIMIT = 50;
      if (typeParam === 'both' || typeParam === 'apt') result.apt = await getTopDongs('apt', cutoff, sido, RANK_LIMIT);
      if (typeParam === 'both' || typeParam === 'villa') result.villa = await getTopDongs('villa', cutoff, sido, RANK_LIMIT);
      return res.status(200).json({ sidoList: SIDO_LIST, months, sido: sido || null, cutoff, ...result });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'baseRate') {
    // 6시간 CDN 캐시 위에 Supabase 24시간 캐시가 또 있음(getBaseRateTrend 참고) - 이중 캐시라
    // 실제 ECOS 호출은 하루 몇 번 안 됨.
    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=43200');
    try {
      const result = await getBaseRateTrend(req.query.force === '1');
      if (result.error) return res.status(502).json(result);
      return res.status(200).json(result);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'roneIndex') {
    // 6시간 CDN 캐시 위에 Supabase 24시간 캐시가 또 있음(getRoneTrend 참고) - 월 1회만 갱신되는 값이라 실제 R-ONE 호출은 하루 몇 번 안 됨.
    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=43200');
    try {
      const roneResult = await getRoneTrend(req.query.force === '1');
      const sido = (req.query.sido || '전국').trim();
      const bySido = roneTrendForSido(roneResult, sido);
      return res.status(200).json({ sido, ...bySido });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'population') {
    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=43200');
    try {
      // 시/군/구(5자리) 또는 시/도(2자리) 행정구역코드 둘 다 허용 - 프론트에서 물건 주소의
      // 정확한 시군구코드를 아직 못 구하는 화면(경매 모달)에서는 시/도 2자리로 우선 조회함.
      const sigunguCd = req.query.sigunguCd;
      if (!sigunguCd || !/^\d{2,5}$/.test(String(sigunguCd))) {
        return res.status(400).json({ error: 'sigunguCd(2~5자리 행정구역코드)가 필요합니다.' });
      }
      const result = await getKosisTrend(String(sigunguCd), req.query.force === '1');
      return res.status(200).json(result);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'avmEstimate') {
    // 학습된 계수를 읽어 가벼운 내적만 하는 요청이라 캐시 없이 매번 계산해도 충분히 빠름 -
    // 대신 계수 자체가 주 1회만 바뀌므로(train-avm.py 스케줄) 짧게 CDN 캐시만 둠.
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');
    try {
      const { type, dong, size, floor, buildYear, lawdCd, danji, topFloor, lat, lon } = req.query;
      // ⚠️ 2026-08(버그 수정): 처음엔 프론트가 카카오 geocoder 지역명을 문자열로 가공해서
      // region으로 그대로 보냈는데, "수원시 영통구"처럼 시+구가 함께 있는 지역은
      // house_trades.region이 "수원 영통구"(시 생략)로 저장돼 있어 불일치가 났음(안산 등에서
      // 실제 배포 후 테스트로 발견 - 전국 평균으로만 폴백됨). LAWD_CODES(이 앱이 실거래 수집
      // 때부터 써온 5자리 법정동코드→region 매핑, search-complex.js 등에서도 이미 씀)가
      // 유일한 정답 소스라, lawdCd가 오면 그걸로 region을 직접 찾아서 씀 - 문자열 가공에
      // 의존하지 않음. lawdCd가 없는(구형 프론트) 호출을 위해 region 직접 지정도 계속 지원.
      let region = req.query.region;
      // ⚠️ 2026-08(K-apt 2단계): kapt_complex_info.sigungu_code 조회에 lawdCd를 그대로 씀 -
      // region 문자열 매칭보다 신뢰도가 높음(구형 프론트가 region만 보낸 경우엔 역으로
      // LAWD_CODES에서 코드를 찾아 채움).
      let sigunguCode = lawdCd ? String(lawdCd) : null;
      if (lawdCd) {
        const found = LAWD_CODES.find((r) => r.code === String(lawdCd));
        if (found) region = found.name;
      } else if (region) {
        const found = LAWD_CODES.find((r) => r.name === region);
        if (found) sigunguCode = found.code;
      }
      if (!region || !dong || !size || !floor || !buildYear) {
        return res.status(400).json({ error: 'region(또는 lawdCd), dong, size, floor, buildYear 쿼리파라미터가 필요합니다.' });
      }
      // ⚠️ 2026-08(버그 수정): 처음엔 'villa'가 아니면 무조건 'apt'로 취급했는데(오피스텔/
      // 그외 유형까지 다 아파트로 잘못 분류됨), 프론트도 실제로는 항상 type=apt만 보내고
      // 있었던 게 겹쳐서 - 연립다세대·단독(villa) 물건을 열어도 AVM이 "아파트 시세"로
      // 계산돼 실제 매물보다 몇 배 높은 값이 나오는 버그가 있었음(안산 이동 530-21 실제
      // 테스트에서 발견 - 비교물건 1.65억 vs AVM 7.7억). type을 있는 그대로 넘겨서
      // AVM_MODEL_ID_BY_TYPE에 없는 유형(villa/officetel/other)은 정직하게 "지원 안 함"
      // 에러를 내도록 수정 - 잘못된 시장의 값을 그럴듯하게 보여주지 않음.
      const result = await getAvmEstimate(
        type || 'apt', region, dong,
        parseFloat(size), parseFloat(floor), parseInt(buildYear, 10),
        danji ? String(danji).trim() : null,
        sigunguCode,
        topFloor ? parseInt(topFloor, 10) : null,
        lat ? parseFloat(lat) : null,
        lon ? parseFloat(lon) : null
      );
      if (result.error) return res.status(422).json(result);
      return res.status(200).json(result);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  res.setHeader('Cache-Control', 's-maxage=1800, stale-while-revalidate=3600'); // 30분 캐시 (자주 안 바뀌는 정보라 캐싱)
  try {
    const [aptSale, aptRent, villaSale, singleSale, villaRent, singleRent] = await Promise.all([
      getRange('house_trades'),
      getRange('house_rent'),
      getRange('villa_trades'),
      getRange('single_trades'),
      getRange('villa_rent'),
      getRange('single_rent'),
    ]);
    return res.status(200).json({
      aptSale,
      aptRent,
      nonAptSale: mergeRanges(villaSale, singleSale),
      nonAptRent: mergeRanges(villaRent, singleRent),
      updatedAt: new Date().toISOString(),
    });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
