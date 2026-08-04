/* ════════════════════════════════════════════════════════════
   api/get-official-price.js
   지도의 모든 매물 패널(일반 아파트/연립다세대/단독다가구 + 경매 물건)에서 쓰는
   국토교통부 공시가격 실시간 조회 (VWorld API)
   - 아파트/연립다세대(공동주택) → 공동주택가격속성조회
   - 단독다가구/토지 → 개별공시지가속성조회
   흐름: 주소 → (VWorld 검색API) PNU(고유번호) → (VWorld 국가중점데이터API) 공시가격
   - 경매 패널: AI가 뽑은 정확한 지번주소(addrJibun)+동/층/호수를 그대로 사용
   - 일반 매물 패널: DB의 region+dong+bunji로 주소를 조립하고, 호수 정보가 없으므로
     층(floor)+전용면적(sizeM2)이 가장 가까운 동일 필지의 유닛을 찾아서 대표값으로 사용

   ⚠️ VWORLD_API_KEY 환경변수 필요 (https://www.vworld.kr 가입 → 오픈API → 인증키 발급)
   ⚠️ 인증키 발급시 등록한 도메인과 VWORLD_DOMAIN이 일치해야 함
   ⚠️ VWorld 서버가 간헐적으로 연결을 끊는 경우(SocketError 등)가 있어, 네트워크 오류는
      500으로 죽지 않고 재시도 후 "조회 실패"로 깔끔하게 응답하도록 처리함
   ⚠️ 이 함수는 PNU 검색 + 공동주택가격 조회 + 개별공시지가 조회를 순차로(최대 3번) 호출하고
      각각 재시도까지 붙어있어 시간이 걸림 - parse-auction.js와 동일하게 maxDuration을 반드시
      명시해야 함(Vercel Hobby 플랜 기본 실행시간 10초는 이 호출 패턴엔 너무 짧아서, 함수가
      VWorld 응답을 받기도 전에 강제 종료되며 커넥션이 끊기고 그게 "연결 실패"로 잘못 보고됨
      - 실제로 이 export가 빠져있던 게 "브라우저 직접호출은 되는데 배포된 함수는 항상 실패"
      증상의 원인이었음).

   ── 2026-07 인천 서구→서해구/검단구 분구 대응 ──
   2026-07-01자로 인천광역시 서구가 폐지되고 서해구/검단구로 분리되면서 법정동코드(및 PNU)가
   바뀌었습니다. api/get-building.js에서 먼저 발견한 것과 같은 계열의 문제인데, 이쪽은 증상이
   반대 방향입니다: VWorld의 "주소→PNU" 검색은 이미 새 지명("서해구")을 인식하고 새 PNU를
   정상적으로 돌려주는데(2026-08 인천 서해구 연희동 712-2 실측: PNU 2827510400107120002
   정상 조회됨), 정작 개별공시지가/공동주택가격 "데이터셋" 자체는 아직 분구 이전 PNU로만
   고시돼 있어서 새 PNU로는 "해당 필지의 공시가격 데이터를 찾지 못했습니다"로 실패합니다
   (반대로 "서구"라는 옛 지명으로 주소검색을 하면 VWorld가 아예 PNU조차 못 찾음 - 주소검색
   인덱스는 이미 완전히 새 지명으로 전환됐기 때문). 즉 어느 한쪽 이름으로도 한번에 안 풀리는
   상태라, 아래처럼 "새 PNU로 주소→PNU까지는 정상 조회하되, 그 PNU로 가격 데이터가 안 나오면
   구코드로 바꾼 PNU로 한 번 더 시도"하는 방식으로 해결합니다.
   확인된 동만 우선 등록했고, 다른 동에서도 같은 증상이 확인되면 LEGACY_PNU_PREFIX_MAP에
   계속 추가하면 됩니다.

   ── 위와는 별개로: 주소 텍스트 자체에 옛 지명("서구")이 남아있는 경우 ──
   경매 패널(addrJibun)은 법원 서류 원문을 AI가 그대로 추출하는 경우가 많아, 주소 텍스트에
   분구 이전 지명("인천광역시 서구")이 그대로 남아있는 사례가 흔함. 그런데 VWorld 주소검색은
   이미 새 지명으로 완전히 전환되어 있어서, "서구"라는 옛 지명으로는 PNU 검색 자체가 0건으로
   실패함(2026-08 실측: "인천광역시 서구 연희동 712-2" 검색 → 0건, "인천광역시 서해구
   연희동 712-2"로 바꿔야 정상 조회됨 - 반대로 region+dong+bunji로 주소를 조립하는 일반
   매물 패널은 DB region 값이 이미 최신화 마이그레이션을 거쳐 "서해구"로 저장돼 있어 이
   문제가 없었음). RENAMED_REGION_CANDIDATES에 등록된 옛 지명이 주소에 섞여 있으면 새
   지명 후보로 자동 치환해 재시도함.
════════════════════════════════════════════════════════════ */
export const maxDuration = 60;

