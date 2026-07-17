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
      500으로 죽지 않고 1회 재시도 후 "조회 실패"로 깔끔하게 응답하도록 처리함
════════════════════════════════════════════════════════════ */

const VWORLD_SEARCH_URL = 'https://api.vworld.kr/req/search';
const VWORLD_APT_PRICE_URL = 'https://api.vworld.kr/ned/data/getApartHousingPriceAttr';
const VWORLD_LAND_PRICE_URL = 'https://api.vworld.kr/ned/data/getIndvdLandPriceAttr';

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
async function vworldFetch(url, isRetry) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = null; }
    return { ok: res.ok, status: res.status, data, raw: text, networkError: false };
  } catch (err) {
    if (!isRetry) {
      await sleep(500);
      return vworldFetch(url, true);
    }
    console.warn('VWorld 연결 실패(재시도 후에도 실패):', err.message);
    return { ok: false, status: 0, data: null, raw: '', networkError: true };
  }
}

// VWorld 응답은 XML→JSON 변환 방식에 따라 fields가 배열/단일객체/래핑객체 등으로
// 들쭉날쭉할 수 있어, 어떤 모양이 와도 배열로 통일해서 반환
function extractFieldList(data) {
  const resp = data?.response ?? data;
  let fields = resp?.fields ?? resp?.result?.fields ?? null;
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
  const { data, networkError } = await vworldFetch(`${VWORLD_SEARCH_URL}?${params.toString()}`);
  const items = data?.response?.result?.items;
  if (!items || !items.length) return { pnu: null, networkError };
  return { pnu: items[0].id || null, networkError: false }; // PARCEL 검색결과의 id = PNU(19자리)
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
    const { pnu, networkError } = await findPnu(address, VWORLD_API_KEY, VWORLD_DOMAIN);
    if (!pnu) {
      if (networkError) {
        return res.status(200).json({ success: false, error: 'VWorld 서버 연결에 일시적으로 실패했습니다. 잠시 후 다시 시도해 주세요.' });
      }
      return res.status(200).json({ success: false, error: '해당 주소의 필지(PNU)를 찾지 못했습니다. 주소 표기를 확인해 주세요.', addressUsed: stripUnitSuffix(address) });
    }

    const hoNm = digitsOnly(unitNo);
    const floorNm = digitsOnly(unitFloor || floor);
    // 단독다가구로 명시된 경우가 아니면 공동주택(아파트/연립) 조회를 먼저 시도
    const isLikelyLand = propertyType && /단독|다가구|토지/.test(propertyType);

    if (!isLikelyLand) {
      const aptRows = await getApartPrice(pnu, dong || '', floorNm, hoNm, VWORLD_API_KEY, VWORLD_DOMAIN);
      if (aptRows.length) {
        // 호수(hoNm)를 정확히 아는 경우(경매 패널)는 최신값을, 모르는 경우(일반 패널)는
        // 층+면적이 가장 가까운 유닛을 대표값으로 고름
        const latest = hoNm ? pickLatest(aptRows) : (pickBestApartRow(aptRows, sizeM2 ? Number(sizeM2) : null) || pickLatest(aptRows));
        return res.status(200).json({
          success: true,
          source: 'apartment',
          pnu,
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
          approximate: !hoNm, // 호수 특정 없이 층/면적으로 추정한 값이면 true
          history: aptRows.map(r => ({ year: r.stdrYear, month: r.stdrMt, priceWon: r.pblntfPc ? Number(r.pblntfPc) : null, dong: r.dongNm, ho: r.hoNm })),
        });
      }
    }

    // 공동주택 결과가 없으면(단독다가구/토지 등) 개별공시지가로 폴백
    const landRows = await getLandPrice(pnu, VWORLD_API_KEY, VWORLD_DOMAIN);
    if (landRows.length) {
      const latest = pickLatest(landRows);
      return res.status(200).json({
        success: true,
        source: 'land',
        pnu,
        regionName: latest.ldCodeNm || null,
        priceWonPerM2: latest.pblntfPclnd ? Number(latest.pblntfPclnd) : null,
        pblntfDe: latest.pblntfDe || null,
        stdrYear: latest.stdrYear || null,
        stdrMt: latest.stdrMt || null,
        lastUpdated: latest.lastUpdtDt || null,
        matchedCount: landRows.length,
        history: landRows.map(r => ({ year: r.stdrYear, month: r.stdrMt, priceWonPerM2: r.pblntfPclnd ? Number(r.pblntfPclnd) : null })),
      });
    }

    return res.status(200).json({ success: false, error: '해당 필지의 공시가격 데이터를 찾지 못했습니다.', pnu });
  } catch (err) {
    console.error('get-official-price 에러:', err);
    return res.status(500).json({ error: err.message });
  }
}
