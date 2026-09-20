/* ════════════════════════════════════
   전체 지역 좌표/법정동코드/건축물대장 웜업 스크립트 (최종 통합본)
   - house_trades(아파트), villa_trades(연립다세대) 테이블에서 고유 단지를 뽑아
     아직 complex_coords에 없는 것만 카카오 REST API로 지오코딩 + 법정동코드 조회 → 저장
   - 좌표를 구한 단지는 이어서 배포된 /api/get-building 을 호출해 건축물대장도 함께 캐시
     (단독/다가구는 원래 앱에서도 지오코딩·건축물대장 대상이 아니라 웜업에서도 제외)
   - 이미 좌표는 있지만 건축물대장이 아직 없는 단지는 좌표 재조회 없이
     건축물대장만 따로 재시도합니다 (좌표 캐시 여부와 건축물대장 캐시 여부를
     독립적으로 추적 - 예전에 있던 "좌표는 성공했는데 건축물대장만 계속
     빠짐" 버그 수정본입니다).
   - 카카오 API 일일 할당량이 소진되면(429 반복 또는 400+code:-10) 즉시
     감지해서 남은 대상을 헛되이 호출하지 않고 깔끔하게 중단합니다.
   - 이미 처리된 단지는 건너뛰므로, 시간이 부족해 중간에 멈춰도 다시
     실행하면 이어서 처리됩니다.
   ⚠️ 건축물대장(get-building)은 PUBLIC_DATA_API_KEY 하나를 이 웜업 스크립트와
      낮 시간 실사용(브라우저에서 매물 패널 열 때)이 함께 나눠 씁니다. 전국
      단위로 밀린 백로그가 많으면, 이 스크립트가 새벽에 그날 할당량을 혼자
      다 써버려서 낮에 실사용할 때 정작 할당량이 없는 상황이 생길 수 있습니다
      (2026-07 실사용 중 "API limit has been exceeded" 반복 발생으로 확인됨).
      그래서 건축물대장 웜업 호출 수에 실행당 상한(MAX_BUILDING_WARMUP_PER_RUN)을
      둬서, 낮 시간용 할당량을 항상 일부 남겨두도록 했습니다. 상한에 도달하면
      나머지는 다음 실행(다음날 새벽)으로 넘어가며, 이미 처리된 건 건너뛰므로
      결국엔 전부 처리됩니다 - 그냥 하루에 몰아서 처리하지 않을 뿐입니다.
   ⚠️ 2026-09(사용자 피드백): 두 가지를 고쳤습니다.
      1) house_trades처럼 행이 아주 많은 테이블을 OFFSET(.range()) 페이지네이션으로 돌면
         뒤쪽 페이지일수록 앞부분을 다 스캔하고 버리는 비용이 커져 statement_timeout에
         걸리기 쉬웠고, 실패하면 그 지점에서 조용히 "부분 목록"만으로 계속 진행되고
         있었습니다 - id 기준 키셋(커서) 페이지네이션으로 바꿔 이 문제의 근본 원인을
         없앴습니다(fetchDistinctComplexes/fetchExistingCoords 참고).
      2) 좌표 웜업(coordTargets) 단계가 매번 건축물대장 웜업 한도(MAX_BUILDING_WARMUP_PER_RUN)
         전체를 먼저 써버려서, "좌표는 있지만 건축물대장만 없는" 재시도 대상이 매 실행
         0건 처리된 채 계속 이월되고 있었습니다 - 이 재시도 대상을 좌표 웜업보다 먼저,
         한도의 절반을 예약해서 처리하도록 순서를 바꿔 매 실행마다 반드시 진행되게
         했습니다(processBuildingOnlyBatch 참고).
   ⚠️ 2026-09(사용자가 공유해준 data.go.kr 활용신청 현황): get-building.js가 부르는
      건축HUB 세부 API 4개(getBrTitleInfo/getBrHsprcInfo/getBrFlrOulnInfo/
      getBrExposPubuseAreaInfo) 모두 일일 트래픽 한도가 각각 10,000건임을 확인했습니다.
      건물 1건 조회 = 4개 API 각 1회 소모(1:1)이므로 실질 하루 한도는 약 10,000건 -
      예전엔 이 숫자를 몰라 500건(5%)으로만 보수적으로 잡았던 걸, 낮 시간 실사용 몫
      (6,000건 이상)을 넉넉히 남기면서 MAX_BUILDING_WARMUP_PER_RUN을 4,000건으로
      올렸습니다. 대신 한도가 8배 늘어난 만큼 순차 처리로는 실행시간이 너무 길어져
      processBuildingOnlyBatch를 동시처리(BUILDING_CONCURRENCY=6)로 바꿨습니다.
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
const supabase = createClient(
  process.env.SUPABASE_URL?.trim(),
  process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(),
  {
    auth: { persistSession: false },
    // Node 20은 네이티브 WebSocket이 없어 Realtime 클라이언트 초기화가 실패함 → ws로 우회
    realtime: { transport: ws },
  }
);
const KAKAO_REST_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const DELAY_MS = 250;          // 카카오 REST API 호출 사이 간격 (레이트리밋 안전 마진)
const BUILDING_DELAY_MS = 300; // 건축물대장만 재시도할 때 동시처리 워커 사이 시작 간격(레이트리밋 안전마진)
const BUILDING_CONCURRENCY = 6; // 건축물대장 재시도 동시 처리 수 - 아래 MAX_BUILDING_WARMUP_PER_RUN
                                 // 상향에 맞춰 순차(1개씩)로는 실행시간이 너무 길어져 동시처리로 전환.
const CONCURRENCY = 3;         // 동시 처리 단지 수
const PAGE_SIZE = 1000;        // Supabase 페이지네이션 단위
// ⚠️ 2026-09(사용자가 공유해준 data.go.kr 활용신청 현황): get-building.js 한 번 호출이
// 내부적으로 건축HUB의 getBrTitleInfo/getBrHsprcInfo/getBrFlrOulnInfo/getBrExposPubuseAreaInfo
// 4개 세부 API를 동시에 부르는데(각 API 일일 트래픽 10,000건, PUBLIC_DATA_API_KEY로 공유),
// 이 4개가 전부 같은 만큼(1:1) 소모되니 사실상 "하루 10,000번 건물 조회"까지 여유가 있음.
// 예전엔 이 숫자를 몰라서 500건(전체의 5%)으로만 아주 보수적으로 잡았었는데, 실제 한도를
// 알고 나니 너무 낮았음 - 낮 시간 실사용(개인 앱이라 하루 수십~수백 건 수준으로 추정)에
// 넉넉한 여유(10,000건 중 6,000건 이상)를 남기면서도 19,623건 백로그를 며칠 안에 털어낼 수
// 있도록 4,000건으로 올림. 그래도 환경변수로 조절 가능하게 유지함(필요시 낮추거나 더 올릴 수 있음).
const MAX_BUILDING_WARMUP_PER_RUN = parseInt(process.env.MAX_BUILDING_WARMUP_PER_RUN || '4000', 10);
let buildingWarmupCount = 0;
const sleep = ms => new Promise(r => setTimeout(r, ms));
/* ── 호출 제한 대응 ──
   카카오 로컬 API의 "일일 할당량 초과"는 429가 아니라 HTTP 400 + code:-10
   으로 내려옵니다. 이 경우는 초당 제한이 아니라 오늘 할당량이 완전히
   소진된 것이므로, 재시도해도 절대 풀리지 않습니다 → 즉시 감지해서
   바로 중단합니다 (그렇지 않으면 남은 대상 전부에 대해 헛되이 계속
   호출하며 전부 "못 찾음"으로 오판하게 됩니다). 429가 연속으로 여러 번
   나는 경우도 같은 방식으로 안전하게 중단 처리합니다. */
