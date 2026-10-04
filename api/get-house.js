import { createClient } from '@supabase/supabase-js';
import { LAWD_CODES } from '../scripts/lawd-codes.mjs';
import { gzipSync, gunzipSync } from 'zlib';
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
const APT_API_KEY = process.env.PUBLIC_DATA_API_KEY;

// ════════════════════════════════════
// 지역(lawdCd) 단위 응답 캐시 (Upstash Redis)
// - 캐시에는 "국토부 DB 배치 수집분(house_trades/villa_trades/전세)"만 저장합니다.
//   이번달 실시간 신고건(국토부 실시간 API)은 캐시에 절대 포함하지 않고,
//   실제 사용자가 화면을 조회할 때마다 매번 새로 불러와서 캐시된 DB분과 합쳐서 응답합니다.
//   → 새벽 웜업이 이 캐시를 미리 채워둬도, 실제 방문 시엔 항상 최신 실시간 신고건이 반영됩니다.
// - ?skipRealtime=1 로 호출하면(새벽 웜업 전용) 실시간 API 호출 자체를 생략하고
//   DB분만 조회해서 캐시에 채워 넣습니다. 실시간 API가 건축HUB 웜업과 같은 일일 할당량을
//   쓰는 키라서, 웜업 때는 이 할당량을 쓰지 않기 위함입니다.
// ════════════════════════════════════
const REDIS_URL = process.env.UPSTASH_REDIS_URL;
const REDIS_TOKEN = process.env.UPSTASH_REDIS_TOKEN;
// ⚠️ 2026-10(사고 후 되돌림): 같은 날 로딩속도 개선으로 8일 보관 + 매주 전 지역(257곳) 미리 채우기를 했더니
// Upstash 저장소(경매물건·낙찰사례·임장메모와 같은 DB)가 플랜 용량 한도를 넘어 모든 읽기/쓰기가 막혔음
// ("reached current Fixed plan limits"). 지역 캐시는 다시 10시간 보관으로 되돌리고, 큰 지역(압축 후
// HOUSE_CACHE_MAX_BYTES 초과)은 Redis에 저장하지 않음 - 대신 브라우저 보관(IndexedDB 6시간)이 재방문을 빠르게 함.
const CACHE_TTL_SECONDS = 10 * 60 * 60;
const HOUSE_CACHE_MAX_BYTES = 600 * 1024;
// ⚠️ 2026-10(사고 원인 확정 - Upstash 콘솔): 용량이 아니라 "월 데이터 전송량(Bandwidth) 10GB" 초과로
// 정지됐음(12GB). 지역 캐시는 조회할 때마다 수 MB씩 이 저장소에서 꺼내 와서 전송량을 거의 다 차지함 -
// 경매물건·낙찰사례·임장메모가 같은 저장소라 함께 막힘. 지역 캐시는 Redis에 더 이상 두지 않음
// (브라우저 IndexedDB 6시간 보관 + Vercel 엣지 캐시로 대신함). clearCache는 남은 키 정리용으로 유지.
const HOUSE_REDIS_CACHE_ENABLED = false;
// ⚠️ 2026-10(사용자 요청: "배지 로딩속도를 확연하게 높여줘") - 실측: 가평(0.5MB)·성남(4.6MB)은
// 캐시가 돼서 0.15~0.6초인데, 부천(11MB)·강남(9MB)처럼 큰 지역은 원본 JSON 그대로는 Redis 저장/
// 조회(요청 크기 상한·3초 제한)에 걸려 매번 캐시를 못 쓰고 DB를 다시 긁느라 3~7초(바쁠 땐 18초)가
// 걸렸음. gzip으로 압축해서(약 1/10) 저장하면 큰 지역도 캐시가 됨. 'gz:' 접두어로 구분하고,
// 접두어 없는 예전 캐시(평문 JSON)도 그대로 읽음.
const GZ_PREFIX = 'gz:';

