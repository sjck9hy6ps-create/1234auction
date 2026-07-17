/* ════════════════════════════════════════════════════════════
   국토교통부 실거래가 공개시스템(rt.molit.go.kr) CSV 일괄 임포트 스크립트
   ────────────────────────────────────────────────────────────
   목적: 과거 이력을 API 반복 호출로 긁어오는 대신, rt.molit.go.kr에서
   지역 전체/기간 지정해서 직접 다운로드한 CSV 파일을 그대로 DB에 넣는다.
   → 무료 API 쿼터/서버 타임아웃과 무관하게 로컬에서 한 번에 처리 가능.

   사용법:
     node scripts/import-molit-csv.mjs "<CSV파일경로>" --dry-run   (먼저 이걸로 확인)
     node scripts/import-molit-csv.mjs "<CSV파일경로>"             (실제 저장)

   지원 파일 (rt.molit.go.kr 기본 다운로드 파일명을 그대로 쓰면 자동 인식):
     아파트(매매)_실거래가_*.csv       → house_trades
     아파트(전월세)_실거래가_*.csv     → house_rent
     연립다세대(매매)_실거래가_*.csv   → villa_trades
     연립다세대(전월세)_실거래가_*.csv → villa_rent
     단독다가구(매매)_실거래가_*.csv   → single_trades
     단독다가구(전월세)_실거래가_*.csv → single_rent

   필요 패키지: npm install iconv-lite   (rt.molit CSV가 CP949/EUC-KR 인코딩이라 필요)

   주의:
   - 단독다가구는 CSV에 전용면적/층/단지명이 없음. size에는 연면적(매매)
     또는 계약면적(전월세)을 넣고, floor/danji는 비워둠. 대지면적(매매)은
     현재 테이블에 컬럼이 없어서 저장하지 않음 - 필요하면 알려줘.
   - 단독다가구는 번지가 "1***"처럼 마스킹돼 있어서 본번/부번은 항상 null.
   - "시군구" 텍스트를 shared.mjs의 LAWD_CODES와 매칭해서 region/dong을
     만드는데, 목록에 없는 지역(예: 최근 신설/개편된 구)은 건너뛰고
     끝에 "매칭 실패 지역" 목록으로 알려줌 - 나오면 알려주면 LAWD_CODES에
     추가해줄게.
════════════════════════════════════════════════════════════ */
import fs from 'fs';
import iconv from 'iconv-lite';
import { supabase, LAWD_CODES } from './shared.mjs';

const UPSERT_BATCH_SIZE = 500;

// ── CLI 인자 ──
const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const filePath = args.find(a => !a.startsWith('--'));
if (!filePath) {
  console.error('사용법: node scripts/import-molit-csv.mjs "<CSV파일경로>" [--dry-run]');
  process.exit(1);
}

// ── 테이블 자동 판단 (파일명 기반) ──
function detectTable(path) {
  const isApt = path.includes('아파트');
  const isVilla = path.includes('연립다세대');
  const isSingle = path.includes('단독다가구');
  const isSale = path.includes('매매');
  const isRent = path.includes('전월세');
  if (!isSale && !isRent) throw new Error('파일명에 "매매" 또는 "전월세"가 없어서 종류를 판단 못 함');
  if (isApt) return isSale ? 'house_trades' : 'house_rent';
  if (isVilla) return isSale ? 'villa_trades' : 'villa_rent';
  if (isSingle) return isSale ? 'single_trades' : 'single_rent';
  throw new Error('파일명에 "아파트"/"연립다세대"/"단독다가구"가 없어서 종류를 판단 못 함');
}

// ── 지역명 매칭 (raw "시도+시군구+동" → LAWD_CODES의 region/dong) ──
const PROVINCE_PREFIXES = {
  '서울': ['서울특별시'], '부산': ['부산광역시'], '대구': ['대구광역시'], '인천': ['인천광역시'],
  '광주': ['광주광역시'], '대전': ['대전광역시'], '울산': ['울산광역시'], '세종': ['세종특별자치시'],
  '경기': ['경기도'], '강원': ['강원특별자치도', '강원도'], '충북': ['충청북도'], '충남': ['충청남도'],
  '전북': ['전북특별자치도', '전라북도'], '전남': ['전라남도'], '경북': ['경상북도'], '경남': ['경상남도'],
  '제주': ['제주특별자치도'],
  '전남광주': ['전남광주통합특별시'], // 2026-07-01 전남+광주 행정통합
};

function buildPrefixCandidates(entry) {
  const [provinceShort, ...restParts] = entry.name.split(' ');
  const provinceFulls = PROVINCE_PREFIXES[provinceShort] || [provinceShort];
  const rest = restParts.join(' ');
  const candidates = [];
  for (const pf of provinceFulls) {
    if (entry.name === '세종특별자치시') {
      candidates.push(pf);
    } else if (rest.includes(' ')) {
      const [city, gu] = rest.split(' '); // 압축형: "고양 덕양구" → "고양시 덕양구"
      candidates.push(`${pf} ${city}시 ${gu}`);
    } else {
      candidates.push(`${pf} ${rest}`); // "가평군" / "의정부시" / "종로구" 등 그대로
    }
  }
  return candidates;
}

