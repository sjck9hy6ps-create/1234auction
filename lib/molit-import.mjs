/* ════════════════════════════════════════════════════════════
   api/lib/molit-import.mjs
   국토교통부 실거래가 CSV 임포트 공용 로직 (지역 매칭 + 테이블별 row 빌더 + upsert)
   - Codespaces에서 쓰던 scripts/import-molit-csv.mjs 의 핵심 로직을
     서버(Vercel Function)에서도 쓸 수 있도록 옮긴 버전.
   - 파일 읽기/인코딩 변환은 여기서 하지 않음 (브라우저가 이미 파싱해서
     header→value 형태의 row 객체 배열로 보내주기 때문).
   - ⚠️ LAWD_CODES는 scripts/shared.mjs와 내용이 같아야 함(2026-07-01
     행정구역 개편 반영본). 나중에 또 지역코드가 바뀌면 두 파일 다 같이
     고쳐줘야 함 - 잊지 말 것.
════════════════════════════════════════════════════════════ */

export const VALID_TABLES = ['house_trades', 'house_rent', 'villa_trades', 'villa_rent', 'single_trades', 'single_rent'];

export const LAWD_CODES = [
  { code: '11110', name: '서울 종로구' }, { code: '11140', name: '서울 중구' },
  { code: '11170', name: '서울 용산구' }, { code: '11200', name: '서울 성동구' },
  { code: '11215', name: '서울 광진구' }, { code: '11230', name: '서울 동대문구' },
  { code: '11260', name: '서울 중랑구' }, { code: '11290', name: '서울 성북구' },
  { code: '11305', name: '서울 강북구' }, { code: '11320', name: '서울 도봉구' },
  { code: '11350', name: '서울 노원구' }, { code: '11380', name: '서울 은평구' },
  { code: '11410', name: '서울 서대문구' }, { code: '11440', name: '서울 마포구' },
  { code: '11470', name: '서울 양천구' }, { code: '11500', name: '서울 강서구' },
  { code: '11530', name: '서울 구로구' }, { code: '11545', name: '서울 금천구' },
  { code: '11560', name: '서울 영등포구' }, { code: '11590', name: '서울 동작구' },
  { code: '11620', name: '서울 관악구' }, { code: '11650', name: '서울 서초구' },
  { code: '11680', name: '서울 강남구' }, { code: '11710', name: '서울 송파구' },
  { code: '11740', name: '서울 강동구' }, { code: '26110', name: '부산 중구' },
  { code: '26140', name: '부산 서구' }, { code: '26170', name: '부산 동구' },
  { code: '26200', name: '부산 영도구' }, { code: '26230', name: '부산 부산진구' },
  { code: '26260', name: '부산 동래구' }, { code: '26290', name: '부산 남구' },
  { code: '26320', name: '부산 북구' }, { code: '26350', name: '부산 해운대구' },
  { code: '26380', name: '부산 사하구' }, { code: '26410', name: '부산 금정구' },
  { code: '26440', name: '부산 강서구' }, { code: '26470', name: '부산 연제구' },
  { code: '26500', name: '부산 수영구' }, { code: '26530', name: '부산 사상구' },
  { code: '26710', name: '부산 기장군' }, { code: '27110', name: '대구 중구' },
  { code: '27140', name: '대구 동구' }, { code: '27170', name: '대구 서구' },
  { code: '27200', name: '대구 남구' }, { code: '27230', name: '대구 북구' },
  { code: '27260', name: '대구 수성구' }, { code: '27290', name: '대구 달서구' },
  { code: '27710', name: '대구 달성군' }, { code: '27720', name: '대구 군위군' },
  { code: '28125', name: '인천 제물포구' }, { code: '28155', name: '인천 영종구' },
  { code: '28177', name: '인천 미추홀구' }, { code: '28185', name: '인천 연수구' },
  { code: '28200', name: '인천 남동구' }, { code: '28237', name: '인천 부평구' },
  { code: '28245', name: '인천 계양구' }, { code: '28275', name: '인천 서해구' },
  { code: '28290', name: '인천 검단구' }, { code: '28710', name: '인천 강화군' },
  { code: '28720', name: '인천 옹진군' }, { code: '30110', name: '대전 동구' },
  { code: '30140', name: '대전 중구' }, { code: '30170', name: '대전 서구' },
  { code: '30200', name: '대전 유성구' }, { code: '30230', name: '대전 대덕구' },
  { code: '31110', name: '울산 중구' }, { code: '31140', name: '울산 남구' },
  { code: '31170', name: '울산 동구' }, { code: '31200', name: '울산 북구' },
  { code: '31710', name: '울산 울주군' }, { code: '36110', name: '세종특별자치시' },
  { code: '41111', name: '경기 수원 장안구' }, { code: '41113', name: '경기 수원 권선구' },
  { code: '41115', name: '경기 수원 팔달구' }, { code: '41117', name: '경기 수원 영통구' },
  { code: '41131', name: '경기 성남 수정구' }, { code: '41133', name: '경기 성남 중원구' },
  { code: '41135', name: '경기 성남 분당구' }, { code: '41150', name: '경기 의정부시' },
  { code: '41171', name: '경기 안양 만안구' }, { code: '41173', name: '경기 안양 동안구' },
  { code: '41190', name: '경기 부천시' }, { code: '41210', name: '경기 광명시' },
  { code: '41220', name: '경기 평택시' }, { code: '41250', name: '경기 동두천시' },
  { code: '41271', name: '경기 안산 상록구' }, { code: '41273', name: '경기 안산 단원구' },
  { code: '41281', name: '경기 고양 덕양구' }, { code: '41285', name: '경기 고양 일산동구' },
  { code: '41287', name: '경기 고양 일산서구' }, { code: '41290', name: '경기 과천시' },
  { code: '41310', name: '경기 구리시' }, { code: '41360', name: '경기 남양주시' },
  { code: '41370', name: '경기 오산시' }, { code: '41390', name: '경기 시흥시' },
  { code: '41410', name: '경기 군포시' }, { code: '41430', name: '경기 의왕시' },
  { code: '41450', name: '경기 하남시' }, { code: '41461', name: '경기 용인 처인구' },
  { code: '41463', name: '경기 용인 기흥구' }, { code: '41465', name: '경기 용인 수지구' },
  { code: '41480', name: '경기 파주시' }, { code: '41500', name: '경기 이천시' },
  { code: '41550', name: '경기 안성시' }, { code: '41570', name: '경기 김포시' },
  { code: '41590', name: '경기 화성시' }, { code: '41610', name: '경기 광주시' },
  { code: '41630', name: '경기 양주시' }, { code: '41650', name: '경기 포천시' },
  { code: '41670', name: '경기 여주시' }, { code: '41800', name: '경기 연천군' },
  { code: '41820', name: '경기 가평군' }, { code: '41830', name: '경기 양평군' },
  { code: '42110', name: '강원 춘천시' }, { code: '42130', name: '강원 원주시' },
  { code: '42150', name: '강원 강릉시' }, { code: '42170', name: '강원 동해시' },
  { code: '42190', name: '강원 태백시' }, { code: '42210', name: '강원 속초시' },
  { code: '42230', name: '강원 삼척시' }, { code: '42720', name: '강원 홍천군' },
  { code: '42730', name: '강원 횡성군' }, { code: '42750', name: '강원 영월군' },
  { code: '42760', name: '강원 평창군' }, { code: '42770', name: '강원 정선군' },
  { code: '42780', name: '강원 철원군' }, { code: '42790', name: '강원 화천군' },
  { code: '42800', name: '강원 양구군' }, { code: '42810', name: '강원 인제군' },
  { code: '42820', name: '강원 고성군' }, { code: '42830', name: '강원 양양군' },
  { code: '43111', name: '충북 청주 상당구' }, { code: '43112', name: '충북 청주 서원구' },
  { code: '43113', name: '충북 청주 흥덕구' }, { code: '43114', name: '충북 청주 청원구' },
  { code: '43130', name: '충북 충주시' }, { code: '43150', name: '충북 제천시' },
  { code: '43720', name: '충북 보은군' }, { code: '43730', name: '충북 옥천군' },
  { code: '43740', name: '충북 영동군' }, { code: '43745', name: '충북 증평군' },
  { code: '43750', name: '충북 진천군' }, { code: '43760', name: '충북 괴산군' },
  { code: '43770', name: '충북 음성군' }, { code: '43800', name: '충북 단양군' },
  { code: '44131', name: '충남 천안 동남구' }, { code: '44133', name: '충남 천안 서북구' },
  { code: '44150', name: '충남 공주시' }, { code: '44180', name: '충남 보령시' },
  { code: '44200', name: '충남 아산시' }, { code: '44210', name: '충남 서산시' },
  { code: '44230', name: '충남 논산시' }, { code: '44250', name: '충남 계룡시' },
  { code: '44270', name: '충남 당진시' }, { code: '44710', name: '충남 금산군' },
  { code: '44760', name: '충남 부여군' }, { code: '44770', name: '충남 서천군' },
  { code: '44790', name: '충남 청양군' }, { code: '44800', name: '충남 홍성군' },
  { code: '44810', name: '충남 예산군' }, { code: '44825', name: '충남 태안군' },
  { code: '45111', name: '전북 전주 완산구' }, { code: '45113', name: '전북 전주 덕진구' },
  { code: '45130', name: '전북 군산시' }, { code: '45140', name: '전북 익산시' },
  { code: '45180', name: '전북 정읍시' }, { code: '45190', name: '전북 남원시' },
  { code: '45210', name: '전북 김제시' }, { code: '45710', name: '전북 완주군' },
  { code: '45720', name: '전북 진안군' }, { code: '45730', name: '전북 무주군' },
  { code: '45740', name: '전북 장수군' }, { code: '45750', name: '전북 임실군' },
  { code: '45770', name: '전북 순창군' }, { code: '45790', name: '전북 고창군' },
  { code: '45800', name: '전북 부안군' }, { code: '47111', name: '경북 포항 남구' },
  { code: '47113', name: '경북 포항 북구' }, { code: '47130', name: '경북 경주시' },
  { code: '47150', name: '경북 김천시' }, { code: '47170', name: '경북 안동시' },
  { code: '47190', name: '경북 구미시' }, { code: '47210', name: '경북 영주시' },
  { code: '47230', name: '경북 영천시' }, { code: '47250', name: '경북 상주시' },
  { code: '47280', name: '경북 문경시' }, { code: '47290', name: '경북 경산시' },
  { code: '47720', name: '경북 의성군' }, { code: '47730', name: '경북 청송군' },
  { code: '47750', name: '경북 영양군' }, { code: '47760', name: '경북 영덕군' },
  { code: '47770', name: '경북 청도군' }, { code: '47820', name: '경북 고령군' },
  { code: '47830', name: '경북 성주군' }, { code: '47840', name: '경북 칠곡군' },
  { code: '47850', name: '경북 예천군' }, { code: '47900', name: '경북 봉화군' },
  { code: '47920', name: '경북 울진군' }, { code: '47930', name: '경북 울릉군' },
  { code: '48121', name: '경남 창원 의창구' }, { code: '48123', name: '경남 창원 성산구' },
  { code: '48125', name: '경남 창원 마산합포구' }, { code: '48127', name: '경남 창원 마산회원구' },
  { code: '48129', name: '경남 창원 진해구' }, { code: '48170', name: '경남 진주시' },
  { code: '48220', name: '경남 통영시' }, { code: '48240', name: '경남 사천시' },
  { code: '48250', name: '경남 김해시' }, { code: '48270', name: '경남 밀양시' },
  { code: '48310', name: '경남 거제시' }, { code: '48330', name: '경남 양산시' },
  { code: '48720', name: '경남 의령군' }, { code: '48730', name: '경남 함안군' },
  { code: '48740', name: '경남 창녕군' }, { code: '48750', name: '경남 고성군' },
  { code: '48780', name: '경남 남해군' }, { code: '48790', name: '경남 하동군' },
  { code: '48820', name: '경남 산청군' }, { code: '48840', name: '경남 함양군' },
  { code: '48850', name: '경남 거창군' }, { code: '48860', name: '경남 합천군' },
  { code: '50110', name: '제주 제주시' }, { code: '50130', name: '제주 서귀포시' },
  { code: '12110', name: '전남광주 목포시' }, { code: '12130', name: '전남광주 여수시' },
  { code: '12150', name: '전남광주 순천시' }, { code: '12170', name: '전남광주 나주시' },
  { code: '12190', name: '전남광주 광양시' }, { code: '12210', name: '전남광주 동구' },
  { code: '12240', name: '전남광주 서구' }, { code: '12270', name: '전남광주 남구' },
  { code: '12300', name: '전남광주 북구' }, { code: '12330', name: '전남광주 광산구' },
  { code: '12710', name: '전남광주 담양군' }, { code: '12720', name: '전남광주 곡성군' },
  { code: '12730', name: '전남광주 구례군' }, { code: '12740', name: '전남광주 고흥군' },
  { code: '12750', name: '전남광주 보성군' }, { code: '12760', name: '전남광주 화순군' },
  { code: '12770', name: '전남광주 장흥군' }, { code: '12780', name: '전남광주 강진군' },
  { code: '12790', name: '전남광주 해남군' }, { code: '12800', name: '전남광주 영암군' },
  { code: '12810', name: '전남광주 무안군' }, { code: '12820', name: '전남광주 함평군' },
  { code: '12830', name: '전남광주 영광군' }, { code: '12840', name: '전남광주 장성군' },
  { code: '12850', name: '전남광주 완도군' }, { code: '12860', name: '전남광주 진도군' },
  { code: '12870', name: '전남광주 신안군' },
];

