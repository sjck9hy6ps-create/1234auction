/* ════════════════════════════════════
   국토교통부 건축HUB - 건축물대장 조회 (Supabase 캐시 우선)
   getBrTitleInfo(표제부) + getBrHsprcInfo(공동주택가격)
   + getBrFlrOulnInfo(층별개요) + getBrExposPubuseAreaInfo(전유공용면적)
   같은 PUBLIC_DATA_API_KEY를 재사용합니다.
   (data.go.kr에서 "국토교통부_건축HUB_건축물대장정보 서비스" 활용신청이
    이 키로 별도 승인되어 있어야 합니다)
   ── 캐싱 ──
   building_info 테이블에 결과를 저장해두고, 180일 이내에 저장된 캐시가
   있으면 외부 API를 다시 호출하지 않고 캐시를 바로 반환합니다.
   (구조/층수/세대수 등은 거의 안 바뀌고, 공시가격도 연 1회만 갱신되므로)
   ※ 이 버전을 쓰려면 Supabase에 아래 컬럼이 먼저 추가되어 있어야 합니다
     (근수님 - 이미 실행하셨다고 확인함):
     ALTER TABLE building_info ADD COLUMN IF NOT EXISTS floor_json jsonb;
     ALTER TABLE building_info ADD COLUMN IF NOT EXISTS expos_json jsonb;
   ── 디버그 ──
   title/price/floors/exposAreas 중 하나라도 비어있으면 응답에 debug
   필드를 추가로 포함시켜서 건축HUB가 실제로 뭐라고 응답했는지
   (에러코드/빈결과 등) 바로 확인 가능. 원인 파악 끝나면 debug 관련
   코드는 제거해도 됩니다.
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
const API_KEY = process.env.PUBLIC_DATA_API_KEY;
const BASE = 'https://apis.data.go.kr/1613000/BldRgstHubService';
const FRESH_MS = 1000 * 60 * 60 * 24 * 180; // 180일

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  const { sigunguCd, bjdongCd, bun, ji, platGbCd, bldNm } = req.query;
  if (!sigunguCd || !bjdongCd || !bun) {
    return res.status(400).json({ error: 'sigunguCd, bjdongCd, bun 파라미터가 필요합니다.' });
  }
  const jiParam   = ji || '0000';
  const gbCd      = platGbCd || '0';
  const bldNmKey  = (bldNm || '').trim();
  try {
    // ── 1. 캐시 조회 ──
    const { data: cached, error: cacheErr } = await supabase
      .from('building_info')
      .select('*')
      .eq('sigungu_cd', sigunguCd)
      .eq('bjdong_cd', bjdongCd)
      .eq('bun', bun)
      .eq('ji', jiParam)
      .eq('bld_nm', bldNmKey)
      .maybeSingle();
    if (cacheErr) console.error('building_info 캐시 조회 에러:', cacheErr.message);
    if (cached && (Date.now() - new Date(cached.fetched_at).getTime()) < FRESH_MS) {
      return res.status(200).json({
        title: cached.title_json,
        price: cached.price_json,
        floors: cached.floor_json || null,
        exposAreas: cached.expos_json || null,
        cached: true,
      });
    }
    // ── 2. 캐시 없거나 오래됨 → 실시간 조회 ──
    if (!API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 없음' });
    const [titleResult, priceResult, flrResult, exposResult] = await Promise.all([
      fetchBld('getBrTitleInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam }),
      fetchBld('getBrHsprcInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam }),
      fetchBld('getBrFlrOulnInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam, numOfRows: '100' }),
      fetchBld('getBrExposPubuseAreaInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam, numOfRows: '200' }),
    ]);
    const titleItems = titleResult.items;
    const priceItems = priceResult.items;
    const titleItem = pickBestItem(titleItems, bldNmKey);
    const priceItem = pickLatestPrice(priceItems);
    const title = titleItem ? normalizeTitle(titleItem) : null;
    const price = priceItem ? normalizePrice(priceItem) : null;

    const floors = flrResult.items.length
      ? flrResult.items.map(normalizeFloor).sort(function(a, b) { return floorSortKey(a) - floorSortKey(b); })
      : null;
    const exposAreas = exposResult.items.length
      ? exposResult.items.map(normalizeExposArea)
      : null;

    // title/price/floors/exposAreas 중 하나라도 없을 때만 디버그 정보 포함 (원인 파악용, 확인 후 제거 권장)
    const priceEmpty = !price || price.price === null;
    const debug = (!title || priceEmpty || !floors || !exposAreas) ? {
      titleHttpStatus: titleResult.httpStatus,
      priceHttpStatus: priceResult.httpStatus,
      floorHttpStatus: flrResult.httpStatus,
      exposHttpStatus: exposResult.httpStatus,
      titleRaw: titleResult.raw,
      priceRaw: priceResult.raw,
      floorRaw: flrResult.raw,
      exposRaw: exposResult.raw,
    } : undefined;

    // ── 3. 캐시에 저장 (write-through) ──
    // title/price가 둘 다 없으면(예: 429 할당량 초과 등 일시적 실패) 캐시에 저장하지 않음
    // → 다음 요청 때 다시 실시간 조회를 시도할 수 있게 함
    if (title || price) {
      const { error: upsertErr } = await supabase.from('building_info').upsert({
        sigungu_cd: sigunguCd,
        bjdong_cd:  bjdongCd,
        bun,
        ji:         jiParam,
        bld_nm:     bldNmKey,
        title_json: title,
        price_json: price,
        floor_json: floors,
        expos_json: exposAreas,
        fetched_at: new Date().toISOString(),
      }, { onConflict: 'sigungu_cd,bjdong_cd,bun,ji,bld_nm' });
      if (upsertErr) console.error('building_info 캐시 저장 에러:', upsertErr.message);
    }

    return res.status(200).json({ title, price, floors, exposAreas, cached: false, debug });
  } catch (err) {
    console.error('건축물대장 조회 에러:', err.message);
    return res.status(500).json({ error: err.message });
  }
}

async function fetchBld(op, params) {
  const qs = new URLSearchParams({
    serviceKey: API_KEY,
    numOfRows: '20',
    pageNo: '1',
    ...params,
  });
  const url = `${BASE}/${op}?${qs.toString()}`;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const text = await r.text();
    if (text.includes('SERVICE_KEY_IS_NOT_REGISTERED_ERROR') || text.includes('<errMsg>') || text.includes('<returnAuthMsg>')) {
      console.warn(op, '건축HUB 에러:', text.slice(0, 300));
      return { items: [], raw: text.slice(0, 500), httpStatus: r.status };
    }
    return { items: parseItems(text), raw: text.slice(0, 500), httpStatus: r.status };
  } catch (e) {
    console.error(op, '호출 실패:', e.message);
    return { items: [], raw: '(fetch 예외: ' + e.message + ')', httpStatus: null };
  }
}

function parseItems(xmlText) {
  const items = [];
  const re = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = re.exec(xmlText)) !== null) {
    const block = m[1];
    items.push({
      get: function(tag) {
        const r = new RegExp('<' + tag + '>([^<]*)<\\/' + tag + '>');
        const mm = block.match(r);
        return mm ? mm[1].trim() : '';
      }
    });
  }
  return items;
}

/* 태그 이름이 문서마다 다르게 표기되는 경우가 있어, 후보 목록 중 값이 있는
   첫 번째 태그를 반환하는 방어적 헬퍼 (층별개요/전유공용면적 필드에 사용) */
