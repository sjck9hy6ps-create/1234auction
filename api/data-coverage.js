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

async function fetchKosisLatest(tblId, itmId, sigunguCd, orgId) {
  const url = `${KOSIS_DATA_URL}?serviceKey=${encodeURIComponent(KOSIS_API_KEY)}&format=json&orgId=${orgId || '101'}&tblId=${tblId}`
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

/* ⚠️ 2026-09 추가: 새 KOSIS 통계표(예: 미분양현황)를 연동하기 전, 그 표가 itmId를 어떻게
   나누는지 실제로 확인해봐야 하는 진단 전용 엔드포인트(mode=kosisRaw). itmId=ALL로 호출하면
   그 표에 있는 모든 항목(itmId/itmNm)이 섞여서 그대로 돌아오므로, 응답을 보고 "합계/총
   미분양호수"에 해당하는 정확한 itmId 코드를 찾아낸 뒤에야 population/households처럼
   전용 kind로 등록할 수 있음(위 population 도입 때도 이 과정을 거쳤음 - 상단 주석 참고).
   확인이 끝나면 이 mode는 남겨두어도 무방함(향후 다른 KOSIS 표 추가할 때 재사용 가능). */
function sleepMs(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
async function fetchKosisRaw(tblId, orgId, objL1, itmId, prdSe, newEstPrdCnt, extra) {
  // ⚠️ 2026-09: 표마다 필요한 분류축(objL2~objL8)이나 prdSe 코드가 다를 수 있어(실측:
  // DT_MLTM_2082는 population 표와 같은 prdSe='M'/objL1만으로는 INVALID_REQUEST_PARAMETER_ERROR/
  // NO_MANDATORY_REQUEST_PARAMETER_ERROR가 남) extra(objL2..objL8 등 임의 파라미터)를 그대로
  // 이어붙여서, 코드 재배포 없이 쿼리스트링만 바꿔가며 시행착오로 맞는 조합을 찾을 수 있게 함.
  let url = `${KOSIS_DATA_URL}?serviceKey=${encodeURIComponent(KOSIS_API_KEY)}&format=json&orgId=${orgId}&tblId=${tblId}`
    + `&objL1=${objL1}&itmId=${itmId || 'ALL'}`;
  if (prdSe) url += `&prdSe=${prdSe}`;
  url += `&newEstPrdCnt=${newEstPrdCnt || '3'}`;
  if (extra && typeof extra === 'object') {
    Object.keys(extra).forEach(k => { url += `&${k}=${encodeURIComponent(extra[k])}`; });
  }
  // ⚠️ 2026-09(실측 발견): "지방 우량아파트 스크리닝" 배지가 순위 목록의 서로 다른 시/군/구
  // 수십 곳을 짧은 시간에 연달아 조회하다 보니 KOSIS가 "초당 서비스 요청제한 횟수 초과"
  // 에러를 자주 반환함(캐시 미스인 지역만 실제 KOSIS 호출로 이어짐 - population/roneIndex처럼
  // 물건 하나당 한 번만 부르던 기존 사용 패턴에서는 안 보이던 문제). 이 에러 문구가 보이면
  // 짧게 대기 후 최대 2회 재시도함(클라이언트 쪽에서도 동시요청을 줄이지만, 서버도 자체
  // 방어선을 하나 더 둠 - 두 지역이 정확히 같은 타이밍에 캐시미스가 나는 경우까지 커버).
  let data, lastErr;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
      data = await r.json();
    } catch (e) { return { error: 'KOSIS 호출 실패: ' + e.message, url: redactKey(url) }; }
    if (data && data.OpenAPI_ServiceResponse) {
      const h = data.OpenAPI_ServiceResponse.cmmMsgHeader || {};
      const msg = h.returnAuthMsg || h.errMsg || '알 수 없는 오류';
      if (msg.indexOf('요청제한') !== -1 && attempt < 2) { lastErr = msg; await sleepMs(500 + attempt * 500); continue; }
      return { error: 'KOSIS 오류: ' + msg, url: redactKey(url), raw: data };
    }
    lastErr = null;
    break;
  }
  const items = data && data.response && data.response.body && data.response.body.items && data.response.body.items.item;
  return { url: redactKey(url), itemCount: Array.isArray(items) ? items.length : 0, items: items || [], raw: (!items) ? data : undefined };
}
// 진단용 응답의 url 필드에 인증키가 그대로 노출되지 않도록 마스킹함(이 엔드포인트들은 인증
// 없이 누구나 호출 가능하므로, url을 그대로 돌려주면 PUBLIC_DATA_API_KEY가 공개로 유출됨).
function redactKey(url) {
  return String(url).replace(/([?&]serviceKey=)[^&]+/, '$1***REDACTED***');
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
   KOSIS 시·군·구별 미분양현황 (mode=unsoldHousing) - 2026-09 추가
   ⚠️ mode=kosisRaw로 라이브 진단해서 확인한 내용:
   - tblId=DT_MLTM_2082("시·군·구별 미분양현황"), orgId=116(국토교통부) - population/
     households(orgId=101, 표준 5자리 행정구역코드) 표와 완전히 다른 체계임.
   - 이 표는 objL1(시/도) + objL2(시/군/구) 두 축을 다 요구하고(둘 다 없으면
     NO_MANDATORY_REQUEST_PARAMETER_ERROR), 두 코드 모두 표준 LAWD 코드가 아니라 이 표
     전용의 긴 영숫자 코드(예: 서울="13102871087A.0002", 서울 종로구=
     "13102871087B.0002")임 - 그래서 아래 UNSOLD_CODE_ROWS에 실제 라이브 조회로 받은
     전체 246개 행(16개 시/도 × 각 시/군/구, 세종만 예외)을 통째로 박아둠.
   - prdSe=M은 필수. 기본 numOfRows=10이라(문서에 명시 안 돼 있었는데 실측으로 발견 -
     newEstPrdCnt=13을 줘도 10건만 돌아옴) 12개월 추세를 온전히 받으려면 반드시
     numOfRows를 13 이상으로 같이 줘야 함(아래 fetchUnsoldLatest에서 extra.numOfRows=20).
   - 시/군/구 단위 세분화는 표마다 제각각임: 특·광역시는 구 단위(서울 25개구, 부산/대구/
     대전/울산 등 자치구), 그 외 도(경기/강원/충북/충남/전북/경북/경남)는 다구 시(수원시/
     성남시/청주시/창원시 등)가 하위 구로 안 쪼개지고 "시" 전체 합계 1건으로만 나옴(예:
     "경기|수원시" O, "경기|영통구" 같은 항목은 존재하지 않음) - 그래서 아래
     resolveUnsoldCode()는 정확히 일치하는 시/군/구가 없으면 시/도 합계("계")로 자동
     폴백함(다구 시 하위 구 주소가 들어와도 최소한 그 시/도 값은 보여줌).
   - ⚠️ 전남/광주 특이사항: 이 표는 전라남도+광주광역시를 "전남광주"라는 단일 시/도
     분류 하나로 묶어놨음(레거시 KOSIS 분류 체계로 추정) - 그래서 UNSOLD_SIDO_CODES에
     '전남'과 '광주' 둘 다 같은 C1 코드를 가리키도록 별칭을 추가해둠.
   - 기존 kosis_population_cache 테이블(스키마: id/latest_prd/latest_value/year_ago_prd/
     year_ago_value/fetched_at)을 그대로 재사용함(id에 'unsold|C1코드|C2코드' 접두어만
     붙여 구분) - 새 테이블/마이그레이션 불필요.
════════════════════════════════════ */
// 실측 확인된 전체 행(시도명, 시도코드=C1, 시군구명, 시군구코드=C2) - 2026-09 kosisRaw 진단으로 수집
const UNSOLD_CODE_ROWS = [
  ["서울","13102871087A.0002","계","13102871087B.0001"],["서울","13102871087A.0002","종로구","13102871087B.0002"],
  ["서울","13102871087A.0002","강남구","13102871087B.0003"],["서울","13102871087A.0002","중구","13102871087B.0004"],
  ["서울","13102871087A.0002","용산구","13102871087B.0005"],["서울","13102871087A.0002","강동구","13102871087B.0006"],
  ["서울","13102871087A.0002","성동구","13102871087B.0007"],["서울","13102871087A.0002","강북구","13102871087B.0008"],
  ["서울","13102871087A.0002","광진구","13102871087B.0009"],["서울","13102871087A.0002","강서구","13102871087B.0010"],
  ["서울","13102871087A.0002","관악구","13102871087B.0011"],["서울","13102871087A.0002","동대문구","13102871087B.0012"],
  ["서울","13102871087A.0002","중랑구","13102871087B.0013"],["서울","13102871087A.0002","성북구","13102871087B.0014"],
  ["서울","13102871087A.0002","구로구","13102871087B.0015"],["서울","13102871087A.0002","금천구","13102871087B.0016"],
  ["서울","13102871087A.0002","노원구","13102871087B.0017"],["서울","13102871087A.0002","도봉구","13102871087B.0018"],
  ["서울","13102871087A.0002","은평구","13102871087B.0019"],["서울","13102871087A.0002","동작구","13102871087B.0020"],
  ["서울","13102871087A.0002","서대문구","13102871087B.0021"],["서울","13102871087A.0002","마포구","13102871087B.0022"],
  ["서울","13102871087A.0002","양천구","13102871087B.0023"],["서울","13102871087A.0002","서초구","13102871087B.0024"],
  ["서울","13102871087A.0002","영등포구","13102871087B.0025"],["서울","13102871087A.0002","송파구","13102871087B.0026"],
  ["부산","13102871087A.0003","계","13102871087B.0001"],["부산","13102871087A.0003","중구","13102871087B.0004"],
  ["부산","13102871087A.0003","강서구","13102871087B.0010"],["부산","13102871087A.0003","서구","13102871087B.0028"],
  ["부산","13102871087A.0003","금정구","13102871087B.0031"],["부산","13102871087A.0003","동구","13102871087B.0032"],
  ["부산","13102871087A.0003","영도구","13102871087B.0034"],["부산","13102871087A.0003","기장군","13102871087B.0035"],
  ["부산","13102871087A.0003","남구","13102871087B.0036"],["부산","13102871087A.0003","부산진구","13102871087B.0037"],
  ["부산","13102871087A.0003","동래구","13102871087B.0039"],["부산","13102871087A.0003","북구","13102871087B.0040"],
  ["부산","13102871087A.0003","해운대구","13102871087B.0041"],["부산","13102871087A.0003","사하구","13102871087B.0042"],
  ["부산","13102871087A.0003","사상구","13102871087B.0044"],["부산","13102871087A.0003","수영구","13102871087B.0047"],
  ["부산","13102871087A.0003","연제구","13102871087B.0048"],
  ["대구","13102871087A.0004","계","13102871087B.0001"],["대구","13102871087A.0004","중구","13102871087B.0004"],
  ["대구","13102871087A.0004","서구","13102871087B.0028"],["대구","13102871087A.0004","동구","13102871087B.0032"],
  ["대구","13102871087A.0004","남구","13102871087B.0036"],["대구","13102871087A.0004","북구","13102871087B.0040"],
  ["대구","13102871087A.0004","수성구","13102871087B.0060"],["대구","13102871087A.0004","달서구","13102871087B.0062"],
  ["대구","13102871087A.0004","달성군","13102871087B.0064"],["대구","13102871087A.0004","군위군","13102871087B.0065"],
  ["인천","13102871087A.0005","계","13102871087B.0001"],["인천","13102871087A.0005","남동구","13102871087B.0068"],
  ["인천","13102871087A.0005","연수구","13102871087B.0069"],["인천","13102871087A.0005","미추홀구","13102871087B.0070"],
  ["인천","13102871087A.0005","부평구","13102871087B.0071"],["인천","13102871087A.0005","계양구","13102871087B.0072"],
  ["인천","13102871087A.0005","강화군","13102871087B.0073"],["인천","13102871087A.0005","옹진군","13102871087B.0074"],
  ["인천","13102871087A.0005","영종구","13102871087B.0080"],["인천","13102871087A.0005","서해구","13102871087B.0083"],
  ["인천","13102871087A.0005","검단구","13102871087B.0087"],["인천","13102871087A.0005","제물포구","13102871087B.0093"],
  ["대전","13102871087A.0007","계","13102871087B.0001"],["대전","13102871087A.0007","중구","13102871087B.0004"],
  ["대전","13102871087A.0007","서구","13102871087B.0028"],["대전","13102871087A.0007","동구","13102871087B.0032"],
  ["대전","13102871087A.0007","유성구","13102871087B.0075"],["대전","13102871087A.0007","대덕구","13102871087B.0076"],
  ["울산","13102871087A.0008","계","13102871087B.0001"],["울산","13102871087A.0008","중구","13102871087B.0004"],
  ["울산","13102871087A.0008","동구","13102871087B.0032"],["울산","13102871087A.0008","남구","13102871087B.0036"],
  ["울산","13102871087A.0008","북구","13102871087B.0040"],["울산","13102871087A.0008","울주군","13102871087B.0077"],
  ["경기","13102871087A.0009","계","13102871087B.0001"],["경기","13102871087A.0009","수원시","13102871087B.0078"],
  ["경기","13102871087A.0009","가평군","13102871087B.0081"],["경기","13102871087A.0009","성남시","13102871087B.0082"],
  ["경기","13102871087A.0009","의정부시","13102871087B.0084"],["경기","13102871087A.0009","고양시","13102871087B.0085"],
  ["경기","13102871087A.0009","안양시","13102871087B.0086"],["경기","13102871087A.0009","과천시","13102871087B.0088"],
  ["경기","13102871087A.0009","광명시","13102871087B.0089"],["경기","13102871087A.0009","부천시","13102871087B.0090"],
  ["경기","13102871087A.0009","광주시","13102871087B.0091"],["경기","13102871087A.0009","구리시","13102871087B.0092"],
  ["경기","13102871087A.0009","평택시","13102871087B.0094"],["경기","13102871087A.0009","군포시","13102871087B.0095"],
  ["경기","13102871087A.0009","동두천시","13102871087B.0096"],["경기","13102871087A.0009","안산시","13102871087B.0097"],
  ["경기","13102871087A.0009","김포시","13102871087B.0098"],["경기","13102871087A.0009","남양주시","13102871087B.0099"],
  ["경기","13102871087A.0009","오산시","13102871087B.0100"],["경기","13102871087A.0009","시흥시","13102871087B.0101"],
  ["경기","13102871087A.0009","안성시","13102871087B.0102"],["경기","13102871087A.0009","의왕시","13102871087B.0103"],
  ["경기","13102871087A.0009","양주시","13102871087B.0104"],["경기","13102871087A.0009","하남시","13102871087B.0105"],
  ["경기","13102871087A.0009","양평군","13102871087B.0106"],["경기","13102871087A.0009","용인시","13102871087B.0107"],
  ["경기","13102871087A.0009","파주시","13102871087B.0109"],["경기","13102871087A.0009","연천군","13102871087B.0110"],
  ["경기","13102871087A.0009","이천시","13102871087B.0111"],["경기","13102871087A.0009","여주시","13102871087B.0112"],
  ["경기","13102871087A.0009","화성시","13102871087B.0113"],["경기","13102871087A.0009","포천시","13102871087B.0114"],
  ["강원","13102871087A.0010","계","13102871087B.0001"],["강원","13102871087A.0010","춘천시","13102871087B.0115"],
  ["강원","13102871087A.0010","원주시","13102871087B.0116"],["강원","13102871087A.0010","강릉시","13102871087B.0117"],
  ["강원","13102871087A.0010","동해시","13102871087B.0118"],["강원","13102871087A.0010","태백시","13102871087B.0119"],
  ["강원","13102871087A.0010","속초시","13102871087B.0120"],["강원","13102871087A.0010","삼척시","13102871087B.0121"],
  ["강원","13102871087A.0010","홍천군","13102871087B.0122"],["강원","13102871087A.0010","횡성군","13102871087B.0123"],
  ["강원","13102871087A.0010","영월군","13102871087B.0124"],["강원","13102871087A.0010","평창군","13102871087B.0125"],
  ["강원","13102871087A.0010","정선군","13102871087B.0126"],["강원","13102871087A.0010","철원군","13102871087B.0127"],
  ["강원","13102871087A.0010","화천군","13102871087B.0128"],["강원","13102871087A.0010","양구군","13102871087B.0129"],
  ["강원","13102871087A.0010","인제군","13102871087B.0130"],["강원","13102871087A.0010","고성군","13102871087B.0131"],
  ["강원","13102871087A.0010","양양군","13102871087B.0132"],
  ["충북","13102871087A.0011","계","13102871087B.0001"],["충북","13102871087A.0011","청주시","13102871087B.0133"],
  ["충북","13102871087A.0011","괴산군","13102871087B.0134"],["충북","13102871087A.0011","충주시","13102871087B.0135"],
  ["충북","13102871087A.0011","제천시","13102871087B.0136"],["충북","13102871087A.0011","단양군","13102871087B.0137"],
  ["충북","13102871087A.0011","보은군","13102871087B.0139"],["충북","13102871087A.0011","영동군","13102871087B.0140"],
  ["충북","13102871087A.0011","옥천군","13102871087B.0141"],["충북","13102871087A.0011","증평군","13102871087B.0142"],
  ["충북","13102871087A.0011","음성군","13102871087B.0143"],["충북","13102871087A.0011","진천군","13102871087B.0144"],
  ["충남","13102871087A.0012","계","13102871087B.0001"],["충남","13102871087A.0012","천안시","13102871087B.0145"],
  ["충남","13102871087A.0012","공주시","13102871087B.0146"],["충남","13102871087A.0012","보령시","13102871087B.0147"],
  ["충남","13102871087A.0012","계룡시","13102871087B.0148"],["충남","13102871087A.0012","아산시","13102871087B.0149"],
  ["충남","13102871087A.0012","서산시","13102871087B.0150"],["충남","13102871087A.0012","금산군","13102871087B.0151"],
  ["충남","13102871087A.0012","논산시","13102871087B.0152"],["충남","13102871087A.0012","당진시","13102871087B.0153"],
  ["충남","13102871087A.0012","부여군","13102871087B.0154"],["충남","13102871087A.0012","서천군","13102871087B.0156"],
  ["충남","13102871087A.0012","청양군","13102871087B.0157"],["충남","13102871087A.0012","홍성군","13102871087B.0158"],
  ["충남","13102871087A.0012","예산군","13102871087B.0159"],["충남","13102871087A.0012","태안군","13102871087B.0160"],
  ["전북","13102871087A.0013","계","13102871087B.0001"],["전북","13102871087A.0013","전주시","13102871087B.0162"],
  ["전북","13102871087A.0013","군산시","13102871087B.0164"],["전북","13102871087A.0013","익산시","13102871087B.0165"],
  ["전북","13102871087A.0013","정읍시","13102871087B.0166"],["전북","13102871087A.0013","남원시","13102871087B.0167"],
  ["전북","13102871087A.0013","김제시","13102871087B.0168"],["전북","13102871087A.0013","완주군","13102871087B.0169"],
  ["전북","13102871087A.0013","진안군","13102871087B.0170"],["전북","13102871087A.0013","무주군","13102871087B.0171"],
  ["전북","13102871087A.0013","장수군","13102871087B.0172"],["전북","13102871087A.0013","임실군","13102871087B.0173"],
  ["전북","13102871087A.0013","순창군","13102871087B.0174"],["전북","13102871087A.0013","고창군","13102871087B.0175"],
  ["전북","13102871087A.0013","부안군","13102871087B.0176"],
  ["경북","13102871087A.0015","계","13102871087B.0001"],["경북","13102871087A.0015","포항시","13102871087B.0177"],
  ["경북","13102871087A.0015","경주시","13102871087B.0178"],["경북","13102871087A.0015","김천시","13102871087B.0179"],
  ["경북","13102871087A.0015","안동시","13102871087B.0180"],["경북","13102871087A.0015","구미시","13102871087B.0181"],
  ["경북","13102871087A.0015","영주시","13102871087B.0182"],["경북","13102871087A.0015","영천시","13102871087B.0183"],
  ["경북","13102871087A.0015","상주시","13102871087B.0184"],["경북","13102871087A.0015","문경시","13102871087B.0185"],
  ["경북","13102871087A.0015","경산시","13102871087B.0186"],["경북","13102871087A.0015","의성군","13102871087B.0187"],
  ["경북","13102871087A.0015","청송군","13102871087B.0188"],["경북","13102871087A.0015","영양군","13102871087B.0189"],
  ["경북","13102871087A.0015","영덕군","13102871087B.0190"],["경북","13102871087A.0015","청도군","13102871087B.0191"],
  ["경북","13102871087A.0015","고령군","13102871087B.0192"],["경북","13102871087A.0015","성주군","13102871087B.0193"],
  ["경북","13102871087A.0015","칠곡군","13102871087B.0194"],["경북","13102871087A.0015","예천군","13102871087B.0195"],
  ["경북","13102871087A.0015","봉화군","13102871087B.0196"],["경북","13102871087A.0015","울진군","13102871087B.0197"],
  ["경북","13102871087A.0015","울릉군","13102871087B.0198"],
  ["경남","13102871087A.0016","계","13102871087B.0001"],["경남","13102871087A.0016","고성군","13102871087B.0131"],
  ["경남","13102871087A.0016","창원시","13102871087B.0199"],["경남","13102871087A.0016","진주시","13102871087B.0201"],
  ["경남","13102871087A.0016","통영시","13102871087B.0202"],["경남","13102871087A.0016","사천시","13102871087B.0203"],
  ["경남","13102871087A.0016","김해시","13102871087B.0205"],["경남","13102871087A.0016","밀양시","13102871087B.0206"],
  ["경남","13102871087A.0016","거제시","13102871087B.0207"],["경남","13102871087A.0016","양산시","13102871087B.0208"],
  ["경남","13102871087A.0016","의령군","13102871087B.0209"],["경남","13102871087A.0016","함안군","13102871087B.0210"],
  ["경남","13102871087A.0016","창녕군","13102871087B.0211"],["경남","13102871087A.0016","남해군","13102871087B.0212"],
  ["경남","13102871087A.0016","하동군","13102871087B.0213"],["경남","13102871087A.0016","산청군","13102871087B.0214"],
  ["경남","13102871087A.0016","함양군","13102871087B.0215"],["경남","13102871087A.0016","거창군","13102871087B.0216"],
  ["경남","13102871087A.0016","합천군","13102871087B.0217"],
  ["제주","13102871087A.0017","계","13102871087B.0001"],["제주","13102871087A.0017","제주시","13102871087B.0218"],
  ["제주","13102871087A.0017","서귀포시","13102871087B.0219"],
  ["전남광주","13102871087A.0018","계","13102871087B.0001"],["전남광주","13102871087A.0018","목포시","13102871087B.0027"],
  ["전남광주","13102871087A.0018","서구","13102871087B.0028"],["전남광주","13102871087A.0018","여수시","13102871087B.0029"],
  ["전남광주","13102871087A.0018","순천시","13102871087B.0030"],["전남광주","13102871087A.0018","동구","13102871087B.0032"],
  ["전남광주","13102871087A.0018","나주시","13102871087B.0033"],["전남광주","13102871087A.0018","남구","13102871087B.0036"],
  ["전남광주","13102871087A.0018","광양시","13102871087B.0038"],["전남광주","13102871087A.0018","북구","13102871087B.0040"],
  ["전남광주","13102871087A.0018","광산구","13102871087B.0043"],["전남광주","13102871087A.0018","담양군","13102871087B.0045"],
  ["전남광주","13102871087A.0018","곡성군","13102871087B.0046"],["전남광주","13102871087A.0018","구례군","13102871087B.0049"],
  ["전남광주","13102871087A.0018","고흥군","13102871087B.0050"],["전남광주","13102871087A.0018","보성군","13102871087B.0051"],
  ["전남광주","13102871087A.0018","화순군","13102871087B.0052"],["전남광주","13102871087A.0018","장흥군","13102871087B.0053"],
  ["전남광주","13102871087A.0018","강진군","13102871087B.0054"],["전남광주","13102871087A.0018","해남군","13102871087B.0055"],
  ["전남광주","13102871087A.0018","영암군","13102871087B.0056"],["전남광주","13102871087A.0018","무안군","13102871087B.0057"],
  ["전남광주","13102871087A.0018","함평군","13102871087B.0058"],["전남광주","13102871087A.0018","영광군","13102871087B.0059"],
  ["전남광주","13102871087A.0018","장성군","13102871087B.0061"],["전남광주","13102871087A.0018","완도군","13102871087B.0063"],
  ["전남광주","13102871087A.0018","진도군","13102871087B.0066"],["전남광주","13102871087A.0018","신안군","13102871087B.0067"],
  ["세종","13102871087A.0019","계","13102871087B.0001"],["세종","13102871087A.0019","세종시","13102871087B.0079"],
];
const UNSOLD_SIDO_CODES = {};
const UNSOLD_SIGUNGU_CODES = {};
UNSOLD_CODE_ROWS.forEach(([sidoNm, c1, guNm, c2]) => {
  UNSOLD_SIDO_CODES[sidoNm] = c1;
  UNSOLD_SIGUNGU_CODES[sidoNm + '|' + guNm] = c2;
});
UNSOLD_SIDO_CODES['전남'] = UNSOLD_SIDO_CODES['전남광주'];
UNSOLD_SIDO_CODES['광주'] = UNSOLD_SIDO_CODES['전남광주'];
const UNSOLD_TBL = { tblId: 'DT_MLTM_2082', orgId: '116' };

// 사용자가 화면에서 보는 "인천광역시"/"경기도" 같은 정식 시/도 명칭과 "남동구"/"수원시" 같은
// 시/군/구 명칭을 받아 위 코드로 변환함. 다구 시 하위 구(예: "영통구")처럼 이 표에 없는
// 시/군/구가 들어오면 시/도 합계("계")로 자동 폴백함 - 위 주석 참고.
function resolveUnsoldCode(sidoRaw, sigunguRaw) {
  if (!sidoRaw) return null;
  let sido = String(sidoRaw).trim()
    .replace(/^전라남도$/, '전남').replace(/^전라북도$/, '전북')
    .replace(/^경상남도$/, '경남').replace(/^경상북도$/, '경북')
    .replace(/^충청남도$/, '충남').replace(/^충청북도$/, '충북')
    .replace(/(특별자치시|특별자치도|광역시|특별시)$/, '')
    .replace(/도$/, '');
  const c1 = UNSOLD_SIDO_CODES[sido];
  if (!c1) return null;
  const rowSidoKey = (sido === '전남' || sido === '광주') ? '전남광주' : sido;
  const gu = sigunguRaw ? String(sigunguRaw).trim().split(/\s+/)[0] : null;
  if (gu) {
    const c2 = UNSOLD_SIGUNGU_CODES[rowSidoKey + '|' + gu];
    if (c2) return { c1, c2, matchedLevel: 'sigungu', matchedName: gu };
  }
  // 정확히 일치하는 시/군/구가 없으면 시/도 합계로 폴백
  return { c1, c2: UNSOLD_SIGUNGU_CODES[rowSidoKey + '|계'], matchedLevel: 'sido', matchedName: sido };
}

async function fetchUnsoldLatest(c1, c2) {
  const r = await fetchKosisRaw(UNSOLD_TBL.tblId, UNSOLD_TBL.orgId, c1, 'ALL', 'M', '13', { objL2: c2, numOfRows: 20 });
  if (r.error) return { error: r.error };
  const items = r.items || [];
  if (!items.length) return { error: 'KOSIS 미분양 응답에 데이터가 없습니다.' };
  const sorted = items.slice().sort((a, b) => String(a.PRD_DE).localeCompare(String(b.PRD_DE)));
  const history = sorted.map(it => ({ prd: it.PRD_DE, value: parseFloat(it.DT) })).filter(h => Number.isFinite(h.value));
  if (!history.length) return { error: 'KOSIS 미분양 값을 숫자로 변환하지 못했습니다.' };
  const latest = history[history.length - 1];
  const yearAgo = history.length >= 13 ? history[history.length - 13] : history[0];
  return { latestPrd: latest.prd, latestValue: latest.value, yearAgoPrd: yearAgo.prd, yearAgoValue: yearAgo.value };
}

// 기존 kosis_population_cache 테이블을 그대로 재사용(id에 'unsold|' 접두어만 붙임).
async function getUnsoldTrend(c1, c2, force) {
  const cacheId = 'unsold|' + c1 + '|' + c2;
  if (!force) {
    try {
      const { data: cached, error } = await supabase.from('kosis_population_cache').select('*').eq('id', cacheId).maybeSingle();
      if (!error && cached && (Date.now() - new Date(cached.fetched_at).getTime()) < KOSIS_FRESH_MS) {
        return { latestPrd: cached.latest_prd, latestValue: cached.latest_value, yearAgoPrd: cached.year_ago_prd, yearAgoValue: cached.year_ago_value, cached: true };
      }
    } catch (e) { console.warn('kosis_population_cache(unsold) 조회 예외:', e.message); }
  }
  const fresh = await fetchUnsoldLatest(c1, c2);
  if (fresh.error) return fresh;
  try {
    const { error: upsertErr } = await supabase.from('kosis_population_cache').upsert({
      id: cacheId, latest_prd: fresh.latestPrd, latest_value: fresh.latestValue,
      year_ago_prd: fresh.yearAgoPrd, year_ago_value: fresh.yearAgoValue, fetched_at: new Date().toISOString(),
    });
    if (upsertErr) console.warn('kosis_population_cache(unsold) 저장 실패:', upsertErr.message);
  } catch (e) { console.warn('kosis_population_cache(unsold) 저장 예외:', e.message); }
  return { ...fresh, cached: false };
}

/* ════════════════════════════════════
   청약홈(한국부동산원) APT 무순위·잔여세대 (mode=applyhomeRaw, 진단 전용) - 2026-09 추가
   ⚠️ KOSIS 미분양(위)은 시/군/구 "집계 숫자"만 주고 어느 단지인지는 전혀 모른다 - 사용자가
   "미분양 아파트를 지도에 마커로, 내 입찰 물건과 거리도 보고 싶다"고 요청해서, 단지명+주소가
   있는 다른 공공데이터를 웹 리서치로 찾음: 한국부동산원 청약홈이 "무순위·잔여세대"(청약
   추첨에서 다 안 팔려 무순위/선착순으로 다시 파는 신축 분양단지) 목록을 제공함
   (data.go.kr/data/15098547/openapi.do, getRemndrLttotPblancDetail 오퍼레이션).
   ⚠️ 이 API는 apis.data.go.kr이 아니라 별도 게이트웨이 odcloud.kr을 씀(공공데이터포털이
   "파일데이터"를 자동변환해 만든 REST API 계열 - population/roneIndex 등 지금까지 쓰던
   apis.data.go.kr 계열과 인증키 재사용은 되지만 호출 방식·페이징 파라미터가 다름):
     GET https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getRemndrLttotPblancDetail
         ?page=1&perPage=200&serviceKey=...
   ⚠️ 중요한 한계(사용자에게 이미 설명함): (1) 신축 분양단지의 "무순위/잔여세대"만 잡히고
   구축 아파트 재고 전체의 미분양은 안 잡힘(KOSIS 쪽이 그 역할). (2) 위경도 필드가 아예
   없음 - 공급위치(주소)를 프론트에서 기존 Kakao 지오코딩으로 좌표 변환해야 마커를 찍을 수
   있음. (3) 주소 형식이 지저분함(도로명 16%, "OO 일원" 43%, 괄호 표기 34%, 번지 없음 30%,
   블록코드 포함 - 실측 기준, GitHub 공개 구현체 확인). 아직 이 API가 우리 계정에 활용신청
   승인돼 있는지도 모르므로(청약홈은 population 때와 마찬가지로 한국부동산원이 제공기관이라
   별도 활용신청이 필요할 수 있음), 이 함수는 순수 진단용이고 실제 mode=unsoldComplex 같은
   전용 엔드포인트는 이 응답을 실제로 보고 필드명을 확인한 뒤에 만들어야 함(population 도입
   때와 같은 순서).
════════════════════════════════════ */
const APPLYHOME_BASE = 'https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/';
const APPLYHOME_SRC = {
  remnant: 'getRemndrLttotPblancDetail', // 무순위·잔여세대 (미분양에 가장 가까움)
  apt: 'getAPTLttotPblancDetail',        // 일반 분양 공고
  opt: 'getOPTLttotPblancDetail',        // 임의공급
};
async function fetchApplyhomeRaw(srcKey, page, perPage, cond) {
  const op = APPLYHOME_SRC[srcKey] || APPLYHOME_SRC.remnant;
  let url = APPLYHOME_BASE + op + '?page=' + (page || '1') + '&perPage=' + (perPage || '20')
    + '&serviceKey=' + encodeURIComponent(KOSIS_API_KEY);
  if (cond) url += '&' + encodeURIComponent('cond[' + cond.field + '::' + (cond.op || 'EQ') + ']') + '=' + encodeURIComponent(cond.value);
  let data;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
    data = await r.json();
  } catch (e) { return { error: '청약홈 호출 실패: ' + e.message, url: redactKey(url) }; }
  // odcloud는 에러도 200으로 주고 body에 담는 경우가 있어(예: {"error":"..."}) 방어적으로 확인.
  if (data && (data.error || data.errorCode)) {
    return { error: '청약홈 오류: ' + (data.error || data.errorMessage || data.errorCode), url: redactKey(url), raw: data };
  }
  // ⚠️ 2026-09: 활용신청 미승인 등 odcloud 자체 오류는 {"error":...}가 아니라
  // {"code":-4,"msg":"등록되지 않은 인증키 입니다."} 형태로 옴(실측 확인) - 위 data.error 체크로는
  // 안 걸러져서 추가함.
  if (data && typeof data.code === 'number' && data.code < 0) {
    return { error: '청약홈 오류: ' + (data.msg || data.code), url: redactKey(url), raw: data };
  }
  const items = (data && data.data) || [];
  // ⚠️ 응답이 비어 있으면(활용신청 미승인/필드명 상이 등 원인 추정 불가) 진단을 위해 raw 전체를
  // 그대로 돌려줌 - items가 있을 때는 raw를 안 붙여 응답 용량을 아낌.
  return {
    url: redactKey(url), totalCount: data && data.totalCount, currentCount: data && data.currentCount, items,
    raw: items.length ? undefined : data,
  };
}

