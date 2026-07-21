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

   ⚠️ 아래 SQL을 Supabase에 먼저 실행해서 컬럼을 추가해야 합니다:
     ALTER TABLE building_info ADD COLUMN IF NOT EXISTS floor_json jsonb;
     ALTER TABLE building_info ADD COLUMN IF NOT EXISTS expos_json jsonb;

   ── 디버그 ──
   title이 없거나, price/floor/expos가 비어있을 때 응답에 debug 필드를
   추가로 포함시켜서 건축HUB가 실제로 뭐라고 응답했는지 바로 확인 가능.
   층별개요/전유공용면적의 필드명(tag)은 공식 문서 기준 추정치라, 실제
   응답에서 비어있는 값이 보이면 debug.floorRaw/exposRaw로 실제 태그명을
   확인해서 normalizeFloor/normalizeExposArea를 수정해야 할 수 있습니다.
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

    const commonParams = { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam };
    const [titleResult, priceResult, floorResult, exposResult] = await Promise.all([
      fetchBld('getBrTitleInfo', commonParams),
      fetchBld('getBrHsprcInfo', commonParams),
      fetchBld('getBrFlrOulnInfo', { ...commonParams, numOfRows: '100' }),
      fetchBld('getBrExposPubuseAreaInfo', { ...commonParams, numOfRows: '200' }),
    ]);
    const titleItems = titleResult.items;
    const priceItems = priceResult.items;

    const titleItem = pickBestItem(titleItems, bldNmKey);
    const priceItem = pickLatestPrice(priceItems);

    const title = titleItem ? normalizeTitle(titleItem) : null;
    const price = priceItem ? normalizePrice(priceItem) : null;
    const floors = floorResult.items.length
      ? floorResult.items.map(normalizeFloor).sort((a, b) => floorSortKey(a) - floorSortKey(b))
      : null;
    const exposAreas = exposResult.items.length
      ? exposResult.items.map(normalizeExposArea)
      : null;

    // title이 없거나, price가 "빈 껍데기"(year/month/price 전부 비어있음)이거나,
    // 층별개요/전유공용면적이 비어있을 때도 디버그 정보 포함 (원인 파악용, 확인 후 제거 권장)
    const priceEmpty = !price || (!price.year && !price.month && (price.price === null || price.price === undefined));
    const debug = (!title || priceEmpty || !floors || !exposAreas) ? {
      titleHttpStatus: titleResult.httpStatus,
      priceHttpStatus: priceResult.httpStatus,
      floorHttpStatus: floorResult.httpStatus,
      exposHttpStatus: exposResult.httpStatus,
      titleRaw: titleResult.raw,
      priceRaw: priceResult.raw,
      floorRaw: floorResult.raw,
      exposRaw: exposResult.raw,
    } : undefined;

    // ── 3. 캐시에 저장 (write-through) ──
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

/* 여러 후보 태그명 중 값이 있는 첫 번째를 반환 (필드명이 확실치 않은 신규 API용 안전장치) */
function getAny(it, tags) {
  for (const t of tags) {
    const v = it.get(t);
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

/* 층 정렬 기준: 지하는 깊은 순(지하3→지하1), 지상은 낮은 순(1→2→3) */
function floorSortKey(f) {
  const n = parseInt(String(f.flrNo).replace(/[^0-9]/g, ''), 10) || 0;
  return (f.flrGbNm && f.flrGbNm.includes('지하')) ? -n : n;
}

function toInt(v) { const n = parseInt(v, 10); return Number.isNaN(n) ? null : n; }
function toFloat(v) { const n = parseFloat(v); return Number.isNaN(n) ? null : n; }

function normalizeTitle(it) {
  return {
    bldNm: it.get('bldNm'),
    platPlc: getAny(it, ['platPlc']),         // 지번주소
    newPlatPlc: getAny(it, ['newPlatPlc']),   // 도로명주소
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
  };
}

function normalizePrice(it) {
  return {
    year: it.get('stdrYear'),
    month: it.get('stdrMt'),
    price: toInt(it.get('housePrice')),
  };
}

/* 층별개요(getBrFlrOulnInfo) - 태그명은 공식 문서 기준 추정치 */
function normalizeFloor(it) {
  return {
    flrGbNm: getAny(it, ['flrGbCdNm']),                 // 층구분 (지상/지하)
    flrNo: getAny(it, ['flrNoNm', 'flrNo']),             // 층번호
    mainAtchGbNm: getAny(it, ['mainAtchGbCdNm']),        // 주/부속 구분
    strct: getAny(it, ['strctCdNm']),                    // 구조
    mainPurps: getAny(it, ['mainPurpsCdNm']),             // 주용도
    etcPurps: getAny(it, ['etcPurps']),                   // 기타용도
    area: toFloat(getAny(it, ['area'])),                  // 면적(㎡)
  };
}

/* 전유공용면적(getBrExposPubuseAreaInfo) - 태그명은 공식 문서 기준 추정치 */
function normalizeExposArea(it) {
  return {
    hoNm: getAny(it, ['hoNm']),                                              // 호명칭
    flrGbNm: getAny(it, ['flrGbCdNm']),                                      // 층구분
    flrNo: getAny(it, ['flrNoNm', 'flrNo']),                                  // 층번호
    esUseNm: getAny(it, ['exposPubuseGbCdNm', 'esUseStatusCdNm', 'esUseCdNm']), // 전유/공용 구분
    strct: getAny(it, ['strctCdNm']),                                        // 구조
    mainPurps: getAny(it, ['mainPurpsCdNm']),                                 // 용도
    area: toFloat(getAny(it, ['area'])),                                      // 면적(㎡)
  };
}
