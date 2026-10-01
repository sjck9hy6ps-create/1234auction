import { LAWD_CODES, sleep, DELAY_MS, fetchMonthVilla, fetchMonthSingle, upsertVilla, upsertSingle } from './shared-villa.mjs';

// ════════════════════════════════════════════════════════════
// 특정 지역(lawdCd)만 지정해서 연립다세대·단독다가구 과거 데이터를 다시
// 백필하는 스크립트입니다.
//
// 왜 필요한가:
//   2026-08 "안산시 상록구(41271) 빌라 매매기록 배지가 안 뜬다" 조사 중,
//   /api/get-house?lawdCd=41271 응답의 buildingType별 건수를 확인해보니
//   apt=1052건인데 villa=0건이었습니다. 이웃한 단원구(41273)는 villa
//   472건, 다른 경기/인천 지역들도 대부분 수백~천 건씩 있는데 상록구만
//   0건 - 실제 거래가 없어서가 아니라 수집이 누락됐을 가능성이 높습니다.
//   (과거 fix-lawd-region-migration.sql에 '경기 안산시 단원구' →
//   '경기 안산시 상록구'로 재라벨링하는 구문이 있었던 것도 상록구/단원구
//   지역명 이력이 한 번 꼬였었다는 정황이라 참고용으로 남겨둡니다.)
//
//   collect-history-villa-single.mjs(=주간 스크립트와 동일 내용, 오해의
//   소지가 있는 파일명)는 전체 267개 지역을 통째로 도는 구조라 특정
//   지역만 다시 채우려고 재실행하면 불필요하게 API 호출량이 커집니다.
//   이 스크립트는 REGION_CODES로 지정한 지역만 돌아서 안전하게 빠르게
//   백필할 수 있게 만들었습니다.
//
// 사용법 (GitHub Actions workflow_dispatch 입력값 또는 환경변수):
//   REGION_CODES = "41271"                (콤마로 여러 개 가능, 기본값 41271)
//   START_YEAR   = "2022"                 (기본값: 올해-4)
//   END_YEAR     = "2026"                 (기본값: 올해)
// ════════════════════════════════════════════════════════════

const now = new Date();
const currentYear  = now.getFullYear();
const currentMonth = now.getMonth() + 1;

const regionCodes = (process.env.REGION_CODES || '41271')
  .split(',')
  .map(s => s.trim())
  .filter(Boolean);

const startYear = parseInt(process.env.START_YEAR || String(currentYear - 4));
const endYear   = parseInt(process.env.END_YEAR   || String(currentYear));

const targetRegions = LAWD_CODES.filter(r => regionCodes.includes(r.code));
if (!targetRegions.length) {
  console.error(`❌ REGION_CODES(${regionCodes.join(',')})와 일치하는 지역을 LAWD_CODES에서 찾지 못했습니다.`);
  process.exit(1);
}

console.log(`\n📅 지역 지정 연립다세대+단독다가구 백필 시작`);
console.log(`대상 지역: ${targetRegions.map(r => `${r.name}(${r.code})`).join(', ')}`);
console.log(`대상 연도: ${startYear} ~ ${endYear}\n`);