const VWORLD_SEARCH_URL = 'https://api.vworld.kr/req/search';
const VWORLD_APT_PRICE_URL = 'https://api.vworld.kr/ned/data/getApartHousingPriceAttr';
const VWORLD_LAND_PRICE_URL = 'https://api.vworld.kr/ned/data/getIndvdLandPriceAttr';

// PNU(19자리) = sigunguCd(5) + bjdongCd(5) + 산여부(1) + 본번(4) + 부번(4).
// 앞 10자리(시군구+법정동코드)가 분구로 바뀐 지역 중, VWorld 가격 데이터셋이 아직 새 코드를
// 인식하지 못하는 것으로 "확인된" 것만 등록. key: 새 PNU 앞 10자리, value: 분구 이전 구코드.
const LEGACY_PNU_PREFIX_MAP = {
  '2827510400': { sigunguCd: '28260', bjdongCd: '10600' }, // 서해구 연희동 → (구)인천 서구 연희동
};
function buildLegacyPnu(pnu) {
  if (!pnu || pnu.length < 19) return null;
  const legacy = LEGACY_PNU_PREFIX_MAP[pnu.slice(0, 10)];
  if (!legacy) return null;
  return legacy.sigunguCd + legacy.bjdongCd + pnu.slice(10);
}

// "3층302호", "302호" 등 건물 동/호수 표시를 지번주소에서 떼어내고, 순수 지번주소만 남김
// (필지 단위 PNU 조회는 층/호수를 모르는 상태여야 정확히 매칭됨)
function stripUnitSuffix(addr) {
  if (!addr) return '';
  return String(addr)
    .replace(/제?\d+동\s*/g, ' ')
    .replace(/제?\d+층\s*/g, ' ')
    .replace(/제?\d+호\s*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// "302호" → "302" 처럼 숫자만 추출 (VWorld hoNm 파라미터는 숫자만 받음)
function digitsOnly(v) {
  if (!v) return '';
  const m = String(v).match(/\d+/);
  return m ? m[0] : '';
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// VWorld 서버가 간헐적으로 TLS 연결을 끊는 경우(SocketError: other side closed 등)가 있어,
// fetch() 자체가 throw하는 네트워크 오류는 여기서 잡아서 0.5초 후 1회만 재시도하고,
// 그래도 실패하면 예외를 던지는 대신 "실패했다"는 표시를 담은 값을 정상 반환한다
// (호출부가 500으로 죽지 않고 "조회 실패" 메시지로 깔끔하게 응답할 수 있도록)
// Vercel 서버(Node/undici)의 기본 fetch는 User-Agent를 안 보내거나 "node" 같은 값을 보내는데,
// VWorld 쪽 게이트웨이가 이런 요청을 봇 트래픽으로 보고 502로 막는 것으로 보여(직접 브라우저로
// 호출하면 항상 성공하는데 Vercel에서 호출하면 502/연결실패가 반복됨 - 실제 확인된 증상).
// 실제 브라우저와 동일한 User-Agent/Accept 헤더를 붙여서 우회를 시도함.
const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
  // 진단 결과 실제 에러 원인이 "other side closed"(TLS 커넥션을 상대가 먼저 끊음)였음 - Node의
  // fetch(undici)가 커넥션을 재사용(keep-alive)하려다, VWorld 서버가 그 커넥션을 이미 닫아버린
  // 상태에서 재사용을 시도하며 나는 전형적인 오류. 매 요청마다 새 커넥션을 쓰도록 강제해서 이 재사용
  // 문제를 피해봄(서버리스 환경에서는 커넥션 재사용 이점이 크지 않아 부작용 없이 시도해볼만 함).
  'Connection': 'close',
};

async function vworldFetch(url, attempt = 0) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000), headers: BROWSER_HEADERS });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = null; }
    // 502(게이트웨이 차단으로 추정)나 5xx도 네트워크 오류와 동일하게 재시도 대상으로 취급
    if (!res.ok && attempt < 2) {
      await sleep(500 * (attempt + 1));
      return vworldFetch(url, attempt + 1);
    }
    return { ok: res.ok, status: res.status, data, raw: text, networkError: false };
  } catch (err) {
    if (attempt < 2) {
      await sleep(500 * (attempt + 1));
      return vworldFetch(url, attempt + 1);
    }
    console.warn('VWorld 연결 실패(재시도 후에도 실패):', err.message, err.name, err.cause && err.cause.message);
    return { ok: false, status: 0, data: null, raw: '', networkError: true, errMessage: err.message, errName: err.name, errCause: err.cause ? String(err.cause.message || err.cause) : null };
  }
}

