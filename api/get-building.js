/* ════════════════════════════════════
   국토교통부 건축HUB - 건축물대장 조회
   getBrTitleInfo(표제부) + getBrHsprcInfo(공동주택가격) 조합
   같은 PUBLIC_DATA_API_KEY를 재사용합니다.
   (data.go.kr에서 "국토교통부_건축HUB_건축물대장정보 서비스" 활용신청이
    이 키로 별도 승인되어 있어야 합니다)
════════════════════════════════════ */
const API_KEY = process.env.PUBLIC_DATA_API_KEY;
const BASE = 'https://apis.data.go.kr/1613000/BldRgstHubService';

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');

  const { sigunguCd, bjdongCd, bun, ji, platGbCd, bldNm } = req.query;
  if (!sigunguCd || !bjdongCd || !bun) {
    return res.status(400).json({ error: 'sigunguCd, bjdongCd, bun 파라미터가 필요합니다.' });
  }
  if (!API_KEY) {
    return res.status(500).json({ error: 'PUBLIC_DATA_API_KEY 없음' });
  }

  const jiParam = ji || '0000';
  const gbCd = platGbCd || '0';

  try {
    const [titleItems, priceItems] = await Promise.all([
      fetchBld('getBrTitleInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam }),
      fetchBld('getBrHsprcInfo', { sigunguCd, bjdongCd, platGbCd: gbCd, bun, ji: jiParam }),
    ]);

    const titleItem = pickBestItem(titleItems, bldNm);
    const priceItem = pickLatestPrice(priceItems);

    return res.status(200).json({
      title: titleItem ? normalizeTitle(titleItem) : null,
      price: priceItem ? normalizePrice(priceItem) : null,
    });
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
      return [];
    }
    return parseItems(text);
  } catch (e) {
    console.error(op, '호출 실패:', e.message);
    return [];
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