/* ════════════════════════════════════
   미분양(무순위·잔여세대 + 임의공급) 단지 목록 (mode=unsoldComplex) - 2026-09 추가
   ⚠️ 위 applyhomeRaw 진단으로 활용신청 승인 확인 + 실제 필드 확인 완료. 이 함수는 그걸 바탕으로
   "지도에 마커로 찍을 수 있는 단지 목록"을 만듦. 좌표는 여기서 만들지 않음(이 API 자체에
   위경도가 없고, 서버에 Kakao REST 키가 없어 서버사이드 지오코딩이 안 됨) - 프론트가 이미 갖고
   있는 Kakao 지오코딩 캐시(coordCache)로 주소→좌표 변환은 클라이언트에서 함.
   ⚠️ "무순위·잔여세대"(remnant)뿐 아니라 "임의공급"(opt, 무순위에서도 남은 물량을 선착순으로
   다시 파는 단계)도 같이 합침 - 둘 다 "청약으로 다 안 팔렸다"는 신호라 미분양 스크리닝
   목적에는 같은 카테고리로 취급해도 됨(HOUSE_SECD_NM 필드로 구분은 남겨둠).
   ⚠️ 날짜 형식이 소스마다 다름(remnant는 "2026-09-16", opt는 "20260915") - normDate()로
   통일. 접수마감이 지난 공고를 빼지 않는 이유: 접수는 끝났어도 그 회차에 남았던 세대가 그 뒤
   다음 회차 무순위로 또 나올 수 있어("보통 회차를 거듭한다"는 게 무순위의 특성), 최근
   공고일 기준으로만 자르고 접수상태로는 안 자름 - 마감 지난 것도 "이 근처에 최근 미분양이
   있었다"는 참고 신호로는 유효함.
   ⚠️ 아래 SQL을 Supabase에 먼저 한 번 실행해야 합니다:
     create table if not exists unsold_complex_cache (
       id text primary key,
       items jsonb,
       fetched_at timestamptz
     );
════════════════════════════════════ */
const UNSOLD_COMPLEX_FRESH_MS = 1000 * 60 * 60 * 24; // 24시간 - 무순위 공고는 매일 갱신되지만 지도 스크리닝 용도라 이 정도 지연은 무방함
const UNSOLD_COMPLEX_WINDOW_DAYS = 540; // 최근 약 18개월 - 그 이상 지난 공고는 이미 다 팔렸을 가능성이 높음