// VWorld 응답은 XML→JSON 변환 방식에 따라 fields가 배열/단일객체/래핑객체 등으로
// 들쭉날쭉할 수 있어, 어떤 모양이 와도 배열로 통일해서 반환
// ⚠️ 실제로 getApartHousingPriceAttr/getIndvdLandPriceAttr(국가중점데이터API)는 검색API와 달리
//    "response" 래핑이 아예 없고, {"apartHousingPrices":{"field":[...]}} 또는
//    {"indvdLandPrices":{"field":[...]}}처럼 엔드포인트마다 다른 이름의 최상위 키 안에 field를
//    담아 내려줌 - 이 키들을 못 찾아서 매번 빈 배열([])을 반환하던 게 "PNU는 정상 조회되는데
//    이후 가격 조회는 항상 '데이터 없음'으로 뜨는" 진짜 원인이었음(네트워크 문제가 아니었음).
//    알려진 이름을 하드코딩하는 대신, field 프로퍼티를 가진 첫 하위 객체를 자동으로 찾아 사용.
function extractFieldList(data) {
  const resp = data?.response ?? data;
  let fields = resp?.fields ?? resp?.result?.fields ?? null;
  if (!fields && resp && typeof resp === 'object') {
    const wrapperKey = Object.keys(resp).find((k) => resp[k] && typeof resp[k] === 'object' && resp[k].field !== undefined);
    if (wrapperKey) fields = resp[wrapperKey].field;
  }
  if (fields && fields.field !== undefined) fields = fields.field;
  if (!fields) return [];
  return Array.isArray(fields) ? fields : [fields];
}

async function findPnu(address, key, domain) {
  const clean = stripUnitSuffix(address);
  if (!clean) return { pnu: null, networkError: false };
  const params = new URLSearchParams({
    service: 'search',
    request: 'search',
    version: '2.0',
    crs: 'EPSG:4326',
    query: clean,
    type: 'address',
    category: 'PARCEL',
    format: 'json',
    errorformat: 'json',
    size: '1',
    page: '1',
    key,
  });
  if (domain) params.set('domain', domain);
  const fetchResult = await vworldFetch(`${VWORLD_SEARCH_URL}?${params.toString()}`);
  const { data, networkError } = fetchResult;
  const items = data?.response?.result?.items;
  if (!items || !items.length) {
    return { pnu: null, networkError };
  }
  return { pnu: items[0].id || null, networkError: false }; // PARCEL 검색결과의 id = PNU(19자리)
}

// 분구로 이름이 바뀐 지역의 "옛 지명"이 주소 텍스트에 남아있으면 PNU 검색 자체가 실패하는
// 문제 대응. 패턴에 매칭되면 후보 새 지명들로 순서대로 바꿔서 재시도하고, 하나라도 PNU를
// 찾으면 그 결과를 사용함. 확인된 지역만 등록, 필요시 계속 추가.
const RENAMED_REGION_CANDIDATES = [
  { pattern: /인천\s*(광역시)?\s*서구/, replacements: ['인천광역시 서해구', '인천광역시 검단구'] },
];

async function findPnuWithRegionRetry(address, key, domain) {
  const primary = await findPnu(address, key, domain);
  if (primary.pnu || primary.networkError) return primary;
  for (const rule of RENAMED_REGION_CANDIDATES) {
    if (!rule.pattern.test(address)) continue;
    for (const newRegion of rule.replacements) {
      const altAddress = address.replace(rule.pattern, newRegion);
      if (altAddress === address) continue;
      const altResult = await findPnu(altAddress, key, domain);
      if (altResult.pnu) return altResult;
    }
  }
  return primary; // 옛 지명 치환도 실패하면 원래(실패) 결과 그대로 반환
}