const REGION_INDEX = LAWD_CODES
  .map(entry => ({ entry, prefixes: buildPrefixCandidates(entry) }))
  .sort((a, b) => Math.max(...b.prefixes.map(p => p.length)) - Math.max(...a.prefixes.map(p => p.length)));

const unmatchedRegions = new Map(); // rawSigungu → count

function matchRegion(rawSigungu) {
  const s = rawSigungu.replace(/\s+/g, ' ').trim();
  for (const { entry, prefixes } of REGION_INDEX) {
    for (const p of prefixes) {
      if (s === p) return { region: entry.name, dong: '' };
      if (s.startsWith(p + ' ')) return { region: entry.name, dong: s.slice(p.length + 1).trim() };
    }
  }
  unmatchedRegions.set(rawSigungu, (unmatchedRegions.get(rawSigungu) || 0) + 1);
  return null;
}

// ── CSV 파싱 (국토부 CSV는 모든 필드가 큰따옴표로 감싸져 있어서 이 방식이 안전함) ──
function parseCsvLine(line) {
  let s = line.trim();
  if (s.startsWith('"')) s = s.slice(1);
  if (s.endsWith('"')) s = s.slice(0, -1);
  return s.split('","');
}

function loadRows(path) {
  const buf = fs.readFileSync(path);
  const text = iconv.decode(buf, 'cp949');
  const lines = text.split(/\r\n|\r|\n/).filter(l => l.trim() !== '');
  const headerIdx = lines.findIndex(l => l.startsWith('"NO","시군구"'));
  if (headerIdx === -1) throw new Error('헤더 행("NO","시군구",...)을 못 찾음 - rt.molit.go.kr CSV 형식이 맞는지 확인해줘');
  const headerCols = parseCsvLine(lines[headerIdx]);
  return lines.slice(headerIdx + 1).map(line => {
    const cols = parseCsvLine(line);
    const row = {};
    headerCols.forEach((h, i) => { row[h] = cols[i] !== undefined ? cols[i] : ''; });
    return row;
  });
}

// ── 값 정규화 헬퍼 ──
function toInt(v) {
  if (v === undefined || v === null) return null;
  const s = String(v).replace(/,/g, '').trim();
  if (s === '' || s === '-') return null;
  const n = parseInt(s, 10);
  return Number.isNaN(n) ? null : n;
}
function toIntOrZero(v) {
  const n = toInt(v);
  return n === null ? 0 : n;
}
function toFloorInt(v) {
  if (v === undefined || v === null) return null;
  const s = String(v).replace(/,/g, '').trim();
  if (s === '') return null;
  const n = parseFloat(s);
  return Number.isFinite(n) ? Math.floor(n) : null;
}
function buildDealDate(row) {
  const ym = row['계약년월'];
  const d = (row['계약일'] || '').padStart(2, '0');
  const n = parseInt(`${ym}${d}`, 10);
  return Number.isFinite(n) ? n : null;
}
function bunjiFields(rawBunji) {
  const bunji = (!rawBunji || rawBunji === '-') ? '' : rawBunji;
  if (!rawBunji || rawBunji === '-' || rawBunji.includes('*')) {
    return { bunji, main_num: null, sub_num: null }; // 마스킹된 번지("1***")는 숫자로 못 뽑음
  }
  const parts = rawBunji.split('-');
  const m1 = parseInt(parts[0], 10);
  const m2 = parts[1] !== undefined ? parseInt(parts[1], 10) : null;
  return {
    bunji,
    main_num: Number.isNaN(m1) ? null : m1,
    sub_num: (m2 === null || Number.isNaN(m2) || m2 === 0) ? null : m2,
  };
}

