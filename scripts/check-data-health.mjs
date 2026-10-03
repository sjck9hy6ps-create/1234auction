// ════════════════════════════════════════════════════════════
// 데이터 자동 점검 + 자동 복구 (매주 화요일 - 월요일 주간 수집 직후)
//
// 왜 필요한가 (2026-10 실제 사고):
//   행정구역 개편(전남광주 통합, 강원·전북 특별자치도, 인천 구 개편, 화성 분구)으로 국토부
//   지역코드가 바뀌었는데 수집 코드 목록이 옛 코드에 머물러 있어서, 오류 메시지 하나 없이
//   해당 지역 거래가 몇 달씩 0건으로 수집되고 있었음. 또 경북·경남 일부 군은 코드가 한 칸씩
//   밀려 다른 군 이름으로 저장되고 있었음. 둘 다 "에러 없이 조용히" 틀어지는 문제라 사람이
//   눈치채기 어려움 → 매주 자동으로 점검함.
//
// 점검 1) 거래 건수 급감: 아파트 매매/연립다세대 매매/아파트 전월세 각각, 지역별로
//         2개월 전(신고 기한 30일이 지나 거의 다 들어온 달) 건수를 그 앞 6개월 월평균과 비교.
//         - 월평균 5건 이상이던 지역이 0건, 또는 월평균 20건 이상이던 지역이 평균의 30% 미만
//         → (2026-10 사용자 요청 "이메일을 안 봐도 고쳐지게") 그 지역의 그 달과 지난달을 그 자리에서
//           다시 수집(재수집)하고 건수를 다시 셈. 회복되면 "자동 복구됨"으로 기록.
// 점검 2) 지역코드 검증: 코드 목록의 지역명을 카카오 주소검색에 넣어 나오는 실제 법정동코드와
//         비교 - 행정구역 개편으로 코드가 바뀌거나 목록이 밀리면 바로 잡힘. 이건 자동으로 고치면
//         다른 지역 데이터가 섞일 위험이 있어 고치지 않고 "확인 필요"로 남김.
// 점검 3) 읍·면 위치 검증: 최근 3개월 거래의 "지역 이름 + 읍·면"이 실제로 그 지역에 있는지 카카오로
//         확인 - 코드가 맞아도 옆 지역 거래가 섞여 들어온 경우(2026-10 양평→여주 등)를 잡음. 자동 수정 안 함.
//
// 결과는 public/data-health.json에 쉬운 말로 저장(워크플로가 커밋 → 앱 상단 배너가 읽음).
// 자동 복구 못 한 문제가 남으면 작업을 "실패"로 끝내 GitHub 메일 알림도 함께 감.
// ════════════════════════════════════════════════════════════
import fs from 'fs';
import { supabase, LAWD_CODES, fetchMonth, upsertBatch, sleep, DELAY_MS } from './shared.mjs';
import { LAWD_CODES as VILLA_CODES, fetchMonthVilla, upsertVilla } from './shared-villa.mjs';
import { fetchMonthRent, upsertRent } from './shared-rent.mjs';

const KAKAO_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const CONCURRENCY = 6;
const AUTO_FIX_MAX_REGIONS = 40; // 한 번에 재수집할 최대 지역 수(국토부 일일 할당량 보호)

function ymAdd(y, m, delta) {
  const d = new Date(y, m - 1 + delta, 1);
  return { y: d.getFullYear(), m: d.getMonth() + 1 };
}
const toInt = ({ y, m }) => y * 10000 + m * 100 + 1;
const label = ({ y, m }) => `${y}년 ${m}월`;
const ymStr = ({ y, m }) => `${y}${String(m).padStart(2, '0')}`;

const now = new Date();
const cur = { y: now.getFullYear(), m: now.getMonth() + 1 };
const recent = ymAdd(cur.y, cur.m, -2);      // 신고가 거의 끝난 달
const recentEnd = ymAdd(cur.y, cur.m, -1);
const baseStart = ymAdd(cur.y, cur.m, -8);   // 그 앞 6개월
const baseEnd = recent;

const TABLES = [
  { table: 'house_trades', name: '아파트 매매', codes: LAWD_CODES, fetch: fetchMonth, upsert: upsertBatch },
  { table: 'villa_trades', name: '빌라(연립다세대) 매매', codes: VILLA_CODES, fetch: fetchMonthVilla, upsert: upsertVilla },
  { table: 'house_rent', name: '아파트 전월세', codes: LAWD_CODES, fetch: fetchMonthRent, upsert: upsertRent },
];

async function countRows(table, region, from, to) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const { count, error } = await supabase.from(table).select('id', { count: 'exact', head: true })
      .eq('region', region).gte('deal_date', from).lt('deal_date', to);
    if (!error) return count || 0;
    await sleep(2000 * attempt);
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

const isProblem = (recentCnt, baseAvg) =>
  (baseAvg >= 5 && recentCnt === 0) || (baseAvg >= 20 && recentCnt < baseAvg * 0.3);

