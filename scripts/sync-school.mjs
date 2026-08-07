/* ════════════════════════════════════
   학군(초/중/고 밀집도) 동기화 스크립트 - 2026-08 추가 (역세권/학군 연동 1단계)
   ⚠️ 실제 학업성취도·진학률 같은 "성적" 데이터는 조사해봤지만 공개 API가 없음
   (학교알리미 OpenAPI 제공목록에 학업성취도/진학현황 항목 자체가 없고, 3년 이전
   자료나 특수 통계는 EDSS(에듀데이터서비스)에 별도 신청·심사를 거쳐야 함 - 자동화
   불가). 그래서 "이 법정동에 초등학교/중학교가 몇 개 있는가"를 학군의 근사 지표로
   사용함(초품아/학군 밀집도 프록시 - 실제 학업성취도가 아닌 것에 유의).

   2단계 구성:
   [Phase A] NEIS 교육정보개방포털 학교기본정보 API(open.neis.go.kr)를 페이지 단위로
     순회하며 초/중/고 학교 목록(이름·주소)만 저렴하게 수집 → school_info에 골격
     행으로 저장(lat/lon/region/dong은 아직 비워둠). 전국 초중고가 약 2만개 수준이라
     보통 1회 실행으로 목록 수집이 끝남.
   [Phase B] school_info에서 아직 좌표가 없는(geocode 안 된) 행만, 저장해둔 도로명
     주소로 카카오 REST 지오코딩(주소 검색) → 좌표+법정동코드 조회 → LAWD_CODES로
     region/dong 텍스트 채움. 카카오 API 일일 호출량을 warmup-locations.mjs,
     sync-transit.mjs와 같은 앱(키)로 나눠 쓰므로 실행당 상한을 둠(며칠~몇 주에
     걸쳐 이어서 처리됨 - K-apt 동기화와 같은 패턴).

   ⚠️ 신규 Secret 필요: NEIS_API_KEY (open.neis.go.kr/hub/schoolInfo 페이지에서
   "Open API란 > 인증키 신청"으로 무료 발급, 승인 즉시 사용 가능). GitHub 저장소
   Settings → Secrets and variables → Actions에 추가해야 함. 카카오 키는
   KAKAO_REST_API_KEY(기존 키 재사용, 새로 만들 필요 없음).
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import { LAWD_CODES } from './scripts/lawd-codes.mjs';

const supabase = createClient(
  process.env.SUPABASE_URL?.trim(),
  process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(),
  { auth: { persistSession: false }, realtime: { transport: ws } }
);
const NEIS_API_KEY = process.env.NEIS_API_KEY?.trim();
const KAKAO_REST_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const PAGE_SIZE_NEIS = 1000;
const MAX_NEIS_PAGES_PER_RUN = 25; // 전국 초중고 약 2만개 → 25페이지(2.5만건)면 통상 1회에 끝남
const MAX_GEOCODE_PER_RUN = parseInt(process.env.MAX_SCHOOL_GEOCODE_PER_RUN || '1500', 10);
const GEOCODE_DELAY_MS = 250;
const PAGE_SIZE_SB = 1000;
const VALID_TYPES = new Set(['초등학교', '중학교', '고등학교']);
const CODE_TO_REGION = new Map(LAWD_CODES.map(r => [r.code, r.name]));
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ── NEIS 학교기본정보 목록 조회 ── */
async function fetchNeisPage(pIndex) {
  const url = `https://open.neis.go.kr/hub/schoolInfo?KEY=${encodeURIComponent(NEIS_API_KEY)}`
    + `&Type=json&pIndex=${pIndex}&pSize=${PAGE_SIZE_NEIS}`;
  let res;
  try {
    res = await fetch(url, { signal: AbortSignal.timeout(20000) });
  } catch (e) {
    console.error(`❌ NEIS API 네트워크 오류(page ${pIndex}):`, e.message);
    return { rows: [], done: true };
  }
  if (!res.ok) {
    console.error(`❌ NEIS API 실패(page ${pIndex}) - status:${res.status}`);
    return { rows: [], done: true };
  }
  let json;
  try { json = await res.json(); } catch (e) { return { rows: [], done: true }; }
  const block = json?.schoolInfo;
  if (!Array.isArray(block) || block.length < 2) {
    // INFO-200(데이터 없음) 등 - 목록 끝에 도달
    const code = json?.RESULT?.CODE || json?.schoolInfo?.[0]?.head?.find?.(h => h.RESULT)?.RESULT?.CODE;
    if (pIndex === 1 && !code) {
      console.error(`  [디버그] NEIS 응답 예상과 다름: ${JSON.stringify(json).slice(0, 500)}`);
    }
    return { rows: [], done: true };
  }
  const rows = block[1]?.row || [];
  return { rows, done: rows.length < PAGE_SIZE_NEIS };
}
/* ── Phase A: 목록 수집(저렴, 카카오 호출 없음) ── */
async function syncSchoolList() {
  const { data: stateRow } = await supabase.from('school_sync_state').select('page_idx').eq('id', 1).maybeSingle();
  let pageIdx = stateRow?.page_idx || 1;
  console.log(`📦 [Phase A] NEIS 학교목록 수집 시작 (page ${pageIdx}부터)`);
  let totalNew = 0, pagesRun = 0, reachedEnd = false;
  for (; pagesRun < MAX_NEIS_PAGES_PER_RUN; pagesRun++, pageIdx++) {
    const { rows, done } = await fetchNeisPage(pageIdx);
    if (rows.length === 0) { reachedEnd = true; break; }
    const filtered = rows.filter(r => VALID_TYPES.has(r.SCHUL_KND_SC_NM));
    if (filtered.length > 0) {
      const upsertRows = filtered.map(r => ({
        school_code: r.SD_SCHUL_CODE,
        school_name: r.SCHUL_NM,
        school_type: r.SCHUL_KND_SC_NM,
        road_addr: r.ORG_RDNMA || null,
      }));
      // school_info에 lat/lon/region/dong이 이미 채워진 행을 덮어쓰지 않도록
      // upsert는 이름/주소만 갱신하고 좌표 컬럼은 건드리지 않음(ignoreDuplicates로
      // PK 충돌 시 스킵 - 이미 목록에 있던 학교는 그대로 둠).
      const { error } = await supabase.from('school_info')
        .upsert(upsertRows, { onConflict: 'school_code', ignoreDuplicates: true });
      if (error) console.error(`❌ school_info 저장 에러(page ${pageIdx}):`, error.message);
      else totalNew += filtered.length;
    }
    console.log(`   page ${pageIdx}: ${rows.length}건 중 초/중/고 ${filtered.length}건`);
    if (done) { reachedEnd = true; pagesRun++; break; }
  }
  const nextPageIdx = reachedEnd ? 1 : pageIdx; // 끝까지 갔으면 다음 실행은 처음부터(연간 갱신 재확인)
  await supabase.from('school_sync_state').upsert({ id: 1, page_idx: nextPageIdx });
  console.log(`   → 이번 실행 ${pagesRun}페이지 처리, 신규/갱신 저장 시도 ${totalNew}건, 다음 시작 page: ${nextPageIdx}${reachedEnd ? ' (목록 끝까지 도달 → 처음으로 리셋)' : ''}\n`);
}
/* ── 카카오 REST: 주소 → 좌표 + 법정동코드 ── */
let consecutive429 = 0;
let quotaExhausted = false;
async function kakaoFetch(url) {
  if (quotaExhausted) return null;
  let res;
  try {
    res = await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO_REST_KEY}` } });
  } catch (e) { return null; }
  if (res.status === 429) {
    consecutive429++;
    if (consecutive429 >= 5) { quotaExhausted = true; console.error('🛑 카카오 API 호출 제한 반복 → 중단'); }
    return null;
  }
  if (res.status === 400) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* ignore */ }
    if (body && (body.code === -10 || /API limit has been exceeded/i.test(body.message || ''))) {
      quotaExhausted = true;
      console.error('🛑 카카오 API 일일 할당량 초과 → 중단');
    }
    return null;
  }
  consecutive429 = 0;
  if (!res.ok) return null;
  try { return await res.json(); } catch (e) { return null; }
}
async function geocodeSchool(addr) {
  const url = `https://dapi.kakao.com/v2/local/search/address.json?query=${encodeURIComponent(addr)}`;
  const json = await kakaoFetch(url);
  const doc = json?.documents?.[0];
  if (!doc) return null;
  const lat = parseFloat(doc.y), lon = parseFloat(doc.x);
  const regionUrl = `https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x=${lon}&y=${lat}`;
  await sleep(GEOCODE_DELAY_MS);
  const regionJson = await kakaoFetch(regionUrl);
  const b = (regionJson?.documents || []).find(d => d.region_type === 'B');
  if (!b || !b.code || b.code.length < 10) return { lat, lon, region: null, dong: null };
  const sigunguCd = b.code.slice(0, 5);
  const region = CODE_TO_REGION.get(sigunguCd) || null;
  const dong = b.region_3depth_name || null;
  return { lat, lon, region, dong };
}
/* ── Phase B: 좌표 없는 행만 지오코딩 ── */
async function geocodeMissing() {
  console.log(`📦 [Phase B] 좌표 없는 학교 지오코딩 시작 (실행당 상한 ${MAX_GEOCODE_PER_RUN}건)`);
  if (!KAKAO_REST_KEY) {
    console.error('❌ KAKAO_REST_API_KEY 없음 - 지오코딩 단계 건너뜀');
    return;
  }
  const { data: targets, error } = await supabase
    .from('school_info')
    .select('school_code,road_addr')
    .is('lat', null)
    .not('road_addr', 'is', null)
    .limit(MAX_GEOCODE_PER_RUN);
  if (error) { console.error('❌ school_info 조회 에러:', error.message); return; }
  console.log(`   → 이번 실행 대상 ${targets.length}건`);
  let success = 0, fail = 0;
  for (const row of targets) {
    if (quotaExhausted) break;
    const result = await geocodeSchool(row.road_addr);
    await sleep(GEOCODE_DELAY_MS);
    if (!result) { fail++; continue; }
    const { error: upErr } = await supabase.from('school_info')
      .update({ lat: result.lat, lon: result.lon, region: result.region, dong: result.dong })
      .eq('school_code', row.school_code);
    if (upErr) console.error('❌ 좌표 저장 에러:', upErr.message);
    else success++;
    if ((success + fail) % 200 === 0) console.log(`   진행: ${success + fail}/${targets.length}`);
  }
  console.log(`\n🎉 [Phase B] 완료! 성공 ${success}건 / 실패 ${fail}건${quotaExhausted ? ' (할당량 소진으로 중단 - 다음 실행에서 이어짐)' : ''}`);
}
async function main() {
  if (!NEIS_API_KEY) {
    console.error('❌ NEIS_API_KEY 환경변수가 없습니다. GitHub 저장소 Secrets에 추가해 주세요.');
    process.exit(1);
  }
  await syncSchoolList();
  await geocodeMissing();
}
main().catch(e => { console.error('❌ 치명적 오류:', e); process.exit(1); });