async function getCachedHouseData(lawdCd) {
  if (!HOUSE_REDIS_CACHE_ENABLED || !REDIS_URL || !REDIS_TOKEN) return null;
  try {
    const r = await fetch(`${REDIS_URL}/get/house_${lawdCd}`, {
      headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return null;
    const data = await r.json();
    if (!data || !data.result) return null;
    const raw = String(data.result);
    const parsed = raw.startsWith(GZ_PREFIX)
      ? JSON.parse(gunzipSync(Buffer.from(raw.slice(GZ_PREFIX.length), 'base64')).toString('utf8'))
      : JSON.parse(raw);
    // apt만 검사하면, 전세(rent) 조회 기능이 추가되기 전에 저장된 구식 캐시({apt:[...]}만 있고
    // rent 필드 자체가 없는 상태)가 "유효한 캐시"로 통과되어 계속 빈 전세 데이터를 반환하는
    // 버그가 있었습니다. rent도 배열인지 함께 검사해서 구식 캐시는 자동으로 무효 처리되게 함.
    if (!parsed || !Array.isArray(parsed.apt) || !Array.isArray(parsed.rent)) return null;
    return parsed;
  } catch (e) {
    console.error('get-house Redis 캐시 조회 실패:', e.message);
    return null;
  }
}

async function setCachedHouseData(lawdCd, payload) {
  if (!HOUSE_REDIS_CACHE_ENABLED || !REDIS_URL || !REDIS_TOKEN) return;
  try {
    const packed = GZ_PREFIX + gzipSync(Buffer.from(JSON.stringify(payload), 'utf8')).toString('base64');
    if (packed.length > HOUSE_CACHE_MAX_BYTES) return; // 저장소 용량 보호(위 주석)
    const r = await fetch(`${REDIS_URL}/set/house_${lawdCd}?EX=${CACHE_TTL_SECONDS}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'text/plain' },
      body: packed,
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) {
      const errText = await r.text();
      console.error('get-house Redis 캐시 저장 실패:', errText);
    }
  } catch (e) {
    console.error('get-house Redis 캐시 저장 실패:', e.message);
  }
}

// ── 캐시 전체 비우기 (CSV 대량 업로드 후 backup.html의 "지도 캐시 전체 삭제" 버튼용) ──
// Upstash REST는 GET/SET처럼 자주 쓰는 명령은 /get/{key}, /set/{key} 같은 단축 경로를 제공하지만,
// KEYS처럼 흔치 않은 명령은 기본 URL에 명령 배열을 그대로 POST하는 범용 방식으로 호출해야 함.
async function redisCommand(cmdArray) {
  const r = await fetch(REDIS_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(cmdArray),
    signal: AbortSignal.timeout(8000),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || 'Redis 명령 실패');
  return data.result;
}
async function clearHouseCache() {
  if (!REDIS_URL || !REDIS_TOKEN) throw new Error('UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN 환경변수가 없습니다.');
  const keys = await redisCommand(['KEYS', 'house_*']);
  if (!Array.isArray(keys) || !keys.length) return { cleared: 0 };
  // 여러 키를 한 번에 지우기 - pipeline 엔드포인트로 DEL 명령을 묶어서 보냄
  const pipelineBody = keys.map((k) => ['DEL', k]);
  const r = await fetch(`${REDIS_URL}/pipeline`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(pipelineBody),
    signal: AbortSignal.timeout(8000),
  });
  if (!r.ok) {
    const errText = await r.text();
    throw new Error('캐시 삭제 실패: ' + errText);
  }
  return { cleared: keys.length };
}

// ════════════════════════════════════
// 2026-08: house_trades/villa_trades/house_rent/villa_rent 조회에 .limit()/.range()가
// 전혀 없어서 Supabase/PostgREST 기본 응답 상한(설정된 db-max-rows)에 걸려 조용히 잘려나가는
// 버그가 있었습니다. deal_date 내림차순 정렬 상태에서 잘리기 때문에 "가장 최근 N건"만 남고
// 오래된 거래이력은 통째로 사라지는 형태 - 거래량이 많은 지역(예: 남양주 다산동)일수록
// 심각해서, 실측으로는 2025-12부터 쌓인 이력 중 최근 7주치만 남고 나머지가 다 사라진 사례를
// 확인했습니다. 그 결과 calcNewHigh()가 "최근 6개월" vs "그 이전" 비교를 할 "이전" 데이터
// 자체를 못 받아서, 신고가(★) 배지가 지역 순위(다산동 아파트 신고가 1위, 126건)와 전혀
// 맞지 않게 거의 뜨지 않는 문제로 이어졌습니다. (신고가 지역 순위 자체는 SQL RPC가 DB를
// 직접 긁는 별도 경로라 이 버그의 영향을 받지 않았음 - 그래서 순위와 배지가 어긋나 보였음.)
// id(PK, BIGINT GENERATED ALWAYS AS IDENTITY - house_rent와 동일한 패턴)를 오름차순 정렬
// 기준으로 삼아 range()로 끝까지 안전하게 페이지네이션합니다.
// ⚠️ 2026-08 추가: 처음엔 while 루프로 페이지를 하나씩 순차 요청했는데, 거래량이 많은
// 지역(예: 남양주시 전체 - house_trades만 7000건대)은 페이지가 7~9개씩 나와서 매번
// Supabase 왕복시간이 그대로 누적되어 캐시가 없을 때(Redis 미스) 응답이 10초 넘게
// 걸리는 게 실측 확인됐습니다. 먼저 count만 가벼운 head 요청으로 받아서 전체 페이지
// 수를 계산한 뒤, 모든 페이지를 Promise.all로 동시에 요청하도록 바꿔서 왕복시간을
// "페이지 수 x 1회"가 아니라 "약 1회"로 줄였습니다. (단순 region 인덱스 조회라
// 페이지 몇 개 더 병렬로 나가는 정도는 앞서 겪은 rpc_new_high_dongs류의 무거운
// 윈도우함수 SQL 병렬호출 문제와는 성격이 달라 안전함.)
const FETCH_PAGE_SIZE = 1000;
// ⚠️ 2026-09: 과거자료(2017-09~) 백필로 house_trades 등이 9년치로 불어나면서, 시군구 전체를
// 기간제한 없이 통째로 내려주던 이 엔드포인트가 지역에 따라 응답 6~13초·페이로드 최대
// 20MB대까지 커졌고, 남양주시 같은 곳은 간헐적으로 500(타임아웃/메모리 추정)까지 실제로
// 발생함(실측 확인). 지도 배지·비교물건 등 이 엔드포인트를 쓰는 기능들은 전부 "최근 시세"가
// 목적이라 그 이전 역사까지는 필요 없고(장기추세형 기능인 leaderFollower/돈되는지역/R-ONE/
// AVM 학습은 전부 이 엔드포인트를 거치지 않고 data-coverage.js·train-avm.py에서 Supabase를
// 직접 SQL로 조회하므로 이 변경과 무관함) - 사용자 요청대로 클라이언트 로딩은 최근 2년으로
// 제한하고, 그 이전 데이터는 DB에 그대로 남겨 "백데이터"로만 계속 활용함(삭제 아님).
const RECENT_WINDOW_YEARS = 2;
// ⚠️ 2026-09(#498, 예상매도가 실측 백테스트): 연립다세대는 아파트보다 거래가 훨씬 드물어서, 수도권
// 빌라 낙찰사례의 절반가량이 "비교물건 없음"으로 예상매도가를 못 냈음. 비교물건 검색
// (index.html findSimilarComps)은 1년→2년→10년 순으로 기간을 넓혀가며 찾는데, 클라이언트가 2년치만
// 받으면 그 폴백이 2년에서 막힘 - 빌라만 3년으로 늘림(빌라 거래량은 아파트의 수분의 1이라 응답
// 크기 부담이 작음).
const RECENT_WINDOW_YEARS_VILLA = 3;
function recentCutoffDateStr(years) {
  const d = new Date();
  d.setFullYear(d.getFullYear() - (years || RECENT_WINDOW_YEARS));
  return String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
}
async function fetchAllRows(table, regionName, yearsOverride) {
  const cutoff = recentCutoffDateStr(yearsOverride || (table === 'villa_trades' ? RECENT_WINDOW_YEARS_VILLA : RECENT_WINDOW_YEARS));
  const { count, error: countError } = await supabase
    .from(table)
    .select('id', { count: 'exact', head: true })
    .eq('region', regionName)
    .gte('deal_date', cutoff);
  if (countError) return { data: null, error: countError };
  if (!count) return { data: [], error: null };

  const pageCount = Math.ceil(count / FETCH_PAGE_SIZE);
  const pagePromises = [];
  for (let i = 0; i < pageCount; i++) {
    const from = i * FETCH_PAGE_SIZE;
    pagePromises.push(
      supabase
        .from(table)
        .select('*')
        .eq('region', regionName)
        .gte('deal_date', cutoff)
        .order('id', { ascending: true })
        .range(from, from + FETCH_PAGE_SIZE - 1)
    );
  }
  const results = await Promise.all(pagePromises);
  for (const r of results) {
    if (r.error) return { data: null, error: r.error };
  }
  const all = results.flatMap(r => r.data || []);
  return { data: all, error: null };
}

// ════════════════════════════════════
// 2026-09: GitHub Actions(주간 수집 스크립트)가 국토부 API(apis.data.go.kr)로
// 직접 fetch할 때 전 지역(~250개 LAWD 코드) 100%에서 UND_ERR_CONNECT_TIMEOUT
// (TCP 연결 자체가 안 됨)이 재현됨 - 6월 이후 house_trades/house_rent/villa_trades/
// single_trades 수집이 전면 중단됐던 원인. 동일 API를 이 파일의 fetchRealtimeApt()가
// Vercel 네트워크에서는 지금도 정상 호출 중이라, GitHub Actions 전용 IP 대역이
// 국토부(혹은 중간 방화벽)에서 막힌 것으로 추정 - 코드/재시도로 해결 불가능한
// 네트워크 문제라 GitHub Actions는 국토부 API를 직접 부르지 않고 이 프록시를
// 경유해서 데이터를 받아가도록 우회함. 인증 없이 열어두면 공용 서비스키의 일일
// 호출 한도를 외부에서 소진시킬 수 있어 공유 비밀값(COLLECT_PROXY_SECRET)으로
// 우리 GitHub Actions 요청만 허용함 - Vercel 환경변수 + GitHub 저장소 시크릿 양쪽에
// 동일한 값을 등록해야 함.
// ════════════════════════════════════
const PROXY_SECRET = process.env.COLLECT_PROXY_SECRET;
const PROXY_ENDPOINTS = {
  aptTrade: 'RTMSDataSvcAptTradeDev', // 아파트 매매 (house_trades)
  aptRent:  'RTMSDataSvcAptRent',     // 아파트 전월세 (house_rent)
  rhTrade:  'RTMSDataSvcRHTrade',     // 연립다세대 매매 (villa_trades)
  shTrade:  'RTMSDataSvcSHTrade',     // 단독/다가구 매매 (single_trades)
  presale:  'RTMSDataSvcSilvTrade',   // 아파트 분양권·입주권 전매 (2026-10, leader_follower_cache 'presale|<시군구>')
};

async function handleMolitProxy(req, res) {
  if (!PROXY_SECRET || req.query.secret !== PROXY_SECRET) {
    return res.status(401).json({ error: 'unauthorized' });
  }
  const endpoint = PROXY_ENDPOINTS[req.query.endpoint];
  if (!endpoint) {
    return res.status(400).json({ error: 'invalid endpoint (use aptTrade/aptRent/rhTrade/shTrade/presale)' });
  }
  const code = req.query.code;
  const ym   = req.query.ym;
  if (!code || !ym) return res.status(400).json({ error: 'code, ym required' });
  if (!APT_API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY not configured' });

  try {
    const url = `https://apis.data.go.kr/1613000/${endpoint}/get${endpoint}`
      + `?serviceKey=${encodeURIComponent(APT_API_KEY)}&LAWD_CD=${code}&DEAL_YMD=${ym}&numOfRows=1000&pageNo=1`;
    const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await response.text();
    res.setHeader('Content-Type', 'text/xml; charset=utf-8');
    return res.status(200).send(text);
  } catch (e) {
    const causeInfo = e.cause ? (e.cause.code || e.cause.message || String(e.cause)) : null;
    console.error('molitProxy 실패:', req.query.endpoint, code, ym, e.message, causeInfo);
    return res.status(502).json({ error: e.message, cause: causeInfo });
  }
}

async function handleComplexHistory(req, res) {
  const region = String(req.query.region || '').trim();
  const dong = String(req.query.dong || '').trim();
  const bunji = String(req.query.bunji || '').trim();
  const table = req.query.type === 'villa' ? 'villa_trades' : 'house_trades';
  const years = Math.min(10, Math.max(1, parseInt(req.query.years, 10) || 10));
  if (!region || !dong || !bunji) return res.status(400).json({ error: 'region, dong, bunji required' });
  // 2026-07 광주·전남 통합 이전 자료는 '광주 ○구'·'전남 ○○군'으로 저장돼 있어 옛 이름도 함께 찾음
  const parts = region.split(' ');
  const names = [region];
  if (parts[0] === '전남광주' && parts[1]) names.push('광주 ' + parts.slice(1).join(' '), '전남 ' + parts.slice(1).join(' '));
  try {
    const rows = [];
    for (let from = 0; from < 5000; from += FETCH_PAGE_SIZE) {
      const { data, error } = await supabase.from(table)
        .select('deal_date,price,size,floor,danji,dealing_type')
        .in('region', names).eq('dong', dong).eq('bunji', bunji)
        .gte('deal_date', recentCutoffDateStr(years))
        .order('deal_date', { ascending: false })
        .range(from, from + FETCH_PAGE_SIZE - 1);
      if (error) return res.status(500).json({ error: error.message });
      rows.push(...(data || []));
      if (!data || data.length < FETCH_PAGE_SIZE) break;
    }
    res.setHeader('Cache-Control', 'public, s-maxage=86400');
    return res.status(200).json({ trades: rows.map(r => [String(r.deal_date), r.price, r.size, r.floor, r.danji, r.dealing_type || null]) });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');

  // GitHub Actions 주간 수집 스크립트 전용 - 국토부 API를 대신 호출해서 XML을 그대로 돌려줌
  // (위 handleMolitProxy 설명 참고). lawdCd 파라미터 흐름과 무관하니 가장 먼저 분기.
  if (req.query.action === 'molitProxy') {
    return handleMolitProxy(req, res);
  }

  // CSV 대량 업로드 후 backup.html에서 이 액션으로 지역별 캐시를 통째로 비움
  // (평소 지도 조회 흐름과 무관한 관리용 액션이라 lawdCd 없이도 처리)
  if (req.query.action === 'clearCache') {
    try {
      const result = await clearHouseCache();
      return res.status(200).json(result);
    } catch (e) {
      return res.status(500).json({ error: e.message });
    }
  }

  // 2026-10(사용자 요청: 시세 그래프 1년·3년·10년) - 지도용 응답은 최근 2년치만 내려주므로(위 RECENT_WINDOW_YEARS),
  // 그래프의 10년 보기는 단지 하나의 매매만 따로 10년치 조회. 단지 하나라 수백 건 수준.
  if (req.query.action === 'history') {
    return handleComplexHistory(req, res);
  }

  const lawdCd = req.query.lawdCd;
  if (!lawdCd) return res.status(400).json({ error: 'lawdCd required' });

  // 새벽 자동 예열 요청만 이 플래그를 붙여서 호출합니다 (실시간 API 할당량 절약용)
  const skipRealtime = req.query.skipRealtime === '1' || req.query.skipRealtime === 'true';

  // house_trades / villa_trades 모두 lawd_cd 컬럼이 없고 region 텍스트로 저장되어 있어
  // LAWD_CODES로 lawdCd → 지역명 변환이 필요합니다.
  const regionInfo = LAWD_CODES.find(r => r.code === lawdCd);
  const regionName = regionInfo ? regionInfo.name : '';

  console.log('lawdCd:', lawdCd, '/ regionName:', regionName || '(매칭 실패)', '/ skipRealtime:', skipRealtime);

  // 2026-10: 백테스트 전용 - ?years=3~6이면 매매(아파트·빌라)만 그 기간만큼 길게(캐시 안 씀, 전세 생략).
  // 과거 낙찰사례를 "그 당시 시점"으로 다시 판정하려면 입찰 전 1~2년 거래가 필요해서.
  const longYears = Math.min(6, parseInt(req.query.years, 10) || 0);
  if (longYears > 2 && regionName) {
    try {
      const [ar, vr, rr] = await Promise.all([fetchAllRows('house_trades', regionName, longYears), fetchAllRows('villa_trades', regionName, longYears),
        req.query.rent === '1' ? fetchAllRows('house_rent', regionName, Math.min(longYears, 4)) : Promise.resolve({ data: [] })]);
      if (ar.error || vr.error) return res.status(500).json({ error: (ar.error || vr.error).message });
      const apt = dedup([...(ar.data || []).map(r => normalizeRow(r, 'apt')), ...(vr.data || []).map(r => normalizeRow(r, 'villa'))]);
      const rent = (rr && rr.data || []).map(r => normalizeRentRow(r, 'apt'));
      return res.status(200).json({ apt, rent, years: longYears });
    } catch (e) { return res.status(500).json({ error: e.message }); }
  }

  try {
    // ── 1. DB 배치 수집분(apt/villa/전세)은 캐시가 있으면 그대로 재사용 ──
    let dbPayload = null;
    // 실시간(이번달 신규 신고건) 조회는 캐시/DB 조회와 무관하므로 미리 출발시켜 둠(직렬 대기 ~1초 제거)
    const now    = new Date();
    const thisYm = String(now.getFullYear()) + String(now.getMonth() + 1).padStart(2, '0');
    const realtimePromise = skipRealtime ? Promise.resolve([]) : fetchRealtimeApt(lawdCd, thisYm);
    if (!skipRealtime) {
      dbPayload = await getCachedHouseData(lawdCd);
      if (dbPayload) console.log('get-house DB캐시 히트:', lawdCd);
    }

    if (!dbPayload) {
      // ── 아파트 DB / 연립다세대 DB / 전세 DB, 세 요청을 동시에 실행 ──
      let aptQuery       = Promise.resolve({ data: [], error: null });
      let villaQuery     = Promise.resolve({ data: [], error: null });
      let aptRentQuery   = Promise.resolve({ data: [], error: null });
      let villaRentQuery = Promise.resolve({ data: [], error: null });

      if (regionName) {
        aptQuery = fetchAllRows('house_trades', regionName);
        villaQuery = fetchAllRows('villa_trades', regionName);
        // 단독/다가구(single_trades)는 지도에 표시하지 않기로 했으므로 조회하지 않음

        // 전세가(house_rent/villa_rent) - 전세가 기반 시세추정(연립다세대) 등에 사용
        aptRentQuery = fetchAllRows('house_rent', regionName);
        villaRentQuery = fetchAllRows('villa_rent', regionName);
      } else {
        console.warn('LAWD_CODES에서 lawdCd(' + lawdCd + ')에 매칭되는 지역명을 찾지 못해 DB 조회를 건너뜁니다.');
      }

      const [aptResult, villaResult, aptRentResult, villaRentResult] = await Promise.all([
        aptQuery,
        villaQuery,
        aptRentQuery,
        villaRentQuery,
      ]);

      if (aptResult.error) {
        console.error('house_trades 조회 에러:', aptResult.error.message);
        throw aptResult.error;
      }
      const aptData = aptResult.data || [];
      console.log('아파트 조회 완료. 건수:', aptData.length);

      let villaData = [];
      if (villaResult.error) {
        console.error('villa_trades 조회 에러:', villaResult.error.message);
      } else {
        villaData = villaResult.data || [];
        console.log('연립다세대 조회 완료. 건수:', villaData.length);
      }

      let aptRentData = [];
      if (aptRentResult.error) {
        console.error('house_rent 조회 에러:', aptRentResult.error.message);
      } else {
        aptRentData = aptRentResult.data || [];
      }

      let villaRentData = [];
      if (villaRentResult.error) {
        console.error('villa_rent 조회 에러:', villaRentResult.error.message);
      } else {
        villaRentData = villaRentResult.data || [];
      }
      console.log('전세가 조회 완료. 아파트=' + aptRentData.length + '건 연립다세대=' + villaRentData.length + '건');

      // ── 정규화 ──
      const aptNormalized      = aptData.map(row => normalizeRow(row, 'apt'));
      const villaNormalized    = villaData.map(row => normalizeRow(row, 'villa'));
      const aptRentNormalized   = aptRentData.map(row => normalizeRentRow(row, 'apt'));
      const villaRentNormalized = villaRentData.map(row => normalizeRentRow(row, 'villa'));

      // ── 합치기 + 중복 제거 (DB 배치 수집분만, 실시간은 여기 포함하지 않음) ──
      const merged = dedup([...aptNormalized, ...villaNormalized]);
      const rentMerged = [...aptRentNormalized, ...villaRentNormalized];
      console.log(
        `DB분 최종: 아파트=${aptNormalized.length}건 연립다세대=${villaNormalized.length}건 ` +
        `합계=${merged.length}건 / 전세=${rentMerged.length}건`
      );

      dbPayload = { apt: merged, rent: rentMerged };
      // 다음 조회(다른 기기 포함)를 위해 DB분만 캐시에 저장 (실시간은 절대 캐시하지 않음)
      await setCachedHouseData(lawdCd, dbPayload);
    }

    // 새벽 웜업 요청은 캐시만 채우면 끝 - 실시간 API는 호출하지 않고 바로 응답
    if (skipRealtime) {
      return res.status(200).json(dbPayload);
    }

    // ── 실시간(이번달 신규 신고건)은 캐시 여부와 무관하게 방문할 때마다 항상 새로 불러와서 합침 ──
    const realtimeItems = await realtimePromise;
    const realtimeNormalized = realtimeItems.map(item => normalizeXMLItem(item, regionName));
    const finalApt = dedup([...realtimeNormalized, ...dbPayload.apt]);
    console.log(`실시간 반영: +${realtimeNormalized.length}건 (최종 ${finalApt.length}건)`);

    // 무료 Vercel 사용량 절약: 같은 지역(lawdCd)을 5분 안에 다시 조회하면(지도 패닝/재방문
    // 등) 함수를 다시 실행하지 않고 Vercel 엣지 캐시에서 바로 응답. 실시간 신고건은 어차피
    // 하루에도 자주 바뀌지 않으므로 5분 지연은 체감상 무의미하고, 함수 호출 수를 크게 줄여줌.
    res.setHeader('Cache-Control', 'public, s-maxage=300, stale-while-revalidate=1800');
    return res.status(200).json({ apt: finalApt, rent: dbPayload.rent });
  } catch (err) {
    console.error('핸들러 에러:', err.message);
    console.error('스택:', err.stack);
    return res.status(500).json({ error: err.message });
  }
}

/* ════════════════════════════════════
   국토부 실시간 API (아파트만 - 연립다세대/단독다가구는 배치 수집으로 커버)
════════════════════════════════════ */
async function fetchRealtimeApt(lawdCd, ym) {
  if (!APT_API_KEY) {
    console.warn('APT_API_KEY 없음 - 실시간 스킵');
    return [];
  }
  try {
    const url = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
      + '?serviceKey=' + encodeURIComponent(APT_API_KEY)
      + '&LAWD_CD=' + lawdCd
      + '&DEAL_YMD=' + ym
      + '&numOfRows=1000'
      + '&pageNo=1';
    const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const text     = await response.text();
    if (text.includes('<errMsg>') || text.includes('SERVICE_KEY_IS_NOT_REGISTERED_ERROR')) {
      console.warn('국토부 API 에러:', text.slice(0, 200));
      return [];
    }
    const items = parseXMLItems(text);
    console.log(`실시간 ${ym} ${lawdCd}: ${items.length}건`);
    return items;
  } catch (e) {
    console.error('실시간 API 실패:', e.message);
    return [];
  }
}

/* ── XML 파싱 ── */
function parseXMLItems(xmlText) {
  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let match;
  while ((match = itemRegex.exec(xmlText)) !== null) {
    const block = match[1];
    items.push({
      _get: function(tag) {
        const r = new RegExp('<' + tag + '>([^<]*)<\\/' + tag + '>');
        const m = block.match(r);
        return m ? m[1].trim() : '';
      }
    });
  }
  return items;
}

/* ── XML(실시간 아파트) → 정규화
   villa 파서(shared-villa.mjs)와 동일하게 bonbun/bubun을 지번 본번/부번으로 매핑해서
   DB에 쌓인 house_trades의 main_num/sub_num과 의미가 일치하도록 맞췄습니다. ── */
function normalizeXMLItem(item, regionName) {
  const year  = parseInt(item._get('dealYear'))  || 0;
  const month = parseInt(item._get('dealMonth')) || 0;
  const day   = parseInt(item._get('dealDay'))   || 0;
  const bunjiRaw = item._get('jibun');
  const bonbun   = item._get('bonbun');
  const bubun    = item._get('bubun');
  return {
    danji:      item._get('aptNm'),
    dong:       item._get('umdNm') || '',
    deal_date:  String(year) + String(month).padStart(2,'0') + String(day).padStart(2,'0'),
    price:      parseInt((item._get('dealAmount') || '0').replace(/,/g, '')) || 0,
    size:       parseFloat(item._get('excluUseAr')) || 0,
    floor:      parseInt(item._get('floor')) || 0,
    build_year: parseInt(item._get('buildYear')) || null,
    road_name:  item._get('roadNm') || '',
    region:     regionName || '',
    bunji:      (bunjiRaw === '' || bunjiRaw === '0') ? '' : bunjiRaw,
    main_num:   parseInt(bonbun, 10) || 0,
    sub_num:    (bubun === '' || parseInt(bubun, 10) === 0) ? null : parseInt(bubun, 10),
    source:     'realtime',
    buildingType: 'apt',
  };
}

/* ── house_trades / villa_trades 공통 정규화 (스키마 동일) ── */
function normalizeRow(row, buildingType) {
  return {
    danji:      row.danji || '',
    dong:       row.dong  || '',
    deal_date:  String(row.deal_date || ''),
    price:      row.price || 0,
    size:       row.size  || 0,
    floor:      row.floor || 0,
    build_year: row.build_year || null,
    road_name:  row.road_name  || '',
    region:     row.region || '',
    bunji:      row.bunji     || '',
    main_num:   row.main_num  || 0,
    sub_num:    row.sub_num   || null,
    source:     'db',
    buildingType,
  };
}

/* ── house_rent / villa_rent 공통 정규화 (스키마 동일, price 대신 deposit/monthly_rent) ── */
function normalizeRentRow(row, buildingType) {
  return {
    danji:        row.danji || '',
    dong:         row.dong  || '',
    deal_date:    String(row.deal_date || ''),
    deposit:      row.deposit || 0,
    monthly_rent: row.monthly_rent || 0,
    size:         row.size  || 0,
    floor:        row.floor || 0,
    build_year:   row.build_year || null,
    road_name:    row.road_name  || '',
    region:       row.region || '',
    bunji:        row.bunji     || '',
    main_num:     row.main_num  || 0,
    sub_num:      row.sub_num   || null,
    buildingType,
  };
}

/* ── 중복 제거 ── */
function dedup(rows) {
  const seen = new Set();
  return rows.filter(row => {
    const key = `${row.buildingType}|${row.danji}|${row.deal_date}|${row.price}|${row.size}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