function normDate(s) {
  if (!s) return null;
  const digits = String(s).replace(/-/g, '');
  if (digits.length !== 8) return null;
  return digits.slice(0, 4) + '-' + digits.slice(4, 6) + '-' + digits.slice(6, 8);
}
// 블록코드("D1-1BL", "A-5블록")와 "OO 일원" 접미사만 가볍게 제거함 - 나머지 정제(괄호 추출,
// 번지 우선 등)는 프론트의 기존 다단계 지오코딩(tryStepGeocode)이 이미 여러 후보를 시도하므로
// 서버에서 과하게 다듬지 않음(README 실측: 도로명 16%뿐이라 완벽한 정제는 애초에 어려움).
function lightCleanAddr(addr) {
  if (!addr) return '';
  return String(addr)
    .replace(/[A-Za-z]\d*-\d+\s*(BL|블록)/gi, '')
    .replace(/\s*일원\s*$/, '')
    .trim();
}

async function fetchUnsoldComplexFresh() {
  const cutoff = new Date(Date.now() - UNSOLD_COMPLEX_WINDOW_DAYS * 86400000);
  const cutoffStr = cutoff.toISOString().slice(0, 10).replace(/-/g, '');
  const sources = [
    { key: 'remnant', label: '무순위·잔여세대' },
    { key: 'opt', label: '임의공급' },
  ];
  const merged = [];
  const errors = [];
  for (const src of sources) {
    const r = await fetchApplyhomeRaw(src.key, '1', '500');
    if (r.error) { errors.push(src.label + ': ' + r.error); continue; }
    (r.items || []).forEach(it => {
      const noticeDate = normDate(it.RCRIT_PBLANC_DE);
      if (!noticeDate || noticeDate.replace(/-/g, '') < cutoffStr) return; // 너무 오래된 공고는 제외
      const addr = it.HSSPLY_ADRES ? String(it.HSSPLY_ADRES).trim() : '';
      if (!addr) return; // 주소 없으면 지도에 못 찍으므로 제외
      merged.push({
        pblancNo: it.PBLANC_NO || it.HOUSE_MANAGE_NO,
        name: it.HOUSE_NM || '(단지명 미상)',
        addr, addrClean: lightCleanAddr(addr),
        zip: it.HSSPLY_ZIP || null,
        totalSupply: Number.isFinite(Number(it.TOT_SUPLY_HSHLDCO)) ? Number(it.TOT_SUPLY_HSHLDCO) : null,
        sido: it.SUBSCRPT_AREA_CODE_NM || null,
        noticeDate,
        receiptStart: normDate(it.SUBSCRPT_RCEPT_BGNDE || it.GNRL_RCEPT_BGNDE),
        receiptEnd: normDate(it.SUBSCRPT_RCEPT_ENDDE || it.GNRL_RCEPT_ENDDE),
        url: it.PBLANC_URL || null,
        kind: it.HOUSE_SECD_NM || src.label,
      });
    });
  }
  if (!merged.length && errors.length) return { error: errors.join(' / ') };
  // 같은 단지가 무순위 회차를 여러 번 거치며 중복 등록될 수 있어 단지명+주소 기준으로 중복
  // 제거하되, 더 최근 공고(noticeDate가 더 큰 것)를 남김 - "지금도 안 팔리고 있다"는 최신
  // 상태가 더 중요한 정보라서임.
  const byKey = new Map();
  merged.forEach(it => {
    const key = it.name + '|' + it.addrClean;
    const prev = byKey.get(key);
    if (!prev || it.noticeDate > prev.noticeDate) byKey.set(key, it);
  });
  const list = Array.from(byKey.values()).sort((a, b) => b.noticeDate.localeCompare(a.noticeDate));
  return { items: list };
}