let consecutive429 = 0;
const MAX_CONSECUTIVE_429 = 5;
let quotaExhausted = false;
let debugLogCount = 0;
async function kakaoFetch(url) {
  if (quotaExhausted) return null;
  let res;
  try {
    res = await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO_REST_KEY}` } });
  } catch (e) {
    console.error('❌ 카카오 API 네트워크 오류:', e.message);
    return null;
  }
  if (res.status === 429) {
    consecutive429++;
    console.error(`⚠️  카카오 API 호출 제한(429) 감지 (연속 ${consecutive429}회)`);
    if (consecutive429 >= MAX_CONSECUTIVE_429 && !quotaExhausted) {
      stopForQuota('호출 제한(429)이 계속 걸림');
    }
    return null;
  }
  if (res.status === 400) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* ignore */ }
    if (body && (body.code === -10 || /API limit has been exceeded/i.test(body.message || ''))) {
      stopForQuota('일일 호출 할당량 초과 (code -10)');
      return null;
    }
    return null;
  }
  consecutive429 = 0;
  if (!res.ok) {
    if (debugLogCount < 3) {
      debugLogCount++;
      let bodyText = '';
      try { bodyText = await res.text(); } catch (e) { bodyText = '(본문 읽기 실패)'; }
      console.error(`❌ 카카오 API 실패 (원인불명) - status:${res.status}, url:${url}`);
      console.error(`   응답 본문: ${bodyText.slice(0, 300)}`);
    }
    return null;
  }
  try {
    return await res.json();
  } catch (e) {
    return null;
  }
}
function stopForQuota(reason) {
  if (quotaExhausted) return;
  quotaExhausted = true;
  console.error(`\n🛑 ${reason} → 여기서 중단합니다.`);
  console.error(`   ⚠️  이 할당량은 앱(App) 단위라서, 실제 서비스 화면(브라우저)의 카카오맵 주소 검색도 같이 막혀 있을 수 있습니다.`);
  console.error(`   이미 처리된 단지는 저장되어 있으니, 할당량이 초기화된 뒤(보통 자정 기준) workflow를 다시 실행하면 남은 단지부터 이어서 처리됩니다.\n`);
}
function buildCacheKey(dong, danji, bunji, roadName, mainNum, subNum) {
  return [dong, danji, bunji, roadName, mainNum, subNum].join('|').toLowerCase();
}
/* 건축물대장 캐시 키 (get-building.js가 building_info에 저장할 때 쓰는 유니크 키와 동일한 개념) */
function computeBunJi(row) {
  let main = null, sub = null;
  if (row.bunji) {
    const parts = String(row.bunji).split('-');
    const m1 = parseInt(parts[0], 10);
    const m2 = parts[1] !== undefined ? parseInt(parts[1], 10) : null;
    main = Number.isNaN(m1) ? null : m1;
    sub = (m2 === null || Number.isNaN(m2) || m2 === 0) ? null : m2;
  }
  if (!main && row.road_name && row.main_num) { main = row.main_num; sub = row.sub_num; }
  if (!main) return null;
  return { bun: String(main).padStart(4, '0'), ji: String(sub || 0).padStart(4, '0') };
}
function buildBuildingKey(sigunguCd, bjdongCd, bun, ji, bldNm) {
  return [sigunguCd, bjdongCd, bun, ji, (bldNm || '').trim()].join('|');
}
/* ── 테이블에서 고유 단지 목록(주소 관련 컬럼만) 페이지네이션으로 전부 뽑아 dedupe ──
   ⚠️ 2026-09(사용자 피드백: 실행 로그에 "house_trades 조회 에러: canceling statement
   due to statement timeout"가 찍히고 그 뒤로 조용히 부분 목록만으로 계속 진행됨을 발견):
   원래는 .range(from, from+999)로 OFFSET 기반 페이지네이션을 했는데, house_trades처럼
   행이 아주 많은 테이블에서는 오프셋이 커질수록 Postgres가 앞부분을 다 스캔하고
   버리는 비용이 계속 늘어나(전형적인 "깊은 OFFSET 페이지네이션" 문제) 뒤쪽 페이지에서
   service_role의 statement_timeout(30s, migration_service_role_timeout.sql 참고)에
   걸리기 쉬웠음. 그리고 실패하면 그 지점에서 바로 break해서 "그 뒤 오프셋에 있던 단지들"이
   그날 목록에서 통째로 누락됐는데도 로그상 개수만 보면 정상 완료처럼 보였음.
   → id 기준 키셋(커서) 페이지네이션(.gt('id', lastId).order('id').limit(n))으로 바꿔서
   페이지 비용이 오프셋 크기와 무관하게 항상 비슷하게 유지되도록 함 - 애초에 이 타임아웃의
   근본 원인을 없앰. 그래도 일시적 오류(네트워크 등)가 나면 페이지 크기를 절반씩 줄여가며
   몇 차례 재시도하고, 그래도 안 되면 그 지점에서 멈추되 "부분 목록"이라는 걸 명확히 로그로
   남김(예전처럼 조용히 넘어가지 않음). */
async function fetchDistinctComplexes(table) {
  const map = new Map();
  let lastId = 0;
  let pageSize = PAGE_SIZE;
  const MAX_ATTEMPTS_PER_PAGE = 4;
  while (true) {
    let data = null, error = null, attemptSize = pageSize;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS_PER_PAGE; attempt++) {
      const res = await supabase
        .from(table)
        .select('id,region,dong,danji,bunji,road_name,main_num,sub_num')
        .gt('id', lastId)
        .order('id', { ascending: true })
        .limit(attemptSize);
      data = res.data; error = res.error;
      if (!error) break;
      console.error(`⚠️  ${table} 조회 실패(id>${lastId}, 페이지크기 ${attemptSize}, 시도 ${attempt}/${MAX_ATTEMPTS_PER_PAGE}): ${error.message}`);
      attemptSize = Math.max(50, Math.floor(attemptSize / 2)); // 다음 시도는 더 작은 페이지로
      await sleep(1000 * attempt);
    }
    if (error) {
      console.error(`❌ ${table} 조회 에러: id>${lastId} 지점에서 ${MAX_ATTEMPTS_PER_PAGE}회 재시도 후에도 실패 - 이 지점부터는 이번 실행에서 건너뜁니다(⚠️ 부분 목록):`, error.message);
      break;
    }
    if (!data || data.length === 0) break;
    for (const row of data) {
      const key = buildCacheKey(row.dong, row.danji, row.bunji, row.road_name, row.main_num, row.sub_num);
      if (!map.has(key)) map.set(key, row);
      lastId = row.id;
    }
    if (data.length < attemptSize) break;
    pageSize = PAGE_SIZE; // 다음 페이지는 원래 크기로 복귀 (이전 페이지에서만 줄었을 수 있으므로)
  }
  return map;
}
/* ── 이미 캐시된 좌표: cache_key → {lat,lon,sigunguCd,bjdongCd} ──
   ⚠️ 2026-09: complex_coords도 house_trades와 같은 id 컬럼 구조(complex_coords_table.sql
   참고)라 같은 깊은 OFFSET 페이지네이션 위험이 있음 - 25만건을 이미 넘어 계속 느는
   테이블이라 미리 id 기준 키셋 페이지네이션으로 바꿔둠(fetchDistinctComplexes 상단
   주석 참고 - 같은 문제, 같은 해법). */
async function fetchExistingCoords() {
  const map = new Map();
  let lastId = 0;
  while (true) {
    const { data, error } = await supabase
      .from('complex_coords')
      .select('id,cache_key,lat,lon,sigungu_cd,bjdong_cd')
      .gt('id', lastId)
      .order('id', { ascending: true })
      .limit(PAGE_SIZE);
    if (error) { console.error('❌ complex_coords 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => { map.set(r.cache_key, { lat: r.lat, lon: r.lon, sigunguCd: r.sigungu_cd, bjdongCd: r.bjdong_cd }); lastId = r.id; });
    if (data.length < PAGE_SIZE) break;
  }
  return map;
}
/* ── 이미 캐시된 건축물대장 조합(sigunguCd|bjdongCd|bun|ji|bldNm) 전부 가져오기 ── */
async function fetchExistingBuildingKeys() {
  const set = new Set();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('building_info')
      .select('sigungu_cd,bjdong_cd,bun,ji,bld_nm')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ building_info 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => set.add(buildBuildingKey(r.sigungu_cd, r.bjdong_cd, r.bun, r.ji, r.bld_nm)));
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return set;
}
/* ── 카카오 REST 주소 검색 ── */
async function kakaoAddressSearch(query) {
  const url = `https://dapi.kakao.com/v2/local/search/address.json?query=${encodeURIComponent(query)}`;
  const json = await kakaoFetch(url);
  const doc = json?.documents?.[0];
  if (!doc) return null;
  return { lat: parseFloat(doc.y), lon: parseFloat(doc.x) };
}
/* ── 카카오 REST 키워드(장소) 검색 - 주소 검색 실패 시 fallback ── */
async function kakaoKeywordSearch(query) {
  const url = `https://dapi.kakao.com/v2/local/search/keyword.json?query=${encodeURIComponent(query)}`;
  const json = await kakaoFetch(url);
  const doc = json?.documents?.[0];
  if (!doc) return null;
  return { lat: parseFloat(doc.y), lon: parseFloat(doc.x) };
}
/* ── 카카오 REST 좌표 → 법정동코드 ── */
async function kakaoCoordToRegionCode(lat, lon) {
  const url = `https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x=${lon}&y=${lat}`;
  const json = await kakaoFetch(url);
  const b = (json?.documents || []).find(d => d.region_type === 'B');
  if (!b || !b.code || b.code.length < 10) return null;
  return { sigunguCd: b.code.slice(0, 5), bjdongCd: b.code.slice(5, 10) };
}
/* ── 클라이언트의 buildGeocodeCandidates()와 동일한 우선순위 ──
   1) 동 + 지번   2) 동 + 단지명   3) (아파트만) 도로명 + 본번(-부번) */