const regions = [...new Set(LAWD_CODES.map(r => r.name))];
const fixed = [];      // 자동 복구된 문제
const attention = [];  // 사람이 확인해야 하는 문제
const notes = [];      // 국토부 원본도 같은 건수 = 수집 문제가 아니라 실제로 거래가 줄어든 것(참고용)
const lines = [];
let fixBudget = AUTO_FIX_MAX_REGIONS;

console.log(`📊 거래 건수 점검: ${label(recent)} vs 그 앞 6개월 월평균 (${regions.length}개 지역)`);
for (const t of TABLES) {
  const res = await pool(regions, async (region) => {
    const recentCnt = await countRows(t.table, region, toInt(recent), toInt(recentEnd));
    const baseCnt = await countRows(t.table, region, toInt(baseStart), toInt(baseEnd));
    return { region, recentCnt, baseAvg: baseCnt === null ? null : baseCnt / 6 };
  });
  let flagged = 0, fixedHere = 0;
  for (const r of res) {
    if (r.recentCnt === null || r.baseAvg === null) {
      attention.push(`${t.name} · ${r.region}: 데이터 조회 자체가 실패했어요`); flagged++; continue;
    }
    if (!isProblem(r.recentCnt, r.baseAvg)) continue;
    flagged++;
    const before = r.recentCnt;
    const desc = `${t.name} · ${r.region} · ${label(recent)}: ${before}건 (평소 월 ${Math.round(r.baseAvg)}건)`;
    if (fixBudget <= 0) { attention.push(desc + ' - 자동 재수집 한도를 넘어 다음 점검으로 미룸'); continue; }
    fixBudget--;
    // ── 자동 복구: 그 지역의 모든 코드로 문제 달 + 지난달을 다시 수집 ──
    const codes = t.codes.filter(c => c.name === r.region);
    let sourceCnt = 0, fetchErr = false; // 국토부 원본에서 문제 달에 받아온 건수
    for (const ym of [ymStr(recent), ymStr(recentEnd)]) {
      for (const { code, name } of codes) {
        try {
          const rows = await t.fetch(code, name, ym);
          if (ym === ymStr(recent)) sourceCnt += (rows || []).filter(x => x.deal_date >= toInt(recent) && x.deal_date < toInt(recentEnd)).length;
          if (rows && rows.length) await t.upsert(rows);
        } catch (e) { fetchErr = true; console.error(`재수집 실패 ${t.table} ${name} ${ym}: ${e.message}`); }
        await sleep(DELAY_MS);
      }
    }
    const after = await countRows(t.table, r.region, toInt(recent), toInt(recentEnd));
    if (after !== null && !isProblem(after, r.baseAvg)) {
      fixed.push(`${desc} → 다시 수집해서 ${after}건으로 복구`); fixedHere++;
    } else if (!fetchErr && after !== null && after >= sourceCnt * 0.9 && (after > 0 || r.baseAvg < 20)) {
      // 국토부 원본에도 이만큼밖에 없음 → 수집은 정상, 실제 거래가 줄어든 것(지역코드 검증은 점검 2에서 따로 함)
      notes.push(`${desc} → 국토부 원본도 ${sourceCnt}건이라 수집 문제는 아니에요(실제로 거래가 줄었어요)`); fixedHere++;
    } else {
      attention.push(`${desc} → 다시 수집해도 ${after ?? '?'}건이에요. 지역코드가 바뀌었거나 실제로 거래가 줄었을 수 있어요`);
    }
  }
  const msg = `${t.name}: ${res.length}개 지역 중 이상 ${flagged}곳 (자동 복구 ${fixedHere}곳)`;
  console.log((flagged > fixedHere ? '❌ ' : '✅ ') + msg);
  lines.push(`- ${flagged > fixedHere ? '❌' : '✅'} ${msg}`);
}