async function getUnsoldComplexList(force) {
  const cacheId = 'all';
  if (!force) {
    try {
      const { data: cached, error } = await supabase.from('unsold_complex_cache').select('*').eq('id', cacheId).maybeSingle();
      if (!error && cached && (Date.now() - new Date(cached.fetched_at).getTime()) < UNSOLD_COMPLEX_FRESH_MS) {
        return { items: cached.items || [], cached: true };
      }
    } catch (e) { console.warn('unsold_complex_cache 조회 예외:', e.message); }
  }
  const fresh = await fetchUnsoldComplexFresh();
  if (fresh.error) return fresh;
  try {
    const { error: upsertErr } = await supabase.from('unsold_complex_cache').upsert({
      id: cacheId, items: fresh.items, fetched_at: new Date().toISOString(),
    });
    if (upsertErr) console.warn('unsold_complex_cache 저장 실패:', upsertErr.message);
  } catch (e) { console.warn('unsold_complex_cache 저장 예외:', e.message); }
  return { items: fresh.items, cached: false };
}

/* ════════════════════════════════════
   후발주자 예측 랭킹 (mode=leaderFollower) - 2026-09 추가
   사용자 요청: "대장아파트가 상승하면 후발주자로 따라오는 아파트들이 있다. 그 순서를 알아내서
   곧 오를 수 있다는 예측에 쓰고 싶다." + "서울 제외 지역에서 법정동 기준으로 대장아파트를
   선정하고, 모든 아파트 순위를 100위까지 만들어달라(순위밖도 표기)."

   ⚠️ 방법론(의도적으로 단순하게 설계함 - 표본이 얇은 지방 단지가 많아 과적합 위험이 큼):
   1) 시/군/구 하나를 지정하면(예: "경북 구미시"), 이미 돈되는지역(getPriceMomentum
      Relative)에서 쓰던 getBucketDanjiPrices(region,dong,danji별 구간 평단가)를 그대로
      재사용해서 법정동×단지별 구간 시계열을 만듦(신규 SQL 불필요 - rpc_bucket_avg_price가
      p_sido 인자에 "시도 시군구" 풀네임을 그대로 넣으면 그 시/군/구로 정확히 좁혀짐을
      실측으로 확인함).
   2) 구간은 7개(아파트 40일×7=280일 - house_trades 수집기간이 2025-12-01부터라 최대
      약 290일치뿐이라 7구간이 한도, 연립다세대는 60일×7=420일).
   3) 법정동별 "대장" = 그 동 안에서 baseline(7구간 전체 평균) 평단가가 가장 높은 단지
      (표본 부족한 대장 오탐 방지를 위해 총 거래건수 LF_MIN_TOTAL_COUNT 이상 요구).
   4) 같은 법정동의 나머지 단지(후발주자 후보)마다:
      - 표본부족 구간은 돈되는지역과 동일한 방식으로 직전/직후 구간과 합쳐 보정.
      - "최근 갭"(gapPct) = 대장의 최근 2구간 상승률 - 이 단지의 최근 2구간 상승률.
        양수면 "대장은 오르고 있는데 이 단지는 아직 덜 올랐다"는 뜻(갭메우기 여지).
      - "과거 동행성"(corr) = 두 단지의 구간별 등락률(수익률) 시계열의 피어슨 상관계수를
        lag 0~2구간(0~80일 뒤처짐)으로 각각 계산해 최댓값을 채택(단순 동시상관이 아니라
        "대장이 먼저 움직이고 얼마 뒤에 따라 움직이는지"까지 확인하기 위함).
      - 두 조건(과거에 실제로 같이 움직인 이력이 있고 + 지금 갭이 벌어져 있음)을 모두
        만족해야만 "후발주자 후보"로 인정함(둘 중 하나만으로는 우연의 일치일 수 있음).
   5) score = corr × gapPct로 전체 시/군/구의 모든 법정동을 통틀어 한 줄 세우기 → 순위
      1~100위까지 매기고, 그 밖(조건 미달 포함)은 "순위밖"으로 사유와 함께 표기.
   ⚠️ 상관계수·시차 추정 둘 다 최대 6개 구간 수익률(=7구간)만으로 계산하는 얇은 통계라
      "확정적 예측"이 아니라 "과거 패턴상 후보"라는 참고 신호로만 취급해야 함 - 프론트에도
      이 caveat을 표시함.
   ⚠️ 아래 SQL을 Supabase에 먼저 한 번 실행해서 캐시 테이블을 만들어야 합니다:
     create table if not exists leader_follower_cache (
       id text primary key,
       payload jsonb,
       fetched_at timestamptz
     );
════════════════════════════════════ */
const LF_FRESH_MS = 1000 * 60 * 60 * 24; // 24시간 - 하루 안에 여러 번 볼 이유가 없는 무거운 집계라 넉넉히
// ⚠️ 2026-09(#458): 과거자료(2017-09~)가 다 들어와서 house_trades가 실질적으로 9년치를
// 커버하게 됨에 따라 버킷 수를 7→26으로 늘림(아파트 40일×26구간≈2.85년 - 2022년 하락기·
// 2023~24년 회복기·2025~26년 흐름까지 최소 한 번 이상의 상승/하락 국면을 포괄하도록).
// 최소 표본(LF_MIN_TOTAL_COUNT)과 최대 시차(LF_MAX_LAG)도 늘어난 버킷 수에 비례해 올림.
const LF_BUCKET_COUNT = 26;
const LF_MIN_TOTAL_COUNT = 20; // 26구간 합계 거래건수 - 이보다 적으면 대장/후발주자 후보 모두에서 제외
const LF_MIN_CORR = 0.3; // 이 미만이면 "우연히 같이 움직인 걸로 보기 어렵다"고 판단해 제외
const LF_MAX_LAG = 6; // 0~6구간(아파트 기준 최대 240일≈8개월) 뒤처짐까지 확인
// ⚠️ 2026-09: corrByLag 진단(lag 1~16 전체 곡선) 결과, 상관계수가 lag별로 완만한 봉우리 없이
// 톱니처럼 요동침(표본이 26버킷→차분 후 19~25개뿐이라 우연히 튀는 값이 잘 나옴) - 게다가 지금
// 로직이 "6개 lag 중 최댓값"을 뽑는 방식이라 다중비교 문제로 노이즈를 신호로 오판하기 쉬움.
// 표본수/6회 비교를 감안한 통계적 유의 기준으로 재검증한 결과 0.35는 너무 관대했고, 실제로
// "우연이 아니다"라고 볼 수 있는 건 0.55 이상뿐이었음(부산 해운대구 실측: 두산위브더제니스
// 0.71·현대 0.68만 통과, 나머지 5개 동은 0.38~0.55로 노이즈와 구분 안 됨) - 0.55로 상향.
const LF_LEAD_MIN_CORR = 0.55;
// LF_MAX_LAG를 16까지 늘려서 봐도 6 너머에서 더 뚜렷한 신호가 나오지 않고 요동만 커짐을
// 확인했으므로 6 그대로 유지. corrByLag 진단 필드는 향후 재검증 필요시를 위해 남겨둠.
const LF_DIAG_MAX_LAG = 16;
const LF_TOP_N = 100;
const LF_MIN_HOUSEHOLDS = 100; // 회전율 기준 대장 후보 최소 세대수 - 나홀로 단지가 우연한 회전율로 뽑히는 것 방지
function pearsonCorr(xs, ys) {
  const n = xs.length;
  if (n < 3) return null; // 점 3개 미만이면 상관계수 자체가 의미 없음
  const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) { const dx = xs[i] - mx, dy = ys[i] - my; sxy += dx * dy; sxx += dx * dx; syy += dy * dy; }
  if (sxx === 0 || syy === 0) return null;
  return sxy / Math.sqrt(sxx * syy);
}
// 돈되는지역(getPriceMomentumRelative)과 동일한 방식 - 표본부족(count<minCount) 구간은
// 직전→직후 순서로 합쳐서 채움. 반환: { prices[N](null 없음), returns[N-1](구간별 등락률) }
function fillBucketSeries(avgArr, countArr, minCount) {
  const n = avgArr.length;
  const prices = [];
  for (let i = 0; i < n; i++) {
    let sum = (avgArr[i] || 0) * (countArr[i] || 0), cnt = countArr[i] || 0;
    let back = i - 1;
    while (cnt < minCount && back >= 0) { sum += (avgArr[back] || 0) * (countArr[back] || 0); cnt += (countArr[back] || 0); back--; }
    let fwd = i + 1;
    while (cnt < minCount && fwd < n) { sum += (avgArr[fwd] || 0) * (countArr[fwd] || 0); cnt += (countArr[fwd] || 0); fwd++; }
    prices.push(cnt > 0 ? sum / cnt : null);
  }
  const firstValid = prices.find(p => p !== null);
  if (firstValid == null) return null; // 이 단지는 전 구간에 거래가 하나도 없음
  for (let i = 0; i < prices.length; i++) { if (prices[i] === null) prices[i] = firstValid; }
  const returns = [];
  for (let i = 1; i < prices.length; i++) { returns.push(prices[i - 1] > 0 ? (prices[i] - prices[i - 1]) / prices[i - 1] : 0); }
  return { prices, returns };
}
async function computeLeaderFollowerFresh(type, region) {
  const bucketDays = bucketDaysFor(type);
  const minCount = minBucketCountFor(type);
  const today = todayInt();
  const buckets = [];
  for (let i = 0; i < LF_BUCKET_COUNT; i++) {
    const startDays = bucketDays * (LF_BUCKET_COUNT - i), endDays = bucketDays * (LF_BUCKET_COUNT - 1 - i);
    buckets.push({ start: daysAgoInt(startDays), end: i === LF_BUCKET_COUNT - 1 ? today + 1 : daysAgoInt(endDays) });
  }
  const bucketMaps = await Promise.all(buckets.map(b => getBucketDanjiPrices(type, b.start, b.end, region)));
  // ⚠️ 2026-09(#464, 사용자 피드백): "순위를 단순 거래량으로만 매기는 건 잘못됐다 - 17년도
  // 자료부터 근거자료로 써서 대장아파트를 꼽은 것처럼, 평단가·거래량·세대수대비 회전율 등으로
  // 정말 가치있는 2등·3등을 골라야 한다"는 지적 반영. 위 26버킷(최근 약 35개월)은 대장의
  // "선행성(시차상관)" 판정용 창일 뿐이라 원래도 순위용 근거로 쓰기엔 기간이 짧음 - 그래서
  // 순위 계산 전용으로 2017-09(과거자료 백필 시작 시점) ~ 오늘 전체 이력을 한 번 더(단일
  // 버킷) 집계 조회함. rpc_bucket_avg_price가 이미 서버에서 groupby 집계해 반환하므로
  // (get-house.js처럼 원시 row를 클라이언트로 내려주는 방식이 아님) 9년치를 한 번에 물어도
  // 응답은 danji당 1행뿐이라 부담이 없음.
  const FULL_HIST_START = 20170901;
  const fullHistMap = await getBucketDanjiPrices(type, FULL_HIST_START, today + 1, region);
  const fullHistByDong = {}; // dong -> danjiName -> { avg, count }
  Object.values(fullHistMap).forEach((entry) => {
    if (!fullHistByDong[entry.dong]) fullHistByDong[entry.dong] = {};
    Object.entries(entry.danjis).forEach(([danjiName, d]) => {
      fullHistByDong[entry.dong][danjiName] = { avg: d.avg, count: d.count };
    });
  });
  function intToDate(n) { const s = String(n); return new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)); }
  const FULL_HIST_DAYS = Math.max(1, Math.round((intToDate(today + 1) - intToDate(FULL_HIST_START)) / 86400000));
  // dongMap: dong -> danjiName -> { avgArr[N], countArr[N] }
  const dongMap = {};
  bucketMaps.forEach((m, bi) => {
    Object.values(m).forEach(entry => {
      const dong = entry.dong;
      if (!dongMap[dong]) dongMap[dong] = {};
      Object.entries(entry.danjis).forEach(([danjiName, d]) => {
        if (!danjiName || danjiName === '(단지미상)') return; // 단지명 없는 거래는 대장/후발주자 비교 대상에서 제외
        if (!dongMap[dong][danjiName]) dongMap[dong][danjiName] = { avgArr: new Array(LF_BUCKET_COUNT).fill(null), countArr: new Array(LF_BUCKET_COUNT).fill(0) };
        dongMap[dong][danjiName].avgArr[bi] = d.avg;
        dongMap[dong][danjiName].countArr[bi] = d.count;
      });
    });
  });
  // ⚠️ 2026-09(회전율 기반 대장 선정): "평단가가 제일 높은 단지"가 아니라 "실제로 가장 활발히
  // 거래되는(=거래선호도가 높은) 단지"를 대장으로 뽑아달라는 요청 반영. 부산 해운대구로 실측한
  // 결과, 평단가 기준이었을 땐 엘시티/두산위브더제니스처럼 시장이 실제로 대장이라 부르는 단지가
  // 거래가 워낙 희소하다는 이유로 후보에도 못 들었음 - 회전율(거래건수÷세대수)로 바꾸면 이
  // 문제가 풀림. 세대수는 AVM(mode=avmEstimate)에서 이미 쓰는 것과 같은 kapt_complex_info
  // 테이블을, 같은 정규화 매칭 방식(normalizeComplexName)으로 재사용함 - 여기서는 법정동
  // 전체를 한 번에 조회해 매칭하므로 단지마다 왕복하지 않음(성능).
  const householdMap = {}; // `${법정동}|${normalizeComplexName(단지명)}` -> 세대수
  // ⚠️ 2026-09: 진단 결과 - 이 조회 로직(지역코드 매칭, 쿼리) 자체는 정상이고(에러 없음),
  // kapt_complex_info 테이블에 households가 채워진 행이 전국 어디에도 없어서(부산/경기/대구
  // 등 7개 지역 실측 - 전부 0건) 회전율 폴백이 항상 비어있었음. sync-kapt.yml(K-apt 동기화
  // GitHub Actions)이 실제로는 한 번도 성공적으로 households를 채운 적이 없다는 뜻 - 이 파일
  // 코드가 아니라 그 워크플로/시크릿 쪽 문제라 여기서 고칠 수 있는 부분이 아님(아래 대응 참고).
  try {
    const lawdEntry = LAWD_CODES.find((r) => r.name === region);
    if (lawdEntry) {
      const { data: kaptRows } = await supabase
        .from('kapt_complex_info')
        .select('kapt_name, as3, households')
        .eq('sigungu_code', lawdEntry.code)
        .not('households', 'is', null);
      (kaptRows || []).forEach((r) => {
        if (!r.as3 || !(r.households > 0)) return;
        const key = `${r.as3}|${normalizeComplexName(r.kapt_name)}`;
        // 같은 키에 여러 행이 있으면(리모델링 등으로 K-apt에 신구 레코드가 같이 남아있는 경우)
        // 세대수가 더 큰 쪽을 보수적으로 채택
        if (!householdMap[key] || r.households > householdMap[key]) householdMap[key] = r.households;
      });
    }
  } catch (e) { /* K-apt 조회 실패해도 막지 않음 - 회전율 없이 가격 기준 폴백으로 계속 진행 */ }
  const windowDays = bucketDays * LF_BUCKET_COUNT;

  const leaders = [];
  const candidates = []; // 순위 매길 후보(대장 자신은 제외)
  Object.entries(dongMap).forEach(([dong, danjis]) => {
    // 이 법정동에서 최소 거래요건을 만족하는 단지만 후보로 삼음
    const qualified = Object.entries(danjis)
      .map(([name, d]) => {
        const totalCount = d.countArr.reduce((a, b) => a + b, 0);
        const filled = fillBucketSeries(d.avgArr, d.countArr, minCount);
        if (!filled || totalCount < LF_MIN_TOTAL_COUNT) return null;
        const baseline = filled.prices.reduce((a, b) => a + b, 0) / filled.prices.length;
        const households = householdMap[`${dong}|${normalizeComplexName(name)}`] || null;
        // 연환산 회전율(%) = 구간 내 거래건수÷세대수를 1년 기준으로 환산 - "1년에 세대의 몇 %가
        // 거래되는지"로 단지 규모와 무관하게 비교 가능한 값으로 만듦
        const turnoverPct = households ? Math.round((totalCount / households) * (365 / windowDays) * 1000) / 10 : null;
        // ⚠️ 2026-09(#464): 순위(2등·3등) 산정 전용 - 2017-09~ 전체 이력 기준 평단가/거래량과,
        // 그 전체 거래량으로 다시 계산한 회전율. 대장의 선행성 판정(위 turnoverPct/households)은
        // 그대로 35개월 창을 씀 - 그건 "최근 흐름"을 봐야 하는 다른 목적이라 건드리지 않음.
        const fh = (fullHistByDong[dong] || {})[name] || null;
        const fullPpp = fh ? fh.avg : baseline;
        const fullCount = fh ? fh.count : totalCount;
        const fullTurnoverPct = households ? Math.round((fullCount / households) * (365 / FULL_HIST_DAYS) * 1000) / 10 : null;
        return { name, totalCount, filled, baseline, households, turnoverPct, fullPpp, fullCount, fullTurnoverPct, avgArr: d.avgArr, countArr: d.countArr };
      })
      .filter(Boolean);
    if (qualified.length < 2) return; // 대장-후발주자 관계 자체가 성립하려면 최소 2개 단지 필요

    // ⚠️ 2026-09(#458): "평단가/회전율이 1등인 단지"가 아니라 "이 동네 시세를 실제로 먼저
    // 반영하는(선행하는) 단지"를 대장으로 뽑는 로직으로 교체. 방법: 후보 단지마다 "이 법정동
    // 나머지 전체(자기 자신을 뺀 leave-one-out 집계)"를 만들어서, 자기 자신의 수익률(returns)이
    // 나머지 동네의 수익률을 몇 구간 앞서서(lag 1~LF_MAX_LAG) 예고하는지 시차상관으로 확인함.
    // (leave-one-out인 이유: 그냥 "동 전체 평균"과 비교하면 자기 자신의 비중 때문에 상관계수가
    // 항상 높게 나오는 자기상관 문제가 생김 - 자신을 뺀 나머지와 비교해야 "내가 나머지를
    // 이끈다"는 관계가 깨끗하게 나옴.) 데이터가 얇아 이 판정이 안 되는 법정동은 기존 방식
    // (회전율 1위 → 그마저 안 되면 평단가 1위)으로 순서대로 폴백함.
    const bucketN = LF_BUCKET_COUNT; // ⚠️ 아래쪽 leaderRecentPct 계산에서 쓰는 n(=leader.filled.prices.length)과 이름 겹치지 않게 별도로 둠
    const sumWeighted = new Array(bucketN).fill(0), sumCount = new Array(bucketN).fill(0);
    qualified.forEach((d) => {
      for (let i = 0; i < bucketN; i++) {
        sumWeighted[i] += (d.avgArr[i] || 0) * (d.countArr[i] || 0);
        sumCount[i] += (d.countArr[i] || 0);
      }
    });
    qualified.forEach((d) => {
      const restAvgArr = new Array(bucketN), restCountArr = new Array(bucketN);
      for (let i = 0; i < bucketN; i++) {
        const rc = sumCount[i] - (d.countArr[i] || 0);
        restCountArr[i] = rc;
        restAvgArr[i] = rc > 0 ? (sumWeighted[i] - (d.avgArr[i] || 0) * (d.countArr[i] || 0)) / rc : null;
      }
      const restFilled = fillBucketSeries(restAvgArr, restCountArr, minCount);
      let bestCorr = null, bestLag = null;
      const corrByLag = [];
      if (restFilled) {
        for (let lag = 1; lag <= LF_DIAG_MAX_LAG; lag++) {
          const leaderPart = d.filled.returns.slice(0, d.filled.returns.length - lag);
          const restPart = restFilled.returns.slice(lag);
          const c = pearsonCorr(leaderPart, restPart);
          corrByLag.push([lag, c != null ? Math.round(c * 1000) / 1000 : null]);
          if (lag <= LF_MAX_LAG && c != null && (bestCorr == null || c > bestCorr)) { bestCorr = c; bestLag = lag; }
        }
      }
      d.leadCorr = bestCorr;
      d.leadLag = bestLag;
      d.corrByLag = corrByLag;
    });
    const leadEligible = qualified.filter((d) => d.leadCorr != null && d.leadCorr >= LF_LEAD_MIN_CORR);
    let leader, leaderSource;
    if (leadEligible.length > 0) {
      leadEligible.sort((a, b) => b.leadCorr - a.leadCorr);
      leader = leadEligible[0];
      leaderSource = 'lead_lag';
    } else {
      // 회전율(세대수 데이터 있고 LF_MIN_HOUSEHOLDS 이상) 기준 1위를 대장으로 삼되, 이 법정동의
      // 모든 단지가 K-apt 미매칭이거나 소규모라 회전율을 못 구하면 예전 방식(평단가 최고)으로 폴백
      // - 대장 자체가 사라지는 것보다 정확도가 낮은 값이라도 있는 게 나음(프론트에 출처 표시).
      const turnoverEligible = qualified.filter((d) => d.turnoverPct != null && d.households >= LF_MIN_HOUSEHOLDS);
      if (turnoverEligible.length > 0) {
        turnoverEligible.sort((a, b) => b.turnoverPct - a.turnoverPct);
        leader = turnoverEligible[0];
        leaderSource = 'turnover';
      } else {
        leader = qualified.slice().sort((a, b) => b.baseline - a.baseline)[0];
        leaderSource = 'price_fallback';
      }
    }
    const n = leader.filled.prices.length;
    const leaderRecentPct = Math.round(((leader.filled.prices[n - 1] / leader.filled.prices[n - 3]) - 1) * 1000) / 10;
    leaders.push({
      dong, danji: leader.name, totalCount: leader.totalCount, ppp: Math.round(leader.baseline), recentPct: leaderRecentPct,
      households: leader.households, turnoverPct: leader.turnoverPct, leaderSource,
      leadCorr: leader.leadCorr != null ? Math.round(leader.leadCorr * 100) / 100 : null,
      leadLag: leader.leadLag,
      corrByLag: leader.corrByLag, // ⚠️ 2026-09 진단용 임시 필드 - lag별 상관계수 전체 곡선(추후 제거 예정)
    });
    if (leaderRecentPct <= 0) return; // 대장 자체가 안 올랐으면 "따라 오를 후발주자"라는 전제가 성립하지 않음
    qualified.filter((f) => f.name !== leader.name).forEach(f => {
      const followerRecentPct = Math.round(((f.filled.prices[n - 1] / f.filled.prices[n - 3]) - 1) * 1000) / 10;
      const gapPct = Math.round((leaderRecentPct - followerRecentPct) * 10) / 10;
      let bestCorr = null, bestLag = null;
      for (let lag = 0; lag <= LF_MAX_LAG; lag++) {
        const followerReturns = f.filled.returns.slice(lag);
        const leaderReturns = leader.filled.returns.slice(0, leader.filled.returns.length - lag);
        const c = pearsonCorr(leaderReturns, followerReturns);
        if (c != null && (bestCorr == null || c > bestCorr)) { bestCorr = c; bestLag = lag; }
      }
      const qualifies = bestCorr != null && bestCorr >= LF_MIN_CORR && gapPct > 0;
      let reason = null;
      if (!qualifies) {
        if (bestCorr == null) reason = '대장과의 상관관계 계산 불가(표본부족)';
        else if (bestCorr < LF_MIN_CORR) reason = '과거 대장과 동행한 이력이 약함(상관계수 ' + bestCorr.toFixed(2) + ')';
        else reason = '이미 대장만큼(또는 더) 올라 갭이 없음';
      }
      candidates.push({
        dong, danji: f.name, leaderDanji: leader.name, totalCount: f.totalCount,
        gapPct, corr: bestCorr != null ? Math.round(bestCorr * 100) / 100 : null, lag: bestLag,
        leaderRecentPct, followerRecentPct,
        // ⚠️ 2026-09: "현재 상태(실제 상승률 %)"/"예상 흐름(남은 갭 %)"에 실감나는 금액을 같이
        // 보여달라는 요청 - 평단가 자체(followerPpp)와, 대장과의 평단가 차이(gapAmount, 만원/평 -
        // "앞으로 이만큼 더 오를 여력"으로 해석 가능)를 추가.
        followerPpp: Math.round(f.baseline), gapAmount: Math.round(leader.baseline - f.baseline),
        score: qualifies ? bestCorr * gapPct : null,
        qualifies, reason,
        // ⚠️ 2026-09(#464): 순위 산정(인기·가치 복합점수)에 쓰는 전체이력(2017-09~) 지표.
        fullPpp: Math.round(f.fullPpp), fullCount: f.fullCount, fullTurnoverPct: f.fullTurnoverPct,
      });
    });
  });
  // ⚠️ 2026-09(#461, 사용자 피드백): "서울 마포구처럼 구 안 동들이 사실상 같은 생활권인 곳과
  // 달리, 지방 시/군은 동마다 시장 성격 자체가 다를 수 있어(신도시/구도심/산업단지 등) 시/군/구
  // 전체를 하나로 통합해 100위를 매기면 서로 다른 동네 후보끼리 뒤섞여 비교된다"는 지적 반영.
  // 각 후보의 갭%/상관계수는 원래도 "자기 법정동 대장" 기준 상대값이라 스케일 자체는 이미
  // 맞춰져 있지만(절대가격 아님), 그래도 "곧 따라잡힐 갭"인지의 신뢰도는 같은 동네 안에서
  // 비교할 때가 더 의미 있음 - 그래서 시/군/구 전체 통합 순위 대신, 법정동별로 그룹을 나누고
  // 각 그룹 안에서 1위~N위를 매기는 방식으로 변경함(기존 flat ranked[] → rankedByDong[]).
  // ⚠️ 2026-09(#463→#464, 사용자 피드백 반영 2차): "동행성/갭 조건을 만족하는 단지만 순위가
  // 생기는 게 이상하다"는 1차 피드백에 이어 "단순 거래량만으로 순위를 매기는 것도 잘못됐다 -
  // 17년도 자료부터 근거로 삼아 대장아파트를 꼽은 것처럼, 평단가·거래량·세대수대비 회전율 등
  // 여러 근거로 '정말 가치있는' 2등·3등을 골라야 한다"는 2차 피드백까지 반영함. qualifies
  // (동행성 0.3 이상 & 갭 있음)는 여전히 순위 포함 여부가 아니라 "(후발주자)" 표식 여부로만
  // 쓰고, 순위 자체는 세 지표(fullPpp/fullCount/fullTurnoverPct, 전부 2017-09~ 전체이력
  // 기준)를 동 안에서 각각 백분위로 바꿔 평균한 복합 가치점수(valueScore)로 매김 - 단위가
  // 서로 다른 지표(만원/평, 건수, %)를 그냥 더하면 안 되니 순위(percentile)로 정규화 후
  // 평균하는 방식을 씀. 세대수 데이터가 아직 없는 단지(K-apt 동기화 진행 중이라 흔함)는
  // fullTurnoverPct가 null이라 그 지표만 빼고 나머지 지표의 평균으로 계산됨(완전히 배제되지
  // 않음).
  function percentileScores(list, keyFn) {
    const withVal = list.map((item, i) => ({ i, v: keyFn(item) })).filter((x) => x.v != null);
    withVal.sort((a, b) => b.v - a.v);
    const n = withVal.length;
    const out = {};
    withVal.forEach((x, rank) => { out[x.i] = n > 1 ? (n - rank) / n : 1; });
    return out;
  }
  const dongGroups = {};
  candidates.forEach((c) => {
    if (!dongGroups[c.dong]) dongGroups[c.dong] = [];
    dongGroups[c.dong].push(c);
  });
  const rankedByDong = [];
  const unranked = [];
  Object.entries(dongGroups).forEach(([dong, list]) => {
    const pppScores = percentileScores(list, (c) => c.fullPpp);
    const volScores = percentileScores(list, (c) => c.fullCount);
    const turnoverScores = percentileScores(list, (c) => c.fullTurnoverPct);
    list.forEach((c, i) => {
      const parts = [pppScores[i], volScores[i], turnoverScores[i]].filter((v) => v != null);
      c.valueScore = parts.length ? parts.reduce((a, b) => a + b, 0) / parts.length : 0;
    });
    // 복합 가치점수 desc. 동률이면 이름순으로 고정해 호출마다 순서가 흔들리지 않게 함.
    list.sort((a, b) => {
      if (b.valueScore !== a.valueScore) return b.valueScore - a.valueScore;
      return a.danji.localeCompare(b.danji);
    });
    const items = [];
    list.forEach((c) => {
      if (items.length < LF_TOP_N) {
        items.push({ ...c, rank: items.length + 1, isFollower: c.qualifies });
      } else {
        unranked.push({ ...c, reason: '순위 ' + LF_TOP_N + '위 밖(종합 가치점수 기준)' });
      }
    });
    if (items.length) {
      rankedByDong.push({ dong, leaderDanji: items[0].leaderDanji, topScore: items[0].valueScore, items });
    }
  });
  // 동 그룹의 나열 순서도 같은 기준으로 "이 동 1위 단지의 종합 가치점수"가 높은 순으로 둠.
  rankedByDong.sort((a, b) => b.topScore - a.topScore);
  leaders.sort((a, b) => b.totalCount - a.totalCount);
  return { region, type, bucketDays, bucketCount: LF_BUCKET_COUNT, leaders, rankedByDong, unranked, totalCandidates: candidates.length };
}
async function getLeaderFollowerRank(type, region, force) {
  const cacheId = region + '|' + type;
  if (!force) {
    try {
      const { data: cached, error } = await supabase.from('leader_follower_cache').select('*').eq('id', cacheId).maybeSingle();
      if (!error && cached && (Date.now() - new Date(cached.fetched_at).getTime()) < LF_FRESH_MS) {
        return { ...cached.payload, cached: true };
      }
    } catch (e) { console.warn('leader_follower_cache 조회 예외:', e.message); }
  }
  const fresh = await computeLeaderFollowerFresh(type, region);
  try {
    const { error: upsertErr } = await supabase.from('leader_follower_cache').upsert({ id: cacheId, payload: fresh, fetched_at: new Date().toISOString() });
    if (upsertErr) console.warn('leader_follower_cache 저장 실패:', upsertErr.message);
  } catch (e) { console.warn('leader_follower_cache 저장 예외:', e.message); }
  return { ...fresh, cached: false };
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
     ⚠️ 2026-08(단지 단위 세분화 + 공간격자 + 법정동 내 평형·연식 세분화): 처음엔 "키"가
     항상 region|dong(법정동)이었는데, 실제 배포 후 확인해보니 같은 법정동 안에서도 단지별
     편차가 커서(예: 고잔동 실측 - 준공연도 다른 단지 섞이며 평단가 3.4배 차이) 오차가 컸음.
     지금은 4단계 폴백 체인으로 키를 찾음(아파트/연립다세대 1단계만 다름):
       1) 아파트: region|dong|danji(단지 표본 충분) / 연립다세대: grid_{lat}_{lon}(공간격자
          1km, 좌표가 있고 표본 충분한 경우)
       2) region|dong|평형대|연식단계(법정동+평형대+연식단계 조합 표본이 있으면 - 사용자
          요청 "AVM 추정가를 법정동 기준만 적용하지 말고 연식·평형 필터를 적용한 값으로")
       3) region|dong(그마저 표본부족 시 법정동 단위로 승격됨)
       4) region(그 법정동조차 표본부족 시 시군구로 승격) → dong_effects["__default__"]
          (전국 평균, 완전히 새 지역일 때만)
     각 단계는 train-avm.py의 group_key 승격 순서와 반드시 일치해야 함(avmPredict 함수
     본문 주석 참고).
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