async function getApartPrice(pnu, dongNm, floorNm, hoNm, key, domain) {
  const params = new URLSearchParams({ pnu, format: 'json', numOfRows: '100', pageNo: '1', key });
  if (domain) params.set('domain', domain);
  if (dongNm) params.set('dongNm', dongNm);
  if (floorNm) params.set('floorNm', floorNm);
  if (hoNm) params.set('hoNm', hoNm);
  const { data } = await vworldFetch(`${VWORLD_APT_PRICE_URL}?${params.toString()}`);
  return extractFieldList(data);
}

async function getLandPrice(pnu, key, domain) {
  const params = new URLSearchParams({ pnu, format: 'json', key });
  if (domain) params.set('domain', domain);
  const { data } = await vworldFetch(`${VWORLD_LAND_PRICE_URL}?${params.toString()}`);
  return extractFieldList(data);
}

// 동/층/호수 필터를 단계적으로 완화해가며 공동주택가격을 조회 (기존 3단계 폴백 로직 그대로).
// 2026-07 분구 대응을 위해 새 PNU/구 PNU 양쪽에 동일하게 재사용할 수 있도록 함수로 분리함.
async function fetchAptRowsWithFallback(pnu, dongNm, floorNm, hoNm, key, domain) {
  let aptRows = await getApartPrice(pnu, dongNm, floorNm, hoNm, key, domain);
  let matchedByHo = !!hoNm;
  // ⚠️ 연립다세대/다세대 같은 단일 건물은 VWorld dongNm 자체가 빈 문자열("")로 등록돼 있는
  // 경우가 흔함(안산시 상록구 이동 530-21 다세대로 실제 확인) - 사용자가 입력한 동 번호가
  // 정확해도 VWorld가 그 건물을 무동(無棟)으로 등록해놨으면 dongNm 필터에서 0건이 됨.
  // 이 경우 동 필터를 빼고 호수만으로 재시도(호수는 훨씬 신뢰도가 높은 필드라 대부분
  // 이걸로 충분히 특정됨) - "토지 개별공시지가만 나오고 실제 공시가격은 안 나온다"는
  // 증상이 아파트뿐 아니라 연립다세대에서도 똑같이 재현된 게 이 케이스였음.
  if (!aptRows.length && dongNm) {
    aptRows = await getApartPrice(pnu, '', floorNm, hoNm, key, domain);
  }
  // 호수 필터까지 걸었는데도 0건이면(호수 표기 형식이 안 맞는 경우) 호수 필터도 빼고
  // 층+면적 근사 매칭으로 최후 폴백
  if (!aptRows.length && hoNm) {
    aptRows = await getApartPrice(pnu, '', floorNm, '', key, domain);
    matchedByHo = false;
  }
  return { aptRows, matchedByHo };
}

// 개별공시지가 조회 + 2026-07 분구 대응 구코드 폴백을 한 세트로 처리.
async function fetchLandRowsWithFallback(pnu, key, domain) {
  let rows = await getLandPrice(pnu, key, domain);
  let pnuUsed = pnu;
  if (!rows.length) {
    const legacyPnu = buildLegacyPnu(pnu);
    if (legacyPnu) {
      const legacyRows = await getLandPrice(legacyPnu, key, domain);
      if (legacyRows.length) {
        rows = legacyRows;
        pnuUsed = legacyPnu;
      }
    }
  }
  return { rows, pnuUsed };
}

// 여러 연도 row가 올 수 있어 stdrYear+stdrMt 기준 최신 것 하나를 대표값으로 고름
function pickLatest(rows, yearKey = 'stdrYear', monthKey = 'stdrMt') {
  if (!rows.length) return null;
  return rows.slice().sort((a, b) => {
    const av = `${a[yearKey] || ''}${a[monthKey] || ''}`;
    const bv = `${b[yearKey] || ''}${b[monthKey] || ''}`;
    return bv.localeCompare(av);
  })[0];
}

