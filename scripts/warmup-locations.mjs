/* ════════════════════════════════════
   전체 지역 좌표/법정동코드/건축물대장 웜업 스크립트
   - house_trades(아파트), villa_trades(연립다세대) 테이블에서 고유 단지를 뽑아
     아직 complex_coords에 없는 것만 카카오 REST API로 지오코딩 + 법정동코드 조회 → 저장
   - 좌표를 구한 단지는 이어서 배포된 /api/get-building 을 호출해 건축물대장도 함께 캐시
     (단독/다가구는 원래 앱에서도 지오코딩·건축물대장 대상이 아니라 웜업에서도 제외)
   - 이미 처리된 단지(complex_coords에 이미 있는 cache_key)는 건너뛰므로
     시간이 부족해 중간에 멈춰도 다시 실행하면 이어서 처리됩니다.
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

const DELAY_MS = 250;      // 카카오 REST API 호출 사이 간격 (레이트리밋 안전 마진)
const CONCURRENCY = 3;     // 동시 처리 단지 수
const PAGE_SIZE = 1000;    // Supabase 페이지네이션 단위

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ── 호출 제한(429) 대응 ──
   카카오 로컬 API 제한은 대부분 "일일 할당량" 성격이라, 한 번 걸리면
   같은 실행 안에서 재시도해도 똑같이 막힙니다. 그래서 429가 연속으로
   몇 번 발생하면 "오늘 할당량 소진"으로 보고 스크립트를 안전하게 멈춥니다.
   이미 처리된 단지는 complex_coords에 저장돼 있으니, 나중에(예: 다음날)
   workflow를 다시 실행하면 남은 단지부터 이어서 처리됩니다. */
let consecutive429 = 0;
const MAX_CONSECUTIVE_429 = 5;
let quotaExhausted = false;

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
  // 카카오는 "일일 할당량 초과"를 429가 아니라 HTTP 400 + code:-10 으로 내려줌.
  // 이 경우는 초당 제한이 아니라 오늘 할당량이 완전히 소진된 것이므로,
  // 재시도해도 절대 풀리지 않음 → 즉시 감지해서 바로 중단해야 함
  // (그렇지 않으면 남은 대상 전부에 대해 헛되이 계속 호출하며 "못 찾음"으로 오판하게 됨).
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
  if (!res.ok) return null;
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

/* ── 테이블에서 고유 단지 목록(주소 관련 컬럼만) 페이지네이션으로 전부 뽑아 dedupe ── */
async function fetchDistinctComplexes(table) {
  const map = new Map();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from(table)
      .select('region,dong,danji,bunji,road_name,main_num,sub_num')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error(`❌ ${table} 조회 에러:`, error.message); break; }
    if (!data || data.length === 0) break;
    for (const row of data) {
      const key = buildCacheKey(row.dong, row.danji, row.bunji, row.road_name, row.main_num, row.sub_num);
      if (!map.has(key)) map.set(key, row);
    }
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return map;
}

/* ── 이미 캐시된 cache_key 전부 가져오기 ── */
async function fetchExistingCoordKeys() {
  const set = new Set();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('complex_coords')
      .select('cache_key')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ complex_coords 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => set.add(r.cache_key));
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
      그 안에서 알아서 building_info 테이블에 캐시해줌 (로직 중복 없이 재사용) ── */
async function warmBuildingInfo(row, sigunguCd, bjdongCd) {
  const { bunji, road_name, main_num, sub_num, danji } = row;
  let main = null, sub = null;
  if (bunji) {
    const parts = String(bunji).split('-');
    const m1 = parseInt(parts[0], 10);
    const m2 = parts[1] !== undefined ? parseInt(parts[1], 10) : null;
    main = Number.isNaN(m1) ? null : m1;
    sub = (m2 === null || Number.isNaN(m2) || m2 === 0) ? null : m2;
  }
  if (!main && road_name && main_num) { main = main_num; sub = sub_num; }
  if (!main) return;

  const bun = String(main).padStart(4, '0');
  const ji = String(sub || 0).padStart(4, '0');
  const url = `${SITE_URL}/api/get-building?sigunguCd=${sigunguCd}&bjdongCd=${bjdongCd}`
    + `&bun=${bun}&ji=${ji}&bldNm=${encodeURIComponent(danji || '')}`;
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
  const existingKeys = await fetchExistingCoordKeys();
  console.log(`   → 이미 캐시된 단지 ${existingKeys.size}개`);

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

  const targets = allEntries.filter(([key]) => !existingKeys.has(key));
  console.log(`📦 신규 웜업 대상: ${targets.length}개\n`);

  let success = 0, fail = 0;
  await processQueue(targets, async ([cacheKey, row, type]) => {
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
    console.log(`\n⏸️  일일 호출 제한으로 중간에 중단됨. 성공 ${success}건 / 실패 ${fail}건 / 미처리 ${targets.length - success - fail}건`);
    console.log(`   나중에(예: 다음날) 이 workflow를 다시 실행하면 미처리 단지부터 이어서 진행됩니다.`);
  } else {
    console.log(`\n🎉 웜업 완료! 성공 ${success}건 / 실패 ${fail}건`);
    if (fail > 0) {
      console.log(`   (실패한 단지는 주소 정보가 부실하거나 카카오에서 찾지 못한 경우입니다. 다시 실행하면 재시도됩니다.)`);
    }
  }
}

main().catch(e => { console.error('❌ 치명적 오류:', e); process.exit(1); });