// ── 테이블별 row 빌더 ──
const BUILDERS = {
  house_trades: (row, m) => ({
    region: m.region, dong: m.dong, danji: row['단지명'] || '',
    size: toFloorInt(row['전용면적(㎡)']), price: toIntOrZero(row['거래금액(만원)']),
    deal_date: buildDealDate(row), floor: toInt(row['층']),
    ...bunjiFields(row['번지']), build_year: toInt(row['건축년도']), road_name: row['도로명'] || '',
  }),
  house_rent: (row, m) => ({
    region: m.region, dong: m.dong, danji: row['단지명'] || '',
    size: toFloorInt(row['전용면적(㎡)']), deposit: toIntOrZero(row['보증금(만원)']),
    monthly_rent: toIntOrZero(row['월세금(만원)']), deal_date: buildDealDate(row), floor: toInt(row['층']),
    ...bunjiFields(row['번지']), build_year: toInt(row['건축년도']), road_name: row['도로명'] || '',
    contract_type: row['계약구분'] || '',
  }),
  villa_trades: (row, m) => ({
    region: m.region, dong: m.dong, danji: row['건물명'] || '',
    size: toFloorInt(row['전용면적(㎡)']), price: toIntOrZero(row['거래금액(만원)']),
    deal_date: buildDealDate(row), floor: toInt(row['층']),
    ...bunjiFields(row['번지']), build_year: toInt(row['건축년도']), road_name: row['도로명'] || '',
  }),
  villa_rent: (row, m) => ({
    region: m.region, dong: m.dong, danji: row['건물명'] || '',
    size: toFloorInt(row['전용면적(㎡)']), deposit: toIntOrZero(row['보증금(만원)']),
    monthly_rent: toIntOrZero(row['월세금(만원)']), deal_date: buildDealDate(row), floor: toInt(row['층']),
    ...bunjiFields(row['번지']), build_year: toInt(row['건축년도']), road_name: row['도로명'] || '',
    contract_type: row['계약구분'] || '', house_type: row['주택유형'] || '',
  }),
  single_trades: (row, m) => ({
    region: m.region, dong: m.dong, danji: '',
    size: toFloorInt(row['연면적(㎡)']), price: toIntOrZero(row['거래금액(만원)']),
    deal_date: buildDealDate(row), floor: null,
    ...bunjiFields(row['번지']), build_year: toInt(row['건축년도']), road_name: row['도로명'] || '',
  }),
  single_rent: (row, m) => ({
    region: m.region, dong: m.dong, danji: '',
    size: toFloorInt(row['계약면적(㎡)']), deposit: toIntOrZero(row['보증금(만원)']),
    monthly_rent: toIntOrZero(row['월세금(만원)']), deal_date: buildDealDate(row), floor: null,
    ...bunjiFields(row['번지']), build_year: toInt(row['건축년도']), road_name: row['도로명'] || '',
    contract_type: row['계약구분'] || '', house_type: row['주택유형'] || '',
  }),
};

async function upsertBatch(tableName, rows) {
  if (!rows.length) return 0;
  const uniqueRows = Array.from(
    new Map(rows.map(r => [`${r.region}_${r.dong}_${r.danji}_${r.size}_${r.floor}_${r.deal_date}`, r])).values()
  );
  let success = 0;
  for (let i = 0; i < uniqueRows.length; i += UPSERT_BATCH_SIZE) {
    const chunk = uniqueRows.slice(i, i + UPSERT_BATCH_SIZE);
    const { error } = await supabase.from(tableName).upsert(chunk, {
      onConflict: 'region,dong,danji,size,floor,deal_date',
    });
    if (error) {
      console.error(`❌ ${tableName} upsert 에러 (${i + 1}~${i + chunk.length}행):`, error.message);
    } else {
      success += chunk.length;
    }
  }
  return success;
}

// ── 메인 ──
async function main() {
  const table = detectTable(filePath);
  const builder = BUILDERS[table];
  console.log(`\n📂 파일: ${filePath}`);
  console.log(`📋 대상 테이블: ${table}${dryRun ? ' (dry-run: 실제 저장 안 함)' : ''}\n`);

  const rawRows = loadRows(filePath);
  console.log(`총 ${rawRows.length}개 행 발견`);

  const builtRows = [];
  let skippedByRegion = 0;
  rawRows.forEach((row, i) => {
    const matched = matchRegion(row['시군구']);
    if (!matched) { skippedByRegion++; return; }
    builtRows.push(builder(row, matched));
    if ((i + 1) % 10000 === 0) console.log(`   ...${i + 1}개 처리`);
  });

  console.log(`\n파싱 완료: ${builtRows.length}개 (지역 매칭 실패로 제외 ${skippedByRegion}개)`);

  if (unmatchedRegions.size > 0) {
    console.log(`\n⚠️  매칭 실패 지역 (${unmatchedRegions.size}종류, LAWD_CODES에 없음):`);
    [...unmatchedRegions.entries()].slice(0, 20).forEach(([r, c]) => console.log(`   "${r}" - ${c}건`));
  }

  if (dryRun) {
    console.log('\n🔍 dry-run 샘플 (앞 5개):');
    builtRows.slice(0, 5).forEach(r => console.log('  ', JSON.stringify(r)));
    console.log('\n결과 확인 후 문제 없으면 --dry-run 빼고 다시 실행해줘.');
    return;
  }

  console.log('\n💾 저장 시작...');
  const saved = await upsertBatch(table, builtRows);
  console.log(`\n🎉 완료! ${table}에 ${saved}/${builtRows.length}건 저장됨`);
}

main().catch(e => { console.error('💥 실패:', e.message); process.exit(1); });