// ⚠️ 2026-09(#498): 2026-07-01 인천 구 개편 이전 달은 국토부가 옛 코드(28110 중구/28140 동구/
// 28260 서구)로만 거래를 내려주므로, 새 구 코드(제물포/영종/서해/검단)로 과거 달을 조회하면
// 빈 응답만 옴 - 그래서 수도권 빌라 실측 백테스트에서 이 4개 구가 2024-10~2026-04 통째로 비어
// 있었음. 개편 이전 달은 옛 코드로 조회한 뒤, unify-region-names-migration.sql PART C와 똑같은
// 동(dong) 기준으로 새 구에 나눠 담음(같은 규칙이어야 이미 이관된 기존 행과 중복/충돌이 안 남).
const INCHEON_REORG_YM = '202607';
const YEONGJONG_DONGS = ['중산동', '운남동', '운북동', '운서동', '을왕동', '남북동', '덕교동', '무의동'];
const GEOMDAN_DONGS = ['검단동', '불로대곡동', '원당동', '당하동', '오류왕길동', '마전동', '아라동', '아라1동', '아라2동'];
const INCHEON_LEGACY = {
  '28125': [{ code: '28110', keep: d => !YEONGJONG_DONGS.includes(d) }, { code: '28140', keep: () => true }], // 제물포구
  '28155': [{ code: '28110', keep: d => YEONGJONG_DONGS.includes(d) }],                                     // 영종구
  '28275': [{ code: '28260', keep: d => !GEOMDAN_DONGS.includes(d) }],                                      // 서해구
  '28290': [{ code: '28260', keep: d => GEOMDAN_DONGS.includes(d) }],                                       // 검단구
};
// ⚠️ 2026-10(#498 실행 결과 반영): 실제로 돌려보니 옛 코드(28110/28140/28260)는 모든 달이 0건이었고,
// 이미 DB에 있던 서해구 2025-11~ 데이터는 새 코드로 수집된 것이었음 - 국토부가 과거 거래도 새 구
// 코드로 다시 분류해 둔 것으로 보임. 그래서 새 코드로 먼저 조회하고, 그 결과가 0건일 때만 옛 코드로
// 한 번 더 시도함(혹시 일부 달만 옛 코드에 남아있는 경우 대비).
async function fetchMonthWithLegacy(fetchFn, code, name, ym) {
  const legacy = INCHEON_LEGACY[code];
  const direct = await fetchFn(code, name, ym);
  if (direct.length || !legacy || ym >= INCHEON_REORG_YM) return direct;
  await sleep(DELAY_MS);
  const rows = [];
  for (const src of legacy) {
    const r = await fetchFn(src.code, name, ym); // region 라벨은 새 구 이름(name)으로 붙음
    rows.push(...r.filter(row => src.keep(String(row.dong || '').trim())));
    await sleep(DELAY_MS);
  }
  return rows;
}

let totalVilla  = 0;
let totalSingle = 0;
// 지역별/월별 건수를 따로 기록해서, 실행 로그만 보고도 "그 달에 실거래가 원래 없는 것"인지
// "API 호출 자체가 실패한 것"인지 구분할 수 있게 함.
const perRegionMonthCounts = {};

for (let year = startYear; year <= endYear; year++) {
  const months = year < currentYear
    ? [1,2,3,4,5,6,7,8,9,10,11,12]
    : Array.from({length: currentMonth}, (_, i) => i + 1);

  for (const month of months) {
    const ym = String(year) + String(month).padStart(2, '0');
    const villaRows  = [];
    const singleRows = [];

    for (const { code, name } of targetRegions) {
      const vRows = await fetchMonthWithLegacy(fetchMonthVilla, code, name, ym);
      villaRows.push(...vRows);
      await sleep(DELAY_MS);

      const sRows = await fetchMonthWithLegacy(fetchMonthSingle, code, name, ym);
      singleRows.push(...sRows);
      await sleep(DELAY_MS);

      const key = `${name}(${code})`;
      perRegionMonthCounts[key] = perRegionMonthCounts[key] || {};
      perRegionMonthCounts[key][ym] = { villa: vRows.length, single: sRows.length };

      console.log(`  ${ym} ${key}: 연립다세대 ${vRows.length}건 / 단독다가구 ${sRows.length}건`);
    }

    await upsertVilla(villaRows);
    await upsertSingle(singleRows);

    totalVilla  += villaRows.length;
    totalSingle += singleRows.length;
  }
}

console.log(`\n🎉 백필 완료!`);
console.log(`   연립다세대 총 ${totalVilla}건`);
console.log(`   단독다가구 총 ${totalSingle}건`);

// 월별 건수가 전부 0인 지역이 있으면 - 실거래가 진짜 없는 것일 수도 있지만
// MOLIT API 응답/서비스키 문제일 가능성도 있으니 마지막에 경고로 다시 짚어줌.
for (const [region, months] of Object.entries(perRegionMonthCounts)) {
  const allZero = Object.values(months).every(m => m.villa === 0 && m.single === 0);
  if (allZero) {
    console.warn(`\n⚠️  ${region}: 조회한 전체 기간(${startYear}~${endYear})에 연립다세대·단독다가구 거래가 단 한 건도 없습니다.`);
    console.warn(`    실제로 거래가 없는 지역일 수도 있지만, 서비스키/LAWD_CD 오류로 매번 빈 응답이 왔을 가능성도 있으니`);
    console.warn(`    Actions 로그에서 "연립다세대 실패:" 에러 메시지가 찍혔는지 확인해 주세요.`);
  }
}