// ── 점검 2: 지역코드 검증(카카오 주소검색) - 자동으로 고치지 않음 ──
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
  lines.push('- ⏭️ 지역코드 검증: 카카오 키 없음(건너뜀)');
} else {
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
    if (!r.actual) { attention.push(`지역코드 · ${r.name}: 지도에서 이 지역 주소를 못 찾았어요(지역 이름이 바뀌었을 수 있어요)`); bad++; }
    else if (r.actual !== r.code) { attention.push(`지역코드 · ${r.name}: 목록엔 ${r.code}, 실제는 ${r.actual} - 행정구역 개편 등으로 코드가 바뀐 것 같아요(수집 코드 목록 수정 필요)`); bad++; }
  }
  const msg = `지역코드 검증: ${targets.length}개 중 불일치 ${bad}곳`;
  console.log((bad ? '❌ ' : '✅ ') + msg);
  lines.push(`- ${bad ? '❌' : '✅'} ${msg}`);

  // ── 점검 3: 읍·면이 엉뚱한 지역 이름 아래 저장됐는지 (2026-10-03 추가) ──
  // 2026-10 실제 사고: 지역코드 목록은 맞는데도 2025~2026 빌라 거래 일부가 옆 지역 이름으로 저장돼
  // 있었음(양평군 → '경기 여주시', 연천군 → '경기 양주시', 가평군 → '경기 포천시') - 이름이 틀리니
  // 지도에서 위치를 못 찾아 배지가 안 떴고, 원인은 끝내 못 찾음. 그래서 최근 3개월 거래의
  // "지역 이름 + 읍·면"을 카카오 주소검색에 넣어, 그 읍·면이 실제로 그 지역에 있는지 확인함.
  // (같은 이름 읍·면이 여러 지역에 있는 경우 - 예: 양주 남면/가평 북면 - 도 지역 이름까지 넣어
  //  검색하므로 정상이면 그대로 통과함.) 잘못 옮기면 다른 지역 데이터가 섞이므로 자동으로
  //  고치지 않고 "확인 필요"로 남김(고칠 땐 sql/fix-gyeonggi-villa-region-labels.sql 방식).
  const emFrom = toInt(ymAdd(cur.y, cur.m, -3));
  const pairs = new Map(); // "region|읍면" → { region, em, tables:Set, cnt }
  for (const t of TABLES) {
    await pool(regions, async (region) => {
      for (let from = 0; ; from += 1000) {
        const { data, error } = await supabase.from(t.table).select('dong')
          .eq('region', region).gte('deal_date', emFrom)
          .or('dong.like.*읍 *,dong.like.*면 *').range(from, from + 999);
        if (error || !data) break;
        for (const { dong } of data) {
          const em = String(dong || '').trim().split(/\s+/)[0];
          if (!/[읍면]$/.test(em)) continue;
          const k = region + '|' + em;
          if (!pairs.has(k)) pairs.set(k, { region, em, tables: new Set(), cnt: 0 });
          const p = pairs.get(k); p.tables.add(t.name); p.cnt++;
        }
        if (data.length < 1000) break;
      }
    });
  }
  const pairList = [...pairs.values()].filter(p => p.region !== '세종특별자치시');
  const emRes = await pool(pairList, async (p) => {
    const sigungu = fullName(p.region).split(' ').slice(1); // 예: ['여주시'] / ['수원시','장안구']
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const url = `https://dapi.kakao.com/v2/local/search/address.json?query=${encodeURIComponent(fullName(p.region) + ' ' + p.em)}`;
        const j = await (await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO_KEY}` } })).json();
        if (!j.documents) continue; // 카카오 오류 → 재시도
        const ok = j.documents.some(d => {
          const a = (d.address && d.address.address_name) || d.address_name || '';
          // 읍·면 이름 자체는 비교하지 않음 - 면→읍 승격(예: 달성군 구지면 → 구지읍, 2026-10 확인)처럼
          // 국토부는 옛 이름, 카카오는 새 이름을 주는 경우가 있어서. 카카오가 그 읍·면을 "이 지역 안"에서
          // 찾았는지만 봄(양평읍을 '경기 여주시'로 넣으면 양평군 결과만 나와 여기서 걸림).
          return sigungu.every(s => a.includes(s));
        });
        return { ...p, ok, checked: true };
      } catch (e) { await sleep(1000); }
    }
    return { ...p, ok: true, checked: false }; // 확인 못 하면 넘어감(다음 주에 다시 봄)
  });
  const misplaced = emRes.filter(r => !r.ok);
  for (const r of misplaced) {
    attention.push(`지역 이름 섞임 · ${r.region}: '${r.em}'은(는) 이 지역에 없는 읍·면인데 최근 거래 ${r.cnt}건(${[...r.tables].join(', ')})이 이 이름으로 저장돼 있어요(옆 지역 거래가 잘못 들어온 것 같아요 - 지도 배지·시세가 틀어질 수 있어요)`);
  }
  const unchecked = emRes.filter(r => !r.checked).length;
  const emMsg = `읍·면 위치 검증(최근 3개월): ${pairList.length}개 중 다른 지역 섞임 ${misplaced.length}곳` + (unchecked ? ` (확인 못 함 ${unchecked}곳)` : '');
  console.log((misplaced.length ? '❌ ' : '✅ ') + emMsg);
  lines.push(`- ${misplaced.length ? '❌' : '✅'} ${emMsg}`);
}

// ── 결과 저장(앱 배너용) + 요약 ──
const status = attention.length ? 'attention' : (fixed.length ? 'fixed' : 'ok');
const result = { checkedAt: now.toISOString(), checkedMonth: label(recent), status, fixed, attention, notes };
fs.mkdirSync('public', { recursive: true });
fs.writeFileSync('public/data-health.json', JSON.stringify(result, null, 2));

const summary = [`## 데이터 자동 점검 (${now.toISOString().slice(0, 10)})`, '', ...lines, '',
  fixed.length ? '### 자동으로 복구한 것' : '', ...fixed.map(p => `- ✅ ${p}`), '',
  notes.length ? '### 참고: 실제로 거래가 줄어든 곳(수집은 정상)' : '', ...notes.map(p => `- ℹ️ ${p}`), '',
  attention.length ? '### 확인이 필요한 것' : '문제 없음 ✅', ...attention.map(p => `- ⚠️ ${p}`)].join('\n');
console.log('\n' + summary);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + '\n');
if (attention.length) {
  console.error(`\n❌ 자동으로 복구하지 못한 문제 ${attention.length}건 - 위 목록을 확인하세요.`);
  process.exit(1);
}