function buildCandidates(row, buildingType) {
  const region = (row.region || '').trim();
  const dong = (row.dong || '').trim();
  const danji = (row.danji || '').trim();
  const bunji = (row.bunji || '').trim();
  const road = (row.road_name || '').trim();
  const main = row.main_num;
  const sub = row.sub_num;
  const candidates = [];
  if (dong && bunji) candidates.push(`${region} ${dong} ${bunji}`.trim());
  if (dong && danji) candidates.push(`${region} ${dong} ${danji}`.trim());
  if (buildingType === 'apt' && road && main) {
    let addr = `${road} ${main}`;
    if (sub && sub !== 0) addr += `-${sub}`;
    candidates.push(`${region} ${addr}`.trim());
  }
  return candidates;
}
async function geocodeComplex(row, buildingType) {
  const candidates = buildCandidates(row, buildingType);
  for (const q of candidates) {
    if (!q || q.length < 2) continue;
    let coord = await kakaoAddressSearch(q);
    await sleep(DELAY_MS);
    if (!coord) {
      coord = await kakaoKeywordSearch(q);
      await sleep(DELAY_MS);
    }
    if (coord) return coord;
  }
  return null;
}
async function saveCoord(cacheKey, lat, lon, sigunguCd, bjdongCd) {
  const { error } = await supabase.from('complex_coords').upsert({
    cache_key: cacheKey, lat, lon,
    sigungu_cd: sigunguCd || null, bjdong_cd: bjdongCd || null,
  }, { onConflict: 'cache_key' });
  if (error) console.error('❌ complex_coords 저장 에러:', error.message);
}
/* ── 건축물대장 웜업: 이미 배포된 /api/get-building을 그대로 호출 →
      그 안에서 알아서 building_info 테이블에 캐시해줌 (로직 중복 없이 재사용)
      ⚠️ 실행당 MAX_BUILDING_WARMUP_PER_RUN 개까지만 호출하고, 넘어가면
      스킵함 (호출 자체를 안 하므로 building_info에 저장도 안 되고, 다음
      실행 때 "아직 캐시 안 된 것"으로 다시 잡혀서 이어서 처리됨) ── */