// 호수(ho)를 모르는 일반 매물 패널용: 동/층이 같은 유닛들 중 "가장 최신 연도" 1건씩만 남기고,
// 그 중 전용면적(sizeM2)이 가장 가까운 유닛을 골라 대표값으로 반환
function pickBestApartRow(rows, sizeM2) {
  if (!rows.length) return null;
  const latestPerUnit = {};
  rows.forEach((r) => {
    const unitKey = `${r.dongNm || ''}_${r.floorNm || ''}_${r.hoNm || ''}`;
    const yv = `${r.stdrYear || ''}${r.stdrMt || ''}`;
    if (!latestPerUnit[unitKey] || yv > latestPerUnit[unitKey]._yv) {
      latestPerUnit[unitKey] = { ...r, _yv: yv };
    }
  });
  const candidates = Object.values(latestPerUnit);
  if (sizeM2) {
    candidates.sort((a, b) => Math.abs((parseFloat(a.prvuseAr) || 0) - sizeM2) - Math.abs((parseFloat(b.prvuseAr) || 0) - sizeM2));
  } else {
    candidates.sort((a, b) => (b._yv || '').localeCompare(a._yv || ''));
  }
  return candidates[0];
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST만 지원함' });

  const VWORLD_API_KEY = process.env.VWORLD_API_KEY;
  if (!VWORLD_API_KEY) {
    return res.status(500).json({ error: 'VWORLD_API_KEY 환경변수가 없습니다. vworld.kr에서 인증키를 발급받아 Vercel/GitHub Secrets에 추가해 주세요.' });
  }
  const VWORLD_DOMAIN = process.env.VWORLD_DOMAIN || '1234auction.vercel.app';

  // addrJibun(경매 패널, AI 추출 정확 주소) 또는 address(일반 매물 패널, region+dong+bunji 조립 주소) 둘 다 지원
  const body = req.body || {};
  const address = body.addrJibun || body.address;
  const { dong, unitFloor, unitNo, floor, sizeM2, propertyType } = body;
  if (!address) {
    return res.status(400).json({ error: 'address(또는 addrJibun) 주소값이 필요합니다.' });
  }

  try {
    const { pnu, networkError } = await findPnuWithRegionRetry(address, VWORLD_API_KEY, VWORLD_DOMAIN);
    if (!pnu) {
      if (networkError) {
        return res.status(200).json({ success: false, error: 'VWorld 서버 연결에 일시적으로 실패했습니다. 잠시 후 다시 시도해 주세요.' });
      }
      return res.status(200).json({ success: false, error: '해당 주소의 필지(PNU)를 찾지 못했습니다. 주소 표기를 확인해 주세요.', addressUsed: stripUnitSuffix(address) });
    }

    const hoNm = digitsOnly(unitNo);
    const floorNm = digitsOnly(unitFloor || floor);
    // ⚠️ dong은 unitNo/floor와 달리 digitsOnly()를 안 거치고 그대로 VWorld dongNm 파라미터로
    // 넘어가고 있었음 - 경매 모달의 "동" 입력칸 placeholder가 "예) 101동"이라 사용자가 "101동"처럼
    // "동" 글자를 붙여 입력하는 게 자연스러운데, VWorld의 dongNm 값은 "29"/"104"처럼 숫자만
    // 있어서 정확일치 필터에 걸려 매번 0건으로 실패하고, 그때마다 토지 개별공시지가로만 폴백되던
    // 게 "토지 공시지가는 나오는데 해당 주소지(공동주택) 공시가격은 안 나온다"는 증상의 원인이었음.
    const dongNm = digitsOnly(dong);

    // 단독다가구로 명시된 경우가 아니면 공동주택(아파트/연립) 조회를 먼저 시도
    const isLikelyLand = propertyType && /단독|다가구|토지/.test(propertyType);
    if (!isLikelyLand) {
      let { aptRows, matchedByHo } = await fetchAptRowsWithFallback(pnu, dongNm, floorNm, hoNm, VWORLD_API_KEY, VWORLD_DOMAIN);
      let pnuForPrice = pnu;

      // 2026-07 인천 서구→서해구 분구 대응: 새 PNU로는 공동주택가격이 0건이면, 등록된 구코드로
      // 재조립한 PNU로 동일한 3단계 폴백을 한 번 더 시도. (연희동 712-2 실측: 새 PNU
      // 2827510400107120002 → 0건, 구 PNU 2826010600107120002로 재시도하면 정상 조회 가능성
      // - get-building.js와 동일한 원인/해결 패턴)
      if (!aptRows.length) {
        const legacyPnu = buildLegacyPnu(pnu);
        if (legacyPnu) {
          const legacyResult = await fetchAptRowsWithFallback(legacyPnu, dongNm, floorNm, hoNm, VWORLD_API_KEY, VWORLD_DOMAIN);
          if (legacyResult.aptRows.length) {
            aptRows = legacyResult.aptRows;
            matchedByHo = legacyResult.matchedByHo;
            pnuForPrice = legacyPnu;
          }
        }
      }

      if (aptRows.length) {
        // 호수(hoNm)를 정확히 아는 경우(경매 패널)는 최신값을, 모르는 경우(일반 패널)는
        // 층+면적이 가장 가까운 유닛을 대표값으로 고름
        const latest = matchedByHo ? pickLatest(aptRows) : (pickBestApartRow(aptRows, sizeM2 ? Number(sizeM2) : null) || pickLatest(aptRows));

        // 국민주택규모(85㎡) 초과 주택 매도시 건물분 부가세 계산을 위해, 같은 PNU(필지)의
        // 개별공시지가(㎡당)도 함께 내려줌 - 집합건물(아파트/연립)이라도 그 밑에 깔린 토지는
        // 여전히 지번 단위로 개별공시지가가 고시되므로 조회 자체는 항상 가능함(공동주택가격과는
        // 별개 데이터). 이 조회가 실패해도 공동주택가격 응답 자체는 그대로 내려감(성능/견고성).
        // pnuForPrice(공동주택가격 조회에 실제로 성공한 PNU - 신/구 어느 쪽이든)로 조회해서
        // 같은 필지 기준으로 일관되게 맞춤.
        let landPriceWonPerM2 = null, landPriceStdrYear = null, landPriceStdrMt = null;
        try {
          const { rows: landRowsForApt } = await fetchLandRowsWithFallback(pnuForPrice, VWORLD_API_KEY, VWORLD_DOMAIN);
          if (landRowsForApt.length) {
            const latestLand = pickLatest(landRowsForApt);
            landPriceWonPerM2 = latestLand.pblntfPclnd ? Number(latestLand.pblntfPclnd) : null;
            landPriceStdrYear = latestLand.stdrYear || null;
            landPriceStdrMt = latestLand.stdrMt || null;
          }
        } catch (e) {
          console.warn('아파트 필지 개별공시지가 조회 실패(공동주택가격은 정상 반환):', e.message);
        }

        return res.status(200).json({
          success: true,
          source: 'apartment',
          pnu: pnuForPrice,
          complexName: latest.aphusNm || null,
          dong: latest.dongNm || null,
          floor: latest.floorNm || null,
          ho: latest.hoNm || null,
          areaM2: latest.prvuseAr ? Number(latest.prvuseAr) : null,
          priceWon: latest.pblntfPc ? Number(latest.pblntfPc) : null,
          stdrYear: latest.stdrYear || null,
          stdrMt: latest.stdrMt || null,
          lastUpdated: latest.lastUpdtDt || null,
          matchedCount: aptRows.length,
          approximate: !matchedByHo, // 호수로 정확히 못 짚고 층/면적으로 추정한 값이면 true
          history: aptRows.map(r => ({ year: r.stdrYear, month: r.stdrMt, priceWon: r.pblntfPc ? Number(r.pblntfPc) : null, dong: r.dongNm, ho: r.hoNm })),
          landPriceWonPerM2,
          landPriceStdrYear,
          landPriceStdrMt,
          legacyFallbackUsed: pnuForPrice !== pnu || undefined,
        });
      }
    }

    // 공동주택 결과가 없으면(단독다가구/토지 등) 개별공시지가로 폴백 (구코드 폴백 포함)
    const { rows: landRows, pnuUsed: landPnuUsed } = await fetchLandRowsWithFallback(pnu, VWORLD_API_KEY, VWORLD_DOMAIN);
    if (landRows.length) {
      const latest = pickLatest(landRows);
      return res.status(200).json({
        success: true,
        source: 'land',
        pnu: landPnuUsed,
        regionName: latest.ldCodeNm || null,
        priceWonPerM2: latest.pblntfPclnd ? Number(latest.pblntfPclnd) : null,
        pblntfDe: latest.pblntfDe || null,
        stdrYear: latest.stdrYear || null,
        stdrMt: latest.stdrMt || null,
        lastUpdated: latest.lastUpdtDt || null,
        matchedCount: landRows.length,
        history: landRows.map(r => ({ year: r.stdrYear, month: r.stdrMt, priceWonPerM2: r.pblntfPclnd ? Number(r.pblntfPclnd) : null })),
        legacyFallbackUsed: landPnuUsed !== pnu || undefined,
      });
    }

    return res.status(200).json({ success: false, error: '해당 필지의 공시가격 데이터를 찾지 못했습니다.', pnu });
  } catch (err) {
    console.error('get-official-price 에러:', err);
    return res.status(500).json({ error: err.message });
  }
}
