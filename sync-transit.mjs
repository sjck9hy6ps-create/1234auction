/* ════════════════════════════════════
   역세권(지하철역 접근성) 동기화 스크립트 - 2026-08 추가 (역세권/학군 연동 1단계)
   - complex_coords(warmup-locations.mjs가 이미 채워둔 단지별 위경도 캐시)에 있는
     단지 중, 아직 transit_features에 없는 것만 카카오 REST "카테고리로 장소 검색"
     (category_group_code=SW8, 지하철역)으로 반경 내 최단거리 지하철역을 찾아 저장.
   - 새 API 키 불필요: 기존 KAKAO_REST_API_KEY(웜업 스크립트와 동일 키)를 그대로 씀.
   - complex_coords가 좌표를 못 채운 단지는 여기서도 자연히 대상에서 빠짐(좌표 없이는
     지하철역 거리도 계산 불가) → complex_coords 웜업이 먼저 돌아야 이 스크립트도 의미가 있음.
   - 카카오 API 일일 할당량 소진 감지/중단 로직은 warmup-locations.mjs와 동일하게 이식.
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';

const supabase = createClient(
  process.env.SUPABASE_URL?.trim(),
  process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(),
  { auth: { persistSession: false }, realtime: { transport: ws } }
);
const KAKAO_REST_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const DELAY_MS = 250;
const CONCURRENCY = 3;
const PAGE_SIZE = 1000;
const SEARCH_RADIUS_M = 2000; // 이 반경 밖이면 "역세권 아님"으로 간주(먼 거리 취급)
// 실행당 처리 상한 - 건축물대장 웜업과 같은 KAKAO_REST_API_KEY(앱 단위 할당량)를
// 공유하므로, 이 스크립트가 하루치를 혼자 다 쓰지 않도록 여유 있게 상한을 둠.
const MAX_PER_RUN = parseInt(process.env.MAX_TRANSIT_PER_RUN || '3000', 10);

const sleep = ms => new Promise(r => setTimeout(r, ms));

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
    if (consecutive429 >= MAX_CONSECUTIVE_429 && !quotaExhausted) stopForQuota('호출 제한(429)이 계속 걸림');
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
  if (!res.ok) return null;
  try { return await res.json(); } catch (e) { return null; }
}
function stopForQuota(reason) {
  if (quotaExhausted) return;
  quotaExhausted = true;
  console.error(`\n🛑 ${reason} → 여기서 중단합니다. (다음 실행 때 이어서 처리됩니다)\n`);
}
/* ── 카카오 REST 카테고리 검색: 반경 내 지하철역 중 최단거리 ── */
async function nearestSubway(lat, lon) {
  const url = `https://dapi.kakao.com/v2/local/search/category.json?category_group_code=SW8`
    + `&x=${lon}&y=${lat}&radius=${SEARCH_RADIUS_M}&sort=distance&size=1`;
  const json = await kakaoFetch(url);
  const doc = json?.documents?.[0];
  if (!doc) return null; // 반경 내 지하철역 없음(멀다는 뜻 - null로 저장해 구분)
  return { distM: parseFloat(doc.distance), stationName: doc.place_name };
}
async function fetchAllCoords() {
  const map = new Map();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('complex_coords')
      .select('cache_key,lat,lon')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ complex_coords 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => { if (r.lat != null && r.lon != null) map.set(r.cache_key, { lat: r.lat, lon: r.lon }); });
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return map;
}
async function fetchExistingTransit() {
  const set = new Set();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('transit_features')
      .select('cache_key')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ transit_features 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => set.add(r.cache_key));
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
  }
  return set;
}
async function saveTransit(cacheKey, distM, stationName) {
  const { error } = await supabase.from('transit_features').upsert({
    cache_key: cacheKey, dist_subway_m: distM, nearest_station: stationName || null,
  }, { onConflict: 'cache_key' });
  if (error) console.error('❌ transit_features 저장 에러:', error.message);
}
async function processQueue(items, worker, concurrency) {
  let idx = 0, done = 0;
  const total = items.length;
  async function runOne() {
    while (idx < items.length) {
      if (quotaExhausted) return;
      const item = items[idx++];
      await worker(item);
      done++;
      if (done % 200 === 0 || done === total) console.log(`   진행: ${done}/${total}`);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, runOne));
}
async function main() {
  if (!KAKAO_REST_KEY) {
    console.error('❌ KAKAO_REST_API_KEY 환경변수가 없습니다.');
    process.exit(1);
  }
  console.log('📦 complex_coords 좌표 목록 불러오는 중...');
  const coords = await fetchAllCoords();
  console.log(`   → 좌표 있는 단지 ${coords.size}개`);
  console.log('📦 이미 처리된 transit_features 목록 불러오는 중...');
  const existing = await fetchExistingTransit();
  console.log(`   → 이미 처리됨 ${existing.size}개`);
  const targets = [...coords.entries()].filter(([key]) => !existing.has(key)).slice(0, MAX_PER_RUN);
  console.log(`📦 이번 실행 처리 대상: ${targets.length}개 (실행당 상한 ${MAX_PER_RUN}개)\n`);
  let success = 0, none = 0, fail = 0;
  await processQueue(targets, async ([cacheKey, coord]) => {
    const result = await nearestSubway(coord.lat, coord.lon);
    await sleep(DELAY_MS);
    if (quotaExhausted) return;
    if (result) {
      await saveTransit(cacheKey, result.distM, result.stationName);
      success++;
    } else {
      // 반경 내 역이 없다는 것도 유의미한 결과 - null로 저장해서 "먼 거리"로 구분
      await saveTransit(cacheKey, null, null);
      none++;
    }
  }, CONCURRENCY);
  if (quotaExhausted) {
    console.log(`\n⏸️  할당량 소진으로 중단. 성공(역 발견) ${success}건 / 역없음(반경밖) ${none}건 / 실패 ${fail}건`);
  } else {
    console.log(`\n🎉 완료! 역 발견 ${success}건 / 반경 밖(${SEARCH_RADIUS_M}m) ${none}건 / 실패 ${fail}건`);
    console.log(`   남은 미처리: ${coords.size - existing.size - targets.length}개 (다음 실행에서 이어서 처리)`);
  }
}
main().catch(e => { console.error('❌ 치명적 오류:', e); process.exit(1); });