const PROVINCE_PREFIXES = {
  '서울': ['서울특별시'], '부산': ['부산광역시'], '대구': ['대구광역시'], '인천': ['인천광역시'],
  '광주': ['광주광역시'], '대전': ['대전광역시'], '울산': ['울산광역시'], '세종': ['세종특별자치시'],
  '경기': ['경기도'], '강원': ['강원특별자치도', '강원도'], '충북': ['충청북도'], '충남': ['충청남도'],
  '전북': ['전북특별자치도', '전라북도'], '전남': ['전라남도'], '경북': ['경상북도'], '경남': ['경상남도'],
  '제주': ['제주특별자치도'], '전남광주': ['전남광주통합특별시'],
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
      const [city, gu] = rest.split(' ');
      candidates.push(`${pf} ${city}시 ${gu}`);
    } else {
      candidates.push(`${pf} ${rest}`);
    }
  }
  return candidates;
}

const REGION_INDEX = LAWD_CODES
  .map(entry => ({ entry, prefixes: buildPrefixCandidates(entry) }))
  .sort((a, b) => Math.max(...b.prefixes.map(p => p.length)) - Math.max(...a.prefixes.map(p => p.length)));

export function matchRegion(rawSigungu) {
  const s = (rawSigungu || '').replace(/\s+/g, ' ').trim();
  for (const { entry, prefixes } of REGION_INDEX) {
    for (const p of prefixes) {
      if (s === p) return { region: entry.name, dong: '' };
      if (s.startsWith(p + ' ')) return { region: entry.name, dong: s.slice(p.length + 1).trim() };
    }
  }
  return null;
}

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
    return { bunji, main_num: null, sub_num: null };
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