// ⚠️ 2026-08(사용자 요청: "AVM 추정가를 법정동 기준만 적용하지 말고, 법정동 내 연식·평형
// 필터를 적용한 값으로") - train-avm.py의 PYEONG_TIER_BOUNDS/AGE_TIER_BOUNDS와 반드시 같은
// 경계값이어야 함(학습/서빙 그룹키 불일치 방지 - grid_key와 같은 종류의 요구사항). index.html의
// PYEONG_TIERS/VILLA_AGE_TIERS와도 동일한 경계를 씀(사용자에게 보이는 평형대/연식단계 개념과
// AVM 내부 그룹핑 개념을 일치시켜 "이 동네 이 평형·연식대"라는 말이 실제로 같은 뜻이 되게 함).
const AVM_PYEONG_TIER_BOUNDS = [['t1', 33], ['t2', 44], ['t3', 55], ['t4', 66], ['t5', 85], ['t6', Infinity]];
const AVM_AGE_TIER_BOUNDS = [['premium', 0, 3], ['new', 4, 8], ['semi', 9, 15], ['old', 16, 25], ['aged', 26, Infinity]];
function avmPyeongTier(sizeM2) {
  if (!(sizeM2 > 0)) return null;
  for (const [key, maxM2] of AVM_PYEONG_TIER_BOUNDS) { if (sizeM2 <= maxM2) return key; }
  return 't6';
}
function avmAgeTier(ageYears) {
  if (ageYears == null || !Number.isFinite(ageYears)) return null;
  for (const [key, lo, hi] of AVM_AGE_TIER_BOUNDS) { if (ageYears >= lo && ageYears <= hi) return key; }
  return 'aged';
}