function getAny(it, tags) {
  for (let i = 0; i < tags.length; i++) {
    const v = it.get(tags[i]);
    if (v) return v;
  }
  return '';
}

/* 단지 내 여러 동이 조회될 수 있어, 단지명(danji)과 가장 비슷한 동을 우선 선택 */
function pickBestItem(items, bldNm) {
  if (!items.length) return null;
  if (bldNm) {
    const norm = s => (s || '').replace(/\s/g, '');
    const target = norm(bldNm);
    if (target) {
      const matched = items.find(it => {
        const n = norm(it.get('bldNm'));
        return n && (n.includes(target) || target.includes(n));
      });
      if (matched) return matched;
    }
  }
  return items[0];
}

/* 공시가격은 여러 연도가 나올 수 있어 가장 최근 기준연월 선택 */
function pickLatestPrice(items) {
  if (!items.length) return null;
  return items.slice().sort((a, b) => {
    const ay = parseInt(a.get('stdrYear') + a.get('stdrMt')) || 0;
    const by = parseInt(b.get('stdrYear') + b.get('stdrMt')) || 0;
    return by - ay;
  })[0];
}

function toInt(v) { const n = parseInt(v, 10); return Number.isNaN(n) ? null : n; }
function toFloat(v) { const n = parseFloat(v); return Number.isNaN(n) ? null : n; }