export async function importBatch(supabase, table, rawRows) {
  const builder = BUILDERS[table];
  if (!builder) throw new Error(`알 수 없는 테이블: ${table}`);

  const unmatched = new Map();
  const built = [];
  for (const row of rawRows) {
    const matched = matchRegion(row['시군구']);
    if (!matched) {
      const key = row['시군구'] || '(없음)';
      unmatched.set(key, (unmatched.get(key) || 0) + 1);
      continue;
    }
    built.push(builder(row, matched));
  }

  const uniqueRows = Array.from(
    new Map(built.map(r => [`${r.region}_${r.dong}_${r.danji}_${r.size}_${r.floor}_${r.deal_date}`, r])).values()
  );

  let saved = 0;
  const errors = [];
  const BATCH = 500;
  for (let i = 0; i < uniqueRows.length; i += BATCH) {
    const chunk = uniqueRows.slice(i, i + BATCH);
    const { error } = await supabase.from(table).upsert(chunk, {
      onConflict: 'region,dong,danji,size,floor,deal_date',
    });
    if (error) errors.push(error.message);
    else saved += chunk.length;
  }

  return {
    received: rawRows.length,
    matched: built.length,
    unmatchedCount: rawRows.length - built.length,
    unmatchedRegions: Array.from(unmatched.entries()).slice(0, 10),
    saved,
    errors,
  };
}
