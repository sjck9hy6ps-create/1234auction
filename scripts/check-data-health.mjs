// ════════════════════════════════════════════════════════════
// 데이터 자동 점검 (매주 화요일 - 월요일 주간 수집 직후)
//
// 왜 필요한가 (2026-10 실제 사고):
//   행정구역 개편(전남광주 통합, 강원·전북 특별자치도, 인천 구 개편, 화성 분구)으로 국토부
//   지역코드가 바뀌었는데 수집 코드 목록이 옛 코드에 머물러 있어서, 오류 메시지 하나 없이
//   해당 지역 거래가 몇 달씩 0건으로 수집되고 있었음(광주·강원·전북 2026년 1~4·6~7월 공백).
//   또 경북·경남 일부 군은 코드가 한 칸씩 밀려 다른 군 이름으로 저장되고 있었음.
//   둘 다 "에러 없이 조용히" 틀어지는 문제라 사람이 눈치채기 어려움 → 매주 자동으로 점검함.
//
// 점검 1) 거래 건수 급감: 아파트 매매/연립다세대 매매/아파트 전월세 각각, 지역별로
//         2개월 전(신고 기한 30일이 지나 거의 다 들어온 달) 건수를 그 앞 6개월 월평균과 비교.
//         - 월평균 5건 이상이던 지역이 0건 → 🚨
//         - 월평균 20건 이상이던 지역이 평균의 30% 미만 → ⚠️
// 점검 2) 지역코드 검증: 코드 목록의 지역명을 카카오 주소검색에 넣어 나오는 실제 법정동코드와
//         비교 - 행정구역 개편으로 코드가 바뀌거나 목록이 밀리면 바로 잡힘.
//
// 문제가 하나라도 있으면 이 작업을 "실패"로 끝냄 → GitHub가 저장소 주인에게 메일로 알려줌.
// 결과 표는 Actions 실행 화면의 Summary에도 남김.
// ════════════════════════════════════════════════════════════
import fs from 'fs';
import { supabase, LAWD_CODES } from './shared.mjs';

const KAKAO_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const CONCURRENCY = 6;

function ymAdd(y, m, delta) {
  const d = new Date(y, m - 1 + delta, 1);
  return { y: d.getFullYear(), m: d.getMonth() + 1 };
}
const toInt = ({ y, m }) => y * 10000 + m * 100 + 1;
const label = ({ y, m }) => `${y}-${String(m).padStart(2, '0')}`;

const now = new Date();
const cur = { y: now.getFullYear(), m: now.getMonth() + 1 };
const recent = ymAdd(cur.y, cur.m, -2);      // 신고가 거의 끝난 달
const recentEnd = ymAdd(cur.y, cur.m, -1);
const baseStart = ymAdd(cur.y, cur.m, -8);   // 그 앞 6개월
const baseEnd = recent;

const TABLES = [
  { table: 'house_trades', name: '아파트 매매' },
  { table: 'villa_trades', name: '연립다세대 매매' },
  { table: 'house_rent', name: '아파트 전월세' },
];

async function countRows(table, region, from, to) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const { count, error } = await supabase.from(table).select('id', { count: 'exact', head: true })
      .eq('region', region).gte('deal_date', from).lt('deal_date', to);
    if (!error) return count || 0;
    await new Promise(r => setTimeout(r, 2000 * attempt));
  }
  return null; // 조회 자체 실패
}

async function pool(items, fn) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: CONCURRENCY }, async () => {
    while (i < items.length) { const k = i++; out[k] = await fn(items[k]); }
  }));
  return out;
}

const regions = [...new Set(LAWD_CODES.map(r => r.name))];
const problems = [];
const lines = [];

