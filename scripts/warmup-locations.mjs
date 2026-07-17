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
const BUILDING_DELAY_MS = 300; // 건축물대장만 재시도할 때 호출 간격
const CONCURRENCY = 3;         // 동시 처리 단지 수
const PAGE_SIZE = 1000;        // Supabase 페이지네이션 단위
// 건축물대장(PUBLIC_DATA_API_KEY) 웜업 호출 수 실행당 상한 - 낮 시간 실사용을 위해
// 하루 할당량을 웜업이 혼자 다 쓰지 않도록 남겨둠. 환경변수로 조절 가능.
const MAX_BUILDING_WARMUP_PER_RUN = parseInt(process.env.MAX_BUILDING_WARMUP_PER_RUN || '500', 10);
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
/* ── 이미 캐시된 좌표: cache_key → {lat,lon,sigunguCd,bjdongCd} ── */
async function fetchExistingCoords() {
  const map = new Map();
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from('complex_coords')
      .select('cache_key,lat,lon,sigungu_cd,bjdong_cd')
      .range(from, from + PAGE_SIZE - 1);
    if (error) { console.error('❌ complex_coords 조회 에러:', error.message); break; }
    if (!data || data.length === 0) break;
    data.forEach(r => map.set(r.cache_key, { lat: r.lat, lon: r.lon, sigunguCd: r.sigungu_cd, bjdongCd: r.bjdong_cd }));
    if (data.length < PAGE_SIZE) break;
    from += PAGE_SIZE;
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
  // 건축물대장만 재시도 (좌표는 이미 있으므로 카카오 지오코딩 호출 없이 진행 - 할당량과 무관)
  if (buildingOnlyTargets.length > 0 && buildingWarmupCount < MAX_BUILDING_WARMUP_PER_RUN) {
    console.log(`\n📦 건축물대장 재시도 시작 (좌표는 있지만 아직 건축물대장이 없는 단지, 전체 ${buildingOnlyTargets.length}개 중 이번 실행 남은 한도 ${MAX_BUILDING_WARMUP_PER_RUN - buildingWarmupCount}개까지)...`);
    let bSuccess = 0, bDone = 0;
    for (const [, row] of buildingOnlyTargets) {
      if (buildingWarmupCount >= MAX_BUILDING_WARMUP_PER_RUN) {
        console.log(`   ⏸️  건축물대장 웜업 실행당 상한(${MAX_BUILDING_WARMUP_PER_RUN}건) 도달 → 나머지는 다음 실행으로 넘어갑니다.`);
        break;
      }
      const key = buildCacheKey(row.dong, row.danji, row.bunji, row.road_name, row.main_num, row.sub_num);
      const coord = existingCoords.get(key);
      if (coord && coord.sigunguCd && coord.bjdongCd) {
        await warmBuildingInfo(row, coord.sigunguCd, coord.bjdongCd);
        bSuccess++;
      }
      bDone++;
      await sleep(BUILDING_DELAY_MS);
      if (bDone % 50 === 0) console.log(`   진행: ${bDone}건 처리`);
    }
    console.log(`\n🎉 건축물대장 재시도 이번 실행분 완료! 처리 ${bSuccess}건 (전체 미처리 ${buildingOnlyTargets.length}건 중, 나머지는 다음날 이어서 처리)`);
  } else if (buildingOnlyTargets.length > 0) {
    console.log(`\n⏸️  건축물대장 웜업 실행당 상한(${MAX_BUILDING_WARMUP_PER_RUN}건)에 이미 도달해(신규 좌표 웜업 단계에서 소진) 재시도 단계는 건너뜁니다. 전체 미처리 ${buildingOnlyTargets.length}건은 다음 실행으로 넘어갑니다.`);
  }
}
main().catch(e => { console.error('❌ 치명적 오류:', e); process.exit(1); });