function normalizeTitle(it) {
  return {
    bldNm: it.get('bldNm'),
    mainPurps: it.get('mainPurpsCdNm'),
    strct: it.get('strctCdNm'),
    roofCd: it.get('roofCdNm'),
    platArea: toFloat(it.get('platArea')),
    archArea: toFloat(it.get('archArea')),
    totArea: toFloat(it.get('totArea')),
    bcRat: toFloat(it.get('bcRat')),
    vlRat: toFloat(it.get('vlRat')),
    hhldCnt: toInt(it.get('hhldCnt')),
    fmlyCnt: toInt(it.get('fmlyCnt')),
    heit: toFloat(it.get('heit')),
    grndFlrCnt: toInt(it.get('grndFlrCnt')),
    ugrndFlrCnt: toInt(it.get('ugrndFlrCnt')),
    rideElvtCnt: toInt(it.get('rideUseElvtCnt')),
    emgenElvtCnt: toInt(it.get('emgenUseElvtCnt')),
    indrAutoUtcnt: toInt(it.get('indrAutoUtcnt')),
    oudrAutoUtcnt: toInt(it.get('oudrAutoUtcnt')),
    indrMechUtcnt: toInt(it.get('indrMechUtcnt')),
    oudrMechUtcnt: toInt(it.get('oudrMechUtcnt')),
    useAprDay: it.get('useAprDay'),
    pmsDay: it.get('pmsDay'),
    engrGrade: it.get('engrGrade'),
    // 지번/도로명주소 (지번주소 표시용으로 추가)
    platPlc: it.get('platPlc'),
    newPlatPlc: it.get('newPlatPlc'),
  };
}

function normalizePrice(it) {
  return {
    year: it.get('stdrYear'),
    month: it.get('stdrMt'),
    price: toInt(it.get('housePrice')),
  };
}

/* 층별개요 (getBrFlrOulnInfo) - 층 하나당 항목 하나 */
function normalizeFloor(it) {
  const flrGbNm = getAny(it, ['flrGbCdNm']);
  const flrNoNm = getAny(it, ['flrNoNm']);
  const flrNo   = toInt(getAny(it, ['flrNo']));
  return {
    dongNm: getAny(it, ['dongNm']),
    flrGbNm: flrGbNm,          // 지상/지하 구분
    flrNoNm: flrNoNm || (flrNo !== null ? flrNo + '층' : ''),
    flrNo: flrNo,
    strct: getAny(it, ['strctCdNm']),
    mainPurps: getAny(it, ['mainPurpsCdNm', 'etcPurps']),
    area: toFloat(getAny(it, ['area'])),
  };
}

/* 지하는 깊은 층(지하5 등)부터, 지상은 낮은 층부터 오름차순 정렬용 정렬키 */
function floorSortKey(f) {
  const isUgrnd = (f.flrGbNm || '').indexOf('지하') !== -1;
  const n = f.flrNo || 0;
  return isUgrnd ? -100000 + (100 - n) : 100000 + n;
}

/* 전유공용면적 (getBrExposPubuseAreaInfo) - 호실/구획 하나당 항목 하나 */
function normalizeExposArea(it) {
  return {
    dongNm: getAny(it, ['dongNm']),
    hoNm: getAny(it, ['hoNm']),
    flrGbNm: getAny(it, ['flrGbCdNm']),
    flrNoNm: getAny(it, ['flrNoNm']),
    gbNm: getAny(it, ['exposPubuseGbCdNm']),   // 전유/공용 구분
    strct: getAny(it, ['strctCdNm']),
    mainPurps: getAny(it, ['mainPurpsCdNm', 'etcPurps']),
    area: toFloat(getAny(it, ['area'])),
  };
}
