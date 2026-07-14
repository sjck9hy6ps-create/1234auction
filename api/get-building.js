/* ════════════════════════════════════
   국토교통부 건축HUB - 건축물대장 조회 (Supabase 캐시 우선)
   getBrTitleInfo(표제부) + getBrHsprcInfo(공동주택가격) 조합
   같은 PUBLIC_DATA_API_KEY를 재사용합니다.
   (data.go.kr에서 "국토교통부_건축HUB_건축물대장정보 서비스" 활용신청이
    이 키로 별도 승인되어 있어야 합니다)

   ── 캐싱 ──
   building_info 테이블에 결과를 저장해두고, 180일 이내에 저장된 캐시가
   있으면 외부 API를 다시 호출하지 않고 캐시를 바로 반환합니다.
   (구조/층수/세대수 등은 거의 안 바뀌고, 공시가격도 연 1회만 갱신되므로)

   ── 디버그 ──
   title/price가 둘 다 null로 나오면 응답에 debug 필드를 추가로 포함시켜서
   건축HUB가 실제로 뭐라고 응답했는지(에러코드/빈결과 등) 바로 확인 가능.
   원인 파악 끝나면 debug 관련 코드는 제거해도 됩니다.
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
      return res.status(200).json({ title: cached.title_json, price: cached.price_json, cached: true });
    }

    // ── 2. 캐시 없거나 오래됨 → 실시간 조회 ──
    if (!API_KEY) return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 없음' });

    const [titleResult, priceResult] = await Promise.all([
      fetchBld('getBrTitleInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam }),
      fetchBld('getBrHsprcInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam }),
    ]);
    const titleItems = titleResult.items;
    const priceItems = priceResult.items;

    const titleItem = pickBestItem(titleItems, bldNmKey);
    const priceItem = pickLatestPrice(priceItems);

    const title = titleItem ? normalizeTitle(titleItem) : null;
    const price = priceItem ? normalizePrice(priceItem) : null;

    // title/price가 둘 다 없을 때만 디버그 정보 포함 (원인 파악용, 확인 후 제거 권장)
    const debug = (!title && !price) ? {
      titleHttpStatus: titleResult.httpStatus,
      priceHttpStatus: priceResult.httpStatus,
      titleRaw: titleResult.raw,
      priceRaw: priceResult.raw,
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
        fetched_at: new Date().toISOString(),
      }, { onConflict: 'sigungu_cd,bjdong_cd,bun,ji,bld_nm' });
      if (upsertErr) console.error('building_info 캐시 저장 에러:', upsertErr.message);
    }
 
    return res.status(200).json({ title, price, cached: false, debug });
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
  };
}

function normalizePrice(it) {
  return {
    year: it.get('stdrYear'),
    month: it.get('stdrMt'),
    price: toInt(it.get('housePrice')),
  };
}