console.log(`📊 거래 건수 점검: ${label(recent)} vs ${label(baseStart)}~${label(ymAdd(baseEnd.y, baseEnd.m, -1))} 월평균 (${regions.length}개 지역)`);
for (const { table, name } of TABLES) {
  const res = await pool(regions, async (region) => {
    const recentCnt = await countRows(table, region, toInt(recent), toInt(recentEnd));
    const baseCnt = await countRows(table, region, toInt(baseStart), toInt(baseEnd));
    return { region, recentCnt, baseAvg: baseCnt === null ? null : baseCnt / 6 };
  });
  let flagged = 0;
  for (const r of res) {
    if (r.recentCnt === null || r.baseAvg === null) {
      problems.push(`❓ ${name} | ${r.region} | 조회 실패`); flagged++; continue;
    }
    if (r.baseAvg >= 5 && r.recentCnt === 0) {
      problems.push(`🚨 ${name} | ${r.region} | ${label(recent)} 0건 (이전 월평균 ${r.baseAvg.toFixed(0)}건)`); flagged++;
    } else if (r.baseAvg >= 20 && r.recentCnt < r.baseAvg * 0.3) {
      problems.push(`⚠️ ${name} | ${r.region} | ${label(recent)} ${r.recentCnt}건 (이전 월평균 ${r.baseAvg.toFixed(0)}건의 ${Math.round(r.recentCnt / r.baseAvg * 100)}%)`); flagged++;
    }
  }
  const msg = `${name}: ${res.length}개 지역 중 이상 ${flagged}곳`;
  console.log((flagged ? '❌ ' : '✅ ') + msg);
  lines.push(`- ${flagged ? '❌' : '✅'} ${msg}`);
}

// ── 점검 2: 지역코드 검증(카카오 주소검색) ──
const SIDO = { 서울: '서울특별시', 부산: '부산광역시', 대구: '대구광역시', 인천: '인천광역시', 대전: '대전광역시', 울산: '울산광역시',
  경기: '경기도', 강원: '강원특별자치도', 충북: '충청북도', 충남: '충청남도', 전북: '전북특별자치도', 전남광주: '전남광주통합특별시',
  경북: '경상북도', 경남: '경상남도', 제주: '제주특별자치도' };
function fullName(n) {
  const t = n.split(' ');
  if (t.length === 1) return n;
  const rest = t.slice(1);
  if (rest.length === 2 && !/[시군]$/.test(rest[0])) rest[0] += '시';
  return (SIDO[t[0]] || t[0]) + ' ' + rest.join(' ');
}
if (!KAKAO_KEY) {
  console.log('ℹ️ KAKAO_REST_API_KEY가 없어 지역코드 검증은 건너뜀');
  lines.push('- ⏭️ 지역코드 검증: 카카오 키 없음(건너뜀)');
} else {
  // 같은 지역명에 여러 코드가 있는 곳(부천 3개 구, 화성 4개 구 등)은 지역명만으로는 구를 특정할 수
  // 없어 검증 대상에서 뺌. 세종은 카카오가 시도 단위 코드(36000)로 돌려줘 비교 불가라 제외.
  const nameCount = {};
  LAWD_CODES.forEach(r => { nameCount[r.name] = (nameCount[r.name] || 0) + 1; });
  const targets = LAWD_CODES.filter(r => nameCount[r.name] === 1 && r.name !== '세종특별자치시');
  const res = await pool(targets, async (r) => {
    try {
      const url = `https://dapi.kakao.com/v2/local/search/address.json?query=${encodeURIComponent(fullName(r.name))}`;
      const j = await (await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO_KEY}` } })).json();
      const a = j.documents && j.documents[0] && j.documents[0].address;
      return { ...r, actual: a ? String(a.b_code).slice(0, 5) : null };
    } catch (e) { return { ...r, actual: null }; }
  });
  let bad = 0;
  for (const r of res) {
    if (!r.actual) { problems.push(`❓ 지역코드 | ${r.name}(${r.code}) | 카카오에서 주소를 못 찾음`); bad++; }
    else if (r.actual !== r.code) { problems.push(`🚨 지역코드 | ${r.name} | 목록 ${r.code} ≠ 실제 ${r.actual} (scripts/lawd-codes.mjs·shared.mjs·shared-villa.mjs 수정 필요)`); bad++; }
  }
  const msg = `지역코드 검증: ${targets.length}개 중 불일치 ${bad}곳`;
  console.log((bad ? '❌ ' : '✅ ') + msg);
  lines.push(`- ${bad ? '❌' : '✅'} ${msg}`);
}

const summary = [`## 데이터 자동 점검 (${now.toISOString().slice(0, 10)})`, '', ...lines, '',
  problems.length ? '### 발견된 문제' : '문제 없음 ✅', '', ...problems.map(p => `- ${p}`)].join('\n');
console.log('\n' + summary);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + '\n');
if (problems.length) {
  console.error(`\n❌ 문제 ${problems.length}건 발견 - 위 목록을 확인하세요.`);
  process.exit(1);
}