async function warmBuildingInfo(row, sigunguCd, bjdongCd) {
  if (buildingWarmupCount >= MAX_BUILDING_WARMUP_PER_RUN) return;
  const bunJi = computeBunJi(row);
  if (!bunJi) return;
  buildingWarmupCount++;
  const url = `${SITE_URL}/api/get-building?sigunguCd=${sigunguCd}&bjdongCd=${bjdongCd}`
    + `&bun=${bunJi.bun}&ji=${bunJi.ji}&bldNm=${encodeURIComponent(row.danji || '')}`;
  try {
    await fetch(url, { signal: AbortSignal.timeout(15000) });
  } catch (e) {
    console.error('❌ 건축물대장 웜업 실패:', e.message);
  }
}
async function processQueue(items, worker, concurrency) {
  let idx = 0, done = 0;
  const total = items.length;
  async function runOne() {
    while (idx < items.length) {
      if (quotaExhausted) return; // 할당량 소진 시 남은 큐 처리 중단 (Actions 시간 낭비 방지)
      const item = items[idx++];
      await worker(item);
      done++;
      if (done % 50 === 0 || done === total) console.log(`   진행: ${done}/${total}`);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, runOne));
}
async function main() {
  if (!KAKAO_REST_KEY) {
    console.error('❌ KAKAO_REST_API_KEY 환경변수가 없습니다. GitHub 저장소 Secrets에 추가해 주세요.');
    process.exit(1);
  }
  console.log('📦 기존 캐시된 좌표 목록 불러오는 중...');
  const existingCoords = await fetchExistingCoords();
  console.log(`   → 이미 캐시된 단지 ${existingCoords.size}개`);
  console.log('📦 기존 캐시된 건축물대장 목록 불러오는 중...');
  const existingBuildingKeys = await fetchExistingBuildingKeys();
  console.log(`   → 이미 건축물대장 캐시된 조합 ${existingBuildingKeys.size}개`);
  console.log(`📦 건축물대장 웜업 실행당 상한: ${MAX_BUILDING_WARMUP_PER_RUN}건 (낮 시간 실사용 할당량 보호용)`);
  // 단독/다가구(single_trades)는 원래 앱에서도 지오코딩·건축물대장 대상이 아니므로 웜업에서도 제외
  const tableTypes = [
    { table: 'house_trades', type: 'apt' },
    { table: 'villa_trades', type: 'villa' },
  ];
  const allEntries = []; // [cacheKey, row, type]
  const seen = new Set();
  for (const { table, type } of tableTypes) {
    console.log(`\n📦 ${table} 고유 단지 목록 추출 중...`);
    const map = await fetchDistinctComplexes(table);
    console.log(`   → ${table}: 고유 단지 ${map.size}개`);
    for (const [key, row] of map) {
      if (seen.has(key)) continue;
      seen.add(key);
      allEntries.push([key, row, type]);
    }
  }
  console.log(`\n📦 전체 고유 단지: ${allEntries.length}개`);
  // 좌표가 아예 없는 단지 → 신규 웜업 대상
  const coordTargets = allEntries.filter(([key]) => !existingCoords.has(key));
  // 좌표는 있지만 건축물대장이 아직 캐시 안 된 단지 → 건축물대장만 재시도 대상
  const buildingOnlyTargets = allEntries.filter(([key, row]) => {
    if (!existingCoords.has(key)) return false; // 좌표 없는 건 위에서 이미 처리
    const coord = existingCoords.get(key);
    if (!coord.sigunguCd || !coord.bjdongCd) return false; // 법정동코드 자체가 없으면 재시도 불가
    const bunJi = computeBunJi(row);
    if (!bunJi) return false;
    const bKey = buildBuildingKey(coord.sigunguCd, coord.bjdongCd, bunJi.bun, bunJi.ji, row.danji);
    return !existingBuildingKeys.has(bKey);
  });
  console.log(`📦 신규 좌표 웜업 대상: ${coordTargets.length}개`);
  console.log(`📦 건축물대장만 재시도 대상: ${buildingOnlyTargets.length}개\n`);

  // ⚠️ 2026-09(사용자 요청: "건축물대장도 같이 웜업할 수 있게 해줘"): 원래는 좌표 웜업
  // (coordTargets) 단계에서 새로 지오코딩에 성공할 때마다 그 자리에서 warmBuildingInfo를
  // 호출했는데, coordTargets가 많은 날은 이 단계만으로 MAX_BUILDING_WARMUP_PER_RUN
  // 전체를 다 써버려서 "좌표는 이미 있는데 건축물대장만 없는" 재시도 대상(buildingOnlyTargets)이
  // 매번 0건 처리된 채 그대로 다음날로 밀리기만 했음(실행 로그에서 19623건 전체 이월로
  // 확인됨). 그래서 이 재시도 대상을 좌표 웜업보다 먼저, 전체 한도의 절반을 예약해서
  // 먼저 처리하도록 순서를 바꿈 - 매 실행마다 이 백로그도 최소한만큼은 반드시 줄어듦.
  // 재시도 대상이 예약분보다 적으면 남는 한도는 그대로 좌표 웜업 단계로 넘어가 낭비되지
  // 않고, 좌표 웜업이 끝난 뒤에도 한도가 남으면 재시도 대상을 이어서 더 처리함.
  // ⚠️ 2026-09: MAX_BUILDING_WARMUP_PER_RUN을 500→4,000으로 올리면서, 예전처럼 한 건씩
  // 순차 처리(건당 BUILDING_DELAY_MS 대기)하면 4,000건 × 0.3초만 해도 20분에 이 API
  // 호출 자체의 소요시간(초 단위)까지 겹쳐 실행시간이 지나치게 길어짐 - coordTargets
  // 웜업(processQueue)과 동일하게 동시처리(BUILDING_CONCURRENCY)로 바꿔서 늘어난 상한
  // 만큼의 실행시간 증가를 감당 가능한 수준으로 유지함.
  async function processBuildingOnlyBatch(targets, startIdx, budgetCap) {
    let success = 0, idx = startIdx, doneInBatch = 0;
    const batchTotal = Math.max(0, Math.min(targets.length, budgetCap - buildingWarmupCount) );
    async function runOne() {
      while (idx < targets.length && buildingWarmupCount < budgetCap) {
        const [, row] = targets[idx++];
        const key = buildCacheKey(row.dong, row.danji, row.bunji, row.road_name, row.main_num, row.sub_num);
        const coord = existingCoords.get(key);
        if (coord && coord.sigunguCd && coord.bjdongCd) {
          await warmBuildingInfo(row, coord.sigunguCd, coord.bjdongCd);
          success++;
        }
        doneInBatch++;
        await sleep(BUILDING_DELAY_MS);
        if (doneInBatch % 200 === 0) console.log(`   진행: ${doneInBatch}${batchTotal ? '/' + batchTotal : ''}건 처리`);
      }
    }
    await Promise.all(Array.from({ length: BUILDING_CONCURRENCY }, runOne));
    return { success, nextIdx: idx };
  }

  const MAX_BUILDING_RETRY_RESERVE = Math.ceil(MAX_BUILDING_WARMUP_PER_RUN / 2);
  let buildingOnlyNextIdx = 0;
  if (buildingOnlyTargets.length > 0) {
    console.log(`📦 건축물대장 재시도 우선 처리 시작 (좌표는 있지만 아직 건축물대장이 없는 단지, 전체 ${buildingOnlyTargets.length}개 중 이번 실행 예약분 최대 ${MAX_BUILDING_RETRY_RESERVE}개)...`);
    const { success: bSuccess, nextIdx } = await processBuildingOnlyBatch(buildingOnlyTargets, 0, MAX_BUILDING_RETRY_RESERVE);
    buildingOnlyNextIdx = nextIdx;
    console.log(`🎉 건축물대장 재시도(우선분) 완료! 처리 ${bSuccess}건\n`);
  }

  let success = 0, fail = 0;
  await processQueue(coordTargets, async ([cacheKey, row, type]) => {
    const coord = await geocodeComplex(row, type);
    if (!coord) { fail++; return; }
    const region = await kakaoCoordToRegionCode(coord.lat, coord.lon);
    await sleep(DELAY_MS);
    await saveCoord(cacheKey, coord.lat, coord.lon, region?.sigunguCd, region?.bjdongCd);
    success++;
    if (region) {
      await warmBuildingInfo(row, region.sigunguCd, region.bjdongCd);
    }
  }, CONCURRENCY);
  if (quotaExhausted) {
    console.log(`\n⏸️  일일 호출 제한으로 좌표 웜업 중간에 중단됨. 성공 ${success}건 / 실패 ${fail}건 / 미처리 ${coordTargets.length - success - fail}건`);
    console.log(`   나중에(예: 다음날) 이 workflow를 다시 실행하면 미처리 단지부터 이어서 진행됩니다.`);
  } else {
    console.log(`\n🎉 좌표 웜업 완료! 성공 ${success}건 / 실패 ${fail}건`);
    if (fail > 0) {
      console.log(`   (실패한 단지는 주소 정보가 부실하거나 카카오에서 찾지 못한 경우입니다. 다시 실행하면 재시도됩니다.)`);
    }
  }

  // 건축물대장 재시도 이어서 처리 (좌표 웜업 단계에서 얼마나 소진했는지에 따라 남는 한도로)
  if (buildingOnlyNextIdx < buildingOnlyTargets.length) {
    if (buildingWarmupCount < MAX_BUILDING_WARMUP_PER_RUN) {
      const remaining = buildingOnlyTargets.length - buildingOnlyNextIdx;
      console.log(`\n📦 건축물대장 재시도 이어서 처리 (좌표 웜업 이후 남은 한도 ${MAX_BUILDING_WARMUP_PER_RUN - buildingWarmupCount}건, 남은 대상 ${remaining}건 중)...`);
      const { success: bSuccess2, nextIdx: nextIdx2 } = await processBuildingOnlyBatch(buildingOnlyTargets, buildingOnlyNextIdx, MAX_BUILDING_WARMUP_PER_RUN);
      buildingOnlyNextIdx = nextIdx2;
      console.log(`\n🎉 건축물대장 재시도(이어서분) 완료! 처리 ${bSuccess2}건`);
    }
    if (buildingOnlyNextIdx < buildingOnlyTargets.length) {
      console.log(`\n⏸️  건축물대장 웜업 실행당 상한(${MAX_BUILDING_WARMUP_PER_RUN}건)에 도달 - 전체 미처리 ${buildingOnlyTargets.length - buildingOnlyNextIdx}건은 다음 실행으로 넘어갑니다.`);
    }
  }
}
main().catch(e => { console.error('❌ 치명적 오류:', e); process.exit(1); });