function avmPredict(model, features, region, dong, danji, gridKey, tierKey) {
  const coefs = model.global_coefs || {};
  // ⚠️ 2026-08(K-apt 2단계): 하드코딩된 6개 목록 대신 실제 저장된 계수의 키를 그대로 씀 -
  // 모델마다(apt_v1엔 log_households가 있고 villa_v1엔 없음) 변수 개수가 달라졌고, 앞으로
  // #298(역세권/학군) 등이 추가돼도 이 함수를 다시 안 고쳐도 되게 하기 위함.
  let logPpp = 0;
  Object.keys(coefs).forEach(k => { logPpp += (coefs[k] || 0) * (features[k] || 0); });
  const logPppFromFeatures = logPpp; // 진단용 - 그룹효과(dong_effects) 더하기 전 값

  const dongEffects = model.dong_effects || {};
  // 진단/신뢰도 표시용 - grid(공간격자, 빌라 전용 1차 단위)/danji(단지) 정확 매칭인지,
  // dong_tier(법정동+평형대+연식단계) 단위인지, dong(법정동) 단위인지, region(시군구)
  // 폴백인지, 아예 전국 평균 폴백인지를 그대로 응답에 남겨 프론트에서 "이 값이 얼마나
  // 구체적인 데이터에 기반했는지"를 사용자에게 투명하게 보여줄 수 있게 함. 순서는
  // train-avm.py의 승격 순서와 반드시 같아야 함(아파트: danji→dong_tier→dong→region,
  // 빌라: grid→dong_tier→dong→region - gridKey는 빌라 예측일 때만 계산되므로 아파트에는
  // 영향이 없고, danjiKey는 빌라 dong_effects에 애초에 존재하지 않는 키 형식이라 둘이 서로
  // 간섭하지 않음).
  // ⚠️ 2026-08(사용자 요청: "AVM 추정가를 법정동 기준만 적용하지 말고, 법정동 내 연식·평형
  // 필터를 적용한 값으로") - danji/grid 표본이 부족해 법정동으로 승격됐을 때도, 그 동
  // 전체를 뭉뚱그리기 전에 "같은 법정동 + 같은 평형대 + 같은 연식단계" 조합의 표본이
  // 있으면 그걸 먼저 씀(tierKey). train-avm.py clean_and_featurize()의 tier_key 승격
  // 로직과 반드시 같은 순서여야 함.
  let effect, effectUsed;
  const danjiKey = danji ? `${region}|${dong}|${danji}` : null;
  if (gridKey && dongEffects[gridKey] !== undefined) {
    effect = dongEffects[gridKey]; effectUsed = 'grid';
  } else if (danjiKey && dongEffects[danjiKey] !== undefined) {
    effect = dongEffects[danjiKey]; effectUsed = 'danji';
  } else if (tierKey && dongEffects[tierKey] !== undefined) {
    effect = dongEffects[tierKey]; effectUsed = 'dong_tier';
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
  // ⚠️ 2026-08(사용자 요청: "AVM 추정가를 법정동 기준만 적용하지 말고, 법정동 내 연식·평형
  // 필터를 적용한 값으로") - danji/grid가 없거나 표본부족으로 법정동까지 승격되는 경우를
  // 위한 중간 키. age는 avmFeatureVector 내부와 똑같이 "오늘 기준" 연식으로 계산해야
  // train-avm.py의 tier_key(deal_year - build_year, 학습 시 각 거래의 연식)와 같은 경계
  // 로직을 타되, 서빙은 항상 "지금 팔면"이 기준이라 avmFeatureVector의 age 계산과 일치시킴.
  const ageForTier = Math.max(0, AVM_CURRENT_YEAR_FALLBACK() - buildYear);
  const pyeongTier = avmPyeongTier(size);
  const ageTier = avmAgeTier(ageForTier);
  const tierKey = (pyeongTier && ageTier) ? `${region}|${dong}|${pyeongTier}|${ageTier}` : null;
  const { ppp, effectUsed, groupEffect, logPppFromFeatures } = avmPredict(model, features, region, dong, danji, gridKey, tierKey);
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

     ════════════════════════════════════
     신고가(전고점 갱신) 거래량 지역 순위 - 2026-08 추가
     "돈되는 지역(가격모멘텀)"으로 이미 상승세가 확인될 즈음이면 이미 진입시점이 늦다는
     사용자 피드백에 따라, "지금 막 신고가가 갱신되고 있는 지역"을 더 이른 신호로 보여줌.

     신고가 정의: 지도 마커의 ★신고가 배지(calcNewHigh, index.html)는 "같은 건물의 같은
     평형에서 최근 6개월 거래 최고가가 그 이전 전체 거래 최고가를 넘었는지"를 건물 단위로
     판정하는데, 이건 특정 건물 하나의 배지 표시용이라 이미 로딩된 데이터(지도 뷰포트) 안에서만
     계산 가능함. 이 순위는 "전국 어디서 지금 신고가가 많이 나오고 있는지"를 봐야 해서 DB
     전체를 SQL에서 집계해야 함 - 그래서 건물+평형 대신 건물(danji) 단위 평당가(ppp, 다른
     RPC와 동일한 정규화 - 평형이 달라도 비교 가능)로 판정 기준을 바꿈: 각 거래를 그 거래
     이전(strict히 더 이른 날짜)의 같은 danji 거래들과 비교해서, 그 danji 역대 최고 평당가를
     처음으로 넘어선 거래를 "신고가 거래"로 셈. (윈도우 함수 RANGE BETWEEN UNBOUNDED
     PRECEDING AND 1 PRECEDING을 deal_date(정수 YYYYMMDD) 기준으로 쓰면 "이 거래보다 이전
     날짜의 모든 행"이 정확히 잡힘 - 같은 날짜 거래끼리는 서로 비교하지 않음. YYYYMMDD 정수
     빼기 1이 실제 달력상 하루 전과 정확히 일치하지 않는 날도 있지만(예: 20260301-1=20260229는
     실존 안 할 수도 있음) 부등호 비교 목적("더 작은 정수인가")에는 문제 없음.)
     danji 이력이 전혀 없는(그 danji의 첫 거래) 건은 비교 대상이 없어 "갱신"이라 부를 수
     없으므로 제외함(prior_max_ppp is null).
     ⚠️ 성능 주의: rpc_bucket_avg_price와 마찬가지로 danji 단위 partition이 꼭 필요해서(다른
     건물끼리 가격을 비교하면 의미가 없음) "전국"(시/도 미지정) 조회는 무거울 수 있음 -
     danji 그룹 수가 늘면서 rpc_bucket_avg_price가 겪었던 것과 같은 종류의 타임아웃 위험이
     있음. 배포 후 실제로 "전국" 단일 구간은 8초대로 확인됨(#420) - 다만 아래 v2에서 흐름을
     보려고 6구간을 도는 만큼, "전국" 스코프는 6배 가까이 걸릴 수 있어 순차 호출로 바꿈
     (getPriceMomentumSimple과 동일한 이유 - 동시 커넥션 과다로 인한 타임아웃 방지).

     ⚠️ 2026-08(v2, 사용자 피드백 2건 반영):
     1) "돈되는 지역처럼 흐름(증감 추이)이 보고 싶다" - 원래는 p_cutoff 이후 전체를 한 번에
        세어 "건수" 하나만 반환했는데, 돈되는지역과 동일한 6구간(momentumBuckets, 아파트
        40일×6/빌라 60일×6)으로 나눠 구간별 건수를 배열로 반환하도록 p_end(구간 종료일,
        NULL이면 상한 없음)를 추가함. JS(getNewHighDongsTrend)가 이 함수를 구간마다 호출해서
        합침.
     2) "신축 거래가 신고가로 오탐될 수 있는지 확인해달라" - 실제로 있었음: 새로 준공된
        단지는 첫 거래(분양가) 이후 두세 번째 거래부터 자연스러운 "프리미엄" 상승이 붙어
        반복적으로 "역대 최고가 경신"으로 잡히는데, 이건 그 동네 전체의 개발호재/모멘텀이
        아니라 그 한 단지의 초기 시세형성 과정일 뿐이라 신호로 부적절함. rpc_bucket_avg_price
        (돈되는지역)가 이미 신축을 집계에서 빼는 것과 동일 기준(아파트 준공 2년 이내, 빌라
        3년 이내)으로, 신축 danji의 거래는 "신고가 이벤트"로 셈하지 않도록(=신고가 여부
        판정 자체에서 제외, ranked 대상에서 배제) build_year 필터를 추가함. (과거 이력
        비교용 prior_max_ppp 계산에는 계속 포함시킴 - 신축이었을 때의 가격도 나중에 그
        단지가 "신축"딱지를 뗀 뒤의 진짜 신고가를 판정할 때는 여전히 유효한 과거 최고가여야
        하기 때문.)
     반환 컬럼(counts 배열 계산은 JS에서 합산하므로 이 함수 자체는 예전처럼 단일 cnt만
     반환 - p_end로 구간을 좁혀서 호출하는 건 호출하는 쪽의 몫)이 그대로라 CREATE OR REPLACE로
     충분하지만, 매개변수(p_end)가 새로 추가돼 이전 시그니처와 달라지므로 이전 함수를 먼저
     지워야 함(그대로 두면 6-인자/7-인자 버전이 둘 다 남아 헷갈릴 수 있음).
     ------------------------------------------------------------------
     drop function if exists rpc_new_high_dongs(int, text, text, int, int, int);
     create function rpc_new_high_dongs(p_cutoff int, p_end int, p_sido text, p_type text, p_min_size int default 10, p_max_size int default 300, p_limit int default 50)
     returns table(region text, dong text, cnt bigint)
     language sql stable as $$
       with raw as (
         select region, dong, coalesce(nullif(danji, ''), '(단지미상)') as danji, deal_date, build_year,
           (price::numeric / nullif(size, 0)) * 3.305785 as ppp
         from house_trades
           where p_type = 'apt' and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, coalesce(nullif(danji, ''), '(단지미상)') as danji, deal_date, build_year,
           (price::numeric / nullif(size, 0)) * 3.305785 as ppp
         from villa_trades
           where p_type = 'villa' and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, coalesce(nullif(danji, ''), '(단지미상)') as danji, deal_date, build_year,
           (price::numeric / nullif(size, 0)) * 3.305785 as ppp
         from single_trades
           where p_type = 'villa' and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
       ),
       ranked as (
         select region, dong, danji, deal_date, build_year, ppp,
           max(ppp) over (
             partition by region, dong, danji
             order by deal_date
             range between unbounded preceding and 1 preceding
           ) as prior_max_ppp
         from raw
       )
       select region, dong, count(*) as cnt
       from ranked
       where deal_date >= p_cutoff
         and (p_end is null or deal_date < p_end)
         and prior_max_ppp is not null and ppp > prior_max_ppp
         -- 신축(아파트 준공 2년 이내, 빌라 3년 이내) 거래는 신고가 이벤트로 셈하지 않음
         and not (build_year is not null
                  and build_year >= (extract(year from current_date)::int - case when p_type = 'apt' then 2 else 3 end))
       group by region, dong
       order by cnt desc
       limit p_limit;
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
// 신고가(전고점 갱신) 거래 - 구간 하나(start~end)에 대한 (region,dong)별 건수. rpc_new_high_dongs
// 참고(위 SQL 주석). getNewHighDongsTrend가 이 함수를 구간마다 호출해서 흐름을 합침.
// ⚠️ p_limit을 넉넉히 크게 줌(구간별 상위 50개만 받으면, "총합 상위 50개" 랭킹을 뒤에서
// 다시 계산할 때 어떤 구간에선 50위 밖이었지만 다른 구간 합산하면 상위권일 동(dong)이
// 누락될 수 있음 - 그래서 이 함수 자체에서는 사실상 전부(최대 2000개) 받고, 최종 "상위
// N개"는 getNewHighDongsTrend가 6구간 합산 이후에 자름).
const NEW_HIGH_BUCKET_FETCH_LIMIT = 2000;
// ⚠️ 2026-08 추가: 무거운 윈도우함수 RPC라 간헐적으로 실패하는 게 이미 알려진 상태였는데
// (아래 getNewHighDongsTrend 주석 참고), 실패하면 그냥 []를 반환해버려서 "이 구간엔
// 진짜 신고가가 0건이었다"와 "이 구간 조회 자체가 실패했다"를 구분할 수 없었음. 그 결과
// 전국+아파트처럼 무거운 조합에서 6구간 중 몇 개가 실패해도 나머지만으로 정상 응답(200)이
// 만들어져서 "0→0→17→0→0→0"처럼 한 구간만 값이 있는 깨진 흐름이 그대로 사용자에게
// 나갔고, 심지어 이 깨진 응답이 30분 캐시(+60분 stale-while-revalidate)에 그대로 박혀서
// 최대 90분 동안 계속 같은 깨진 데이터가 나가는 문제로 이어졌음(실측: 전국+아파트 재조회시
// 17.9초 걸려 캐시 없이 새로 계산하면 6구간 전부 정상적으로 채워지는 것 확인 - RPC 자체
// 버그가 아니라 순수 타임아웃성 실패였음). 최대 2회 재시도 + 실패 여부를 별도로 반환해서
// 호출부가 "이 응답은 일부 구간이 끝내 실패했다"는 걸 알고 캐시하지 않도록 함.
async function getNewHighDongsBucket(type, sido, start, end, retries) {
  const maxRetries = retries == null ? 2 : retries;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const { data, error } = await supabase.rpc('rpc_new_high_dongs', {
        p_cutoff: start, p_end: end, p_sido: sido || null, p_type: type,
        p_min_size: MOMENTUM_SIZE_MIN, p_max_size: MOMENTUM_SIZE_MAX, p_limit: NEW_HIGH_BUCKET_FETCH_LIMIT,
      });
      if (error) {
        console.warn(`newHighDongs(rpc): ${type} 조회 실패(시도 ${attempt + 1}/${maxRetries + 1}) -`, error.message);
        continue;
      }
      return { rows: (data || []).map(r => ({ region: r.region, dong: r.dong, count: Number(r.cnt) })), ok: true };
    } catch (e) {
      console.warn(`newHighDongs(rpc): ${type} 조회 예외(시도 ${attempt + 1}/${maxRetries + 1}) -`, e.message);
    }
  }
  return { rows: [], ok: false }; // 재시도까지 다 실패 - 진짜 0건이 아니라 "조회 실패"임을 표시
}
// 신고가 "흐름" - 돈되는지역(getPriceMomentum)과 같은 6구간(momentumBuckets)으로 나눠 구간별
// 신고가 건수를 배열로 반환. 순위는 6구간 합계(total) 내림차순.
// ⚠️ 2026-08 실측 수정: rpc_new_high_dongs는 rpc_bucket_avg_price와 달리 raw CTE에
// deal_date 필터가 없음(윈도우 함수가 "이 거래 이전 전체 이력"을 봐야 prior_max_ppp를 정확히
// 계산할 수 있어서, 구간 시작일 이전 거래도 다 필요함 - 의도된 설계). 그 말은 6구간 중
// 어느 구간을 조회하든 매번 해당 시/도의 전체 이력에 대해 동일한 무거운 윈도우 계산을
// 다시 돌린다는 뜻이라, "시/도를 지정했으니 가볍다"는 가정이 성립하지 않음. 실제로 배포 후
// 경기(단일 sido, type=apt 하나만)조차 6구간을 Promise.all로 병렬 호출했을 때 간헐적으로
// 전부 빈 배열로 실패하는 게 확인됨(#422 - 동시 커넥션 과다로 인한 타임아웃, getPriceMomentumSimple
// 이 전국 스코프에서 겪은 것과 같은 종류의 문제가 경기처럼 danji 수가 많은 단일 시/도에서도
// 재현됨). 그래서 "전국만 순차, 시/도 지정은 병렬"이라는 기존 구분을 없애고 항상 순차 호출로
// 통일함 - 느리더라도 매번 동시 커넥션 6개가 아니라 1개씩만 쓰니 훨씬 안정적임.
// 반환값에 ok(모든 구간이 성공했는지)를 같이 담아서, 호출부가 실패 섞인 응답을 캐시하지
// 않도록 함(위 주석의 "0→0→17→0→0→0" 캐시 고착 버그 참고).
async function getNewHighDongsTrend(type, sido, limit) {
  const buckets = momentumBuckets(type); // 아파트 40일×6구간 / 빌라 60일×6구간 - 돈되는지역과 동일 창
  const bucketResults = [];
  for (const b of buckets) {
    bucketResults.push(await getNewHighDongsBucket(type, sido, b.start, b.end));
  }
  const allOk = bucketResults.every(b => b.ok);
  const acc = {}; // key(region|dong) -> { region, dong, counts:[6개], total }
  bucketResults.forEach((b, i) => {
    b.rows.forEach(r => {
      const key = r.region + '|' + r.dong;
      if (!acc[key]) acc[key] = { region: r.region, dong: r.dong, counts: [0, 0, 0, 0, 0, 0] };
      acc[key].counts[i] = r.count;
    });
  });
  const list = Object.values(acc).map(x => ({ ...x, total: x.counts.reduce((a, b) => a + b, 0) }));
  list.sort((a, b) => b.total - a.total);
  return { list: list.slice(0, limit), ok: allOk };
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
  // 진단 전용(mode=monthlyGapCheck) - 2026-09 추가. 사용자 요청: "지방아파트 매매 데이터에
  // 백데이터(CSV)를 채워넣기 전에, 지금 업로드된 기간 안에 비어있는 달이 있는지 먼저 확인하고
  // 싶다"에 대응. house_trades(또는 villa_trades)의 min~max 기간을 월 단위로 잘라서 달마다
  // 전체 건수와 "지방"(서울·경기·인천 제외) 건수를 세어봄 - 정상 수집된 달은 수만 건씩
  // 꾸준히 나오므로, 유독 0건이거나 확 줄어든 달이 있으면 그 기간의 수집이 비어있다는 뜻.
  if (req.query.mode === 'monthlyGapCheck') {
    res.setHeader('Cache-Control', 'no-store');
    try {
      const table = req.query.table === 'villa' ? 'villa_trades' : 'house_trades';
      const range = await getRange(table);
      if (range.min == null || range.max == null) return res.status(200).json({ table, months: [], warnings: range.warnings });
      const toDate = n => new Date(Math.floor(n / 10000), Math.floor((n % 10000) / 100) - 1, n % 100);
      const start = toDate(range.min), end = toDate(range.max);
      const months = [];
      let cur = new Date(start.getFullYear(), start.getMonth(), 1);
      while (cur <= end) {
        const next = new Date(cur.getFullYear(), cur.getMonth() + 1, 1);
        const y = cur.getFullYear(), m = String(cur.getMonth() + 1).padStart(2, '0');
        const ny = next.getFullYear(), nm = String(next.getMonth() + 1).padStart(2, '0');
        months.push({ label: `${y}-${m}`, start: parseInt(`${y}${m}01`, 10), end: parseInt(`${ny}${nm}01`, 10) });
        cur = next;
      }
      const results = [];
      for (const mo of months) {
        // ⚠️ 2026-09: count:'estimated'는 실제로 세지 않고 Postgres 플래너 통계로 "추정"만
        // 하는 값이라, 서로 다른 달인데 똑같은 숫자가 나오는 등 신뢰할 수 없었음(진단용
        // 도구인데 정확도가 없으면 의미 없음) - count:'exact'로 실제 카운트하도록 수정.
        const { count: totalCount, error: e1 } = await supabase.from(table).select('*', { count: 'exact', head: true })
          .gte('deal_date', mo.start).lt('deal_date', mo.end);
        const { count: nonMetroCount, error: e2 } = await supabase.from(table).select('*', { count: 'exact', head: true })
          .gte('deal_date', mo.start).lt('deal_date', mo.end)
          .not('region', 'ilike', '서울%').not('region', 'ilike', '경기%').not('region', 'ilike', '인천%');
        results.push({
          month: mo.label, totalCount: totalCount || 0, nonMetroCount: nonMetroCount || 0,
          error: (e1 && e1.message) || (e2 && e2.message) || null,
        });
      }
      return res.status(200).json({ table, min: range.min, max: range.max, months: results });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  // ⚠️ 2026-09(카카오 coord2RegionCode 일일 쿼터(10만건/일) 소진 사례 - "API limit has been
  // exceeded" code -10): 좌표→법정동코드 변환 결과를 격자(소수점4자리, 위경도 약 11m) 단위로
  // Supabase에 영구 캐시함. 대한민국 행정구역 경계는 거의 안 바뀌므로 TTL 없이 계속 재사용 -
  // 한 번 조회된 좌표는 전국 어떤 사용자가 다시 봐도 카카오를 다시 안 부름. 이미 있는
  // create-region-code-cache.sql로 테이블을 먼저 만들어야 함. index.html의
  // coord2RegionCodeCached()가 이 두 모드를 씀(캐시 미스 시에만 실제 카카오 API를 부르고,
  // 그 결과를 regionCodeSet으로 여기에 저장해둠).
  if (req.query.mode === 'regionCodeGet') {
    res.setHeader('Cache-Control', 'no-store');
    try {
      const lat = parseFloat(req.query.lat);
      const lon = parseFloat(req.query.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        return res.status(400).json({ error: 'lat/lon이 필요합니다.' });
      }
      const gridLat = Math.round(lat * 10000) / 10000;
      const gridLon = Math.round(lon * 10000) / 10000;
      const { data, error } = await supabase
        .from('region_code_cache')
        .select('b_code,region1,region2,region3')
        .eq('grid_lat', gridLat)
        .eq('grid_lon', gridLon)
        .maybeSingle();
      if (error) {
        console.warn('regionCodeGet 조회 실패:', error.message);
        return res.status(200).json({ found: false });
      }
      if (!data) return res.status(200).json({ found: false });
      return res.status(200).json({
        found: true,
        result: [{
          region_type: 'B',
          region_1depth_name: data.region1 || '',
          region_2depth_name: data.region2 || '',
          region_3depth_name: data.region3 || '',
          code: data.b_code,
        }],
      });
    } catch (err) {
      console.warn('regionCodeGet 예외:', err.message);
      return res.status(200).json({ found: false });
    }
  }
  if (req.query.mode === 'regionCodeSet') {
    res.setHeader('Cache-Control', 'no-store');
    if (req.method !== 'POST') return res.status(405).json({ error: 'POST로 {lat,lon,result} 를 보내주세요.' });
    try {
      const { lat, lon, result } = req.body || {};
      const latNum = parseFloat(lat);
      const lonNum = parseFloat(lon);
      if (!Number.isFinite(latNum) || !Number.isFinite(lonNum) || !Array.isArray(result)) {
        return res.status(400).json({ error: 'lat/lon/result가 필요합니다.' });
      }
      const bEntry = result.find((r) => r && r.region_type === 'B');
      if (!bEntry || !bEntry.code) return res.status(200).json({ ok: false }); // 저장할 법정동 정보가 없으면 조용히 무시
      const gridLat = Math.round(latNum * 10000) / 10000;
      const gridLon = Math.round(lonNum * 10000) / 10000;
      const { error } = await supabase.from('region_code_cache').upsert({
        grid_lat: gridLat,
        grid_lon: gridLon,
        b_code: bEntry.code,
        region1: bEntry.region_1depth_name || null,
        region2: bEntry.region_2depth_name || null,
        region3: bEntry.region_3depth_name || null,
      }, { onConflict: 'grid_lat,grid_lon' });
      if (error) console.warn('regionCodeSet 저장 실패:', error.message);
      return res.status(200).json({ ok: !error });
    } catch (err) {
      console.warn('regionCodeSet 예외:', err.message);
      return res.status(200).json({ ok: false });
    }
  }
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
      // ⚠️ 2026-08(재조정): 50도 부족한 걸로 실측 확인됨 - "전국" 연립다세대 스코프는 서울
      // (전체 규제지역) 거래량이 워낙 커서 상위 50개 중 41개가 서울이고 비규제지역은 9개뿐이었음
      // (신고가지역 RANK_LIMIT과 같은 문제, 같은 조치로 200까지 상향).
      const RANK_LIMIT = 200;
      if (typeParam === 'both' || typeParam === 'apt') result.apt = await getTopDongs('apt', cutoff, sido, RANK_LIMIT);
      if (typeParam === 'both' || typeParam === 'villa') result.villa = await getTopDongs('villa', cutoff, sido, RANK_LIMIT);
      return res.status(200).json({ sidoList: SIDO_LIST, months, sido: sido || null, cutoff, ...result });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'newHighDongs') {
    // 2026-08(사용자 요청: "신고가 갱신이 많은 지역 순위를 조금 더 빠르게 진입하기 위한
    // 신호로 보고 싶다" → 이후 "돈되는 지역처럼 흐름이 필요하다") - v2: months 파라미터
    // 대신 돈되는지역과 동일한 6구간(momentumBuckets, 아파트 40일×6/빌라 60일×6)으로 신고가
    // 건수 흐름을 보여줌. danji 단위 집계라 무거울 수 있어 캐시를 30분으로 둠(topDongs와 동일).
    try {
      const sido = (req.query.sido || '').trim();
      const typeParam = req.query.type === 'apt' || req.query.type === 'villa' ? req.query.type : 'both';
      const result = {};
      // 2026-08(사용자 리포트: "전국 조회시 연립다세대 순위가 9개에서 끊긴다") - topDongs와
      // 똑같은 원인이었음: 규제지역/비규제지역 필터링은 프론트에서 이 응답을 받은 뒤에
      // 클라이언트 단에서 적용되는데(filterByRegArea), 그전에 이미 서버가 상위 50개로
      // 잘라서 보냄. "전국" 스코프는 서울(전체 규제지역)의 거래량이 워낙 커서 상위 50개
      // 중 대부분이 서울 소속 동으로 채워지고, 정작 비규제지역만 걸러내면 9개 정도만
      // 남는 문제가 실측으로 확인됨(예: 연립다세대 전국 상위 50개 중 비규제지역 9개뿐).
      // getNewHighDongsTrend는 어차피 6구간을 병합한 뒤 마지막에만 .slice(limit)하므로
      // (구간별 조회 자체는 이미 넉넉한 p_limit=2000으로 전부 받아둠) limit을 50→200으로
      // 올려도 추가 연산 부하는 없고 응답 페이로드만 조금 커짐 - topDongs(#418)와 동일한
      // 조치.
      const RANK_LIMIT = 200;
      let allOk = true;
      if (typeParam === 'both' || typeParam === 'apt') {
        const r = await getNewHighDongsTrend('apt', sido, RANK_LIMIT);
        result.apt = r.list; allOk = allOk && r.ok;
      }
      if (typeParam === 'both' || typeParam === 'villa') {
        const r = await getNewHighDongsTrend('villa', sido, RANK_LIMIT);
        result.villa = r.list; allOk = allOk && r.ok;
      }
      // ⚠️ 2026-08: 6구간 중 일부가 (타임아웃 등으로) 끝내 실패했으면 "0→0→17→0→0→0"처럼
      // 깨진 흐름이 그대로 반환된 것 - 이걸 30분+stale-while-revalidate 60분 캐시에 박아두면
      // 최대 90분간 사용자 전원이 깨진 데이터를 보게 됨(실제 발생 확인됨). 실패가 섞였을
      // 때는 캐시하지 않고(no-store) 다음 요청이 새로 재계산하도록 함 - 성공했을 때만
      // 기존처럼 30분 캐시.
      res.setHeader('Cache-Control', allOk ? 's-maxage=1800, stale-while-revalidate=3600' : 'no-store');
      return res.status(200).json({ sidoList: SIDO_LIST, sido: sido || null, ...result });
    } catch (err) {
      res.setHeader('Cache-Control', 'no-store');
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
  if (req.query.mode === 'unsoldHousing') {
    // 미분양 통계는 월 1회만 갱신되므로 population/roneIndex와 같은 캐시 정책을 씀.
    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=43200');
    try {
      if (!KOSIS_API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 환경변수가 없습니다.' });
      const sido = req.query.sido;
      const sigungu = req.query.sigungu;
      if (!sido) return res.status(400).json({ error: 'sido(시/도명, 예: 인천광역시 또는 인천)가 필요합니다.' });
      const resolved = resolveUnsoldCode(String(sido), sigungu ? String(sigungu) : null);
      if (!resolved || !resolved.c2) {
        return res.status(400).json({ error: `"${sido}" 지역의 미분양 통계 코드를 찾지 못했습니다.` });
      }
      const result = await getUnsoldTrend(resolved.c1, resolved.c2, req.query.force === '1');
      return res.status(200).json({ ...result, matchedLevel: resolved.matchedLevel, matchedName: resolved.matchedName });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'unsoldComplex') {
    // 전국 목록을 하루 1회만 갱신하면 되는 데이터라 CDN 캐시도 길게 둠.
    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=43200');
    try {
      if (!KOSIS_API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 환경변수가 없습니다.' });
      const result = await getUnsoldComplexList(req.query.force === '1');
      if (result.error) return res.status(502).json(result);
      const sido = req.query.sido ? String(req.query.sido).trim() : null;
      const items = sido ? result.items.filter(it => it.sido === sido) : result.items;
      return res.status(200).json({ items, cached: result.cached });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'regionList') {
    // 후발주자 예측(mode=leaderFollower) 프론트의 시/군/구 선택 드롭다운용 - 신규 데이터
    // 없이 미분양(mode=unsoldHousing)용으로 이미 만들어둔 UNSOLD_CODE_ROWS(시도+시군구
    // 246행)를 재사용함. "계"(시/도 전체 합계 placeholder row)와 서울은 이 기능이
    // "서울 제외 지방"만 다루므로 제외함.
    const bySido = {};
    UNSOLD_CODE_ROWS.forEach(([sidoNm, , guNm]) => {
      if (sidoNm === '서울' || guNm === '계') return;
      if (!bySido[sidoNm]) bySido[sidoNm] = [];
      bySido[sidoNm].push(guNm);
    });
    return res.status(200).json({ bySido });
  }
  if (req.query.mode === 'leaderFollower') {
    res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=43200');
    try {
      const region = req.query.region ? String(req.query.region).trim() : '';
      const type = req.query.type === 'villa' ? 'villa' : 'apt';
      if (!region) return res.status(400).json({ error: 'region(예: "경북 구미시")이 필요합니다.' });
      if (region.startsWith('서울')) return res.status(400).json({ error: '이 기능은 서울을 제외한 지역만 지원합니다(사용자 요청 - 서울은 이미 급등지역·돈되는지역 등 다른 지표로 충분히 다뤄지고 있고, 이 기능은 지방 갭메우기 신호에 초점을 둠).' });
      const result = await getLeaderFollowerRank(type, region, req.query.force === '1');
      if (result.error) return res.status(502).json(result);
      return res.status(200).json(result);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'applyhomeRaw') {
    // 진단 전용(위 fetchApplyhomeRaw 주석 참고) - 청약홈 무순위·잔여세대 API의 활용신청
    // 승인 여부/실제 응답 필드를 확인할 때만 씀.
    res.setHeader('Cache-Control', 'no-store');
    try {
      if (!KOSIS_API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 환경변수가 없습니다.' });
      const { src, page, perPage, condField, condOp, condValue } = req.query;
      const cond = condField ? { field: String(condField), op: condOp ? String(condOp) : 'EQ', value: condValue } : null;
      const result = await fetchApplyhomeRaw(src ? String(src) : 'remnant', page, perPage, cond);
      return res.status(200).json(result);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'kosisRaw') {
    // 진단 전용(위 fetchKosisRaw 주석 참고) - 새 KOSIS 표의 itmId 체계를 확인할 때만 씀.
    res.setHeader('Cache-Control', 'no-store');
    try {
      if (!KOSIS_API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 환경변수가 없습니다.' });
      const { tblId, orgId, objL1, itmId, prdSe, newEstPrdCnt, ...extra } = req.query;
      delete extra.mode;
      if (!tblId || !orgId || !objL1) {
        return res.status(400).json({ error: 'tblId, orgId, objL1(시군구/시도 코드)이 필요합니다.' });
      }
      const result = await fetchKosisRaw(String(tblId), String(orgId), String(objL1), itmId, prdSe, newEstPrdCnt, extra);
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
