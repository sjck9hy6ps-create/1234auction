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

   ── 배치 캐시조회(POST) ──
   지역을 새로 로딩할 때 연립다세대 건물 수십~수백 개를 하나하나 GET으로
   물어보면, DB엔 이미 캐시가 있어도 요청 왕복시간(latency)만 계속 누적돼
   체감 로딩이 느려집니다. POST { items: [{sigunguCd,bjdongCd,bun,ji,bldNm,key}, ...] }
   로 여러 건물을 한 번에 보내면, sigungu_cd/bjdong_cd 값들로 한 번의 Supabase
   조회만 하고 나머지는 메모리에서 매칭해서 { results: { key: {...}|null } } 로
   돌려줍니다. 외부 API 호출은 하지 않는 "캐시 확인 전용" 모드이며, 캐시 미스인
   건물은 프런트에서 기존 GET(단건, 캐시 없으면 외부 API 호출+저장)으로 마저 채웁니다.

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

  if (req.method === 'POST') {
    return handleBatchCacheCheck(req, res);
  }

  const { sigunguCd, bjdongCd, bun, ji, platGbCd, bldNm, dongNo, force } = req.query;
  if (!sigunguCd || !bjdongCd || !bun) {
    return res.status(400).json({ error: 'sigunguCd, bjdongCd, bun 파라미터가 필요합니다.' });
  }

  const jiParam    = ji || '0000';
  const gbCd       = platGbCd || '0';
  const bldNmKey   = (bldNm || '').trim();
  // ⚠️ 2026-08: 대단지 아파트는 같은 지번(bun/ji)에 표제부가 여러 건(동마다 하나씩, 또는
  // 경로당·관리동 같은 부속건물까지) 등록돼 있는 경우가 많음. 예전엔 bldNm(단지명, 예:
  // "주공9단지")과 표제부의 실제 bldNm(보통 "901동"처럼 동번호만 있거나 아예 비어있음)이
  // 텍스트로 안 맞으면 무조건 items[0](API가 반환한 첫 번째 건물)을 써버려서, 안산 고잔
  // 주공9단지 사례처럼 같은 지번의 1층짜리 경로당 정보가 아파트 정보인 것처럼 뜨는 문제가
  // 있었음(총 층수 1층, 건폐율/용적률 0%/0% 등 - pickBestItem() 참고). dongNo(동번호, 예:
  // "901동")를 추가로 받아 숫자 매칭을 우선 시도하고, 그마저 없으면 주용도가 "공동주택"이면서
  // 층수가 가장 높은 건물을 고르도록 pickBestItem()을 보강함.
  const dongNoDigits = (dongNo || '').replace(/[^0-9]/g, '');
  // 캐시 키에 동번호를 반영(동번호가 다르면 별도 캐시 행) - 기존 bld_nm 컬럼만 재사용해서
  // building_info 테이블 스키마 변경 없이 처리함.
  const cacheBldNm = bldNmKey + (dongNoDigits ? ('__d' + dongNoDigits) : '');
  const forceRefresh = force === '1' || force === 'true';

  try {
    // ── 1. 캐시 조회 (force=1이면 건너뛰고 바로 재조회) ──
    let cached = null;
    if (!forceRefresh) {
      const { data: cachedRow, error: cacheErr } = await supabase
        .from('building_info')
        .select('*')
        .eq('sigungu_cd', sigunguCd)
        .eq('bjdong_cd', bjdongCd)
        .eq('bun', bun)
        .eq('ji', jiParam)
        .eq('bld_nm', cacheBldNm)
        .maybeSingle();
      if (cacheErr) console.error('building_info 캐시 조회 에러:', cacheErr.message);
      cached = cachedRow;
    }

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
      // 대단지는 같은 지번에 동마다(+부속건물까지) 표제부가 여러 건 잡혀 기본 20건을 넘는
      // 경우가 있어(안산 고잔주공9단지 실측으로 확인) numOfRows를 넉넉히 늘림
      fetchBld('getBrTitleInfo', { ...commonParams, numOfRows: '100' }),
      fetchBld('getBrHsprcInfo', commonParams),
      fetchBld('getBrFlrOulnInfo', { ...commonParams, numOfRows: '100' }),
      fetchBld('getBrExposPubuseAreaInfo', { ...commonParams, numOfRows: '200' }),
    ]);
    const titleItems = titleResult.items;
    const priceItems = priceResult.items;

    const titleItem = pickBestItem(titleItems, bldNmKey, dongNoDigits);
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
    // 같은 지번에 표제부가 2건 이상 잡히면(대단지) pickBestItem이 무엇 중에서 골랐는지
    // 바로 확인할 수 있도록 후보 요약을 항상 같이 내려줌(엉뚱한 동이 선택된 것 같을 때
    // 브라우저 네트워크 탭에서 바로 진단 가능하도록 - 원인 재현마다 서버 코드를 다시
    // 뜯어보지 않아도 되게 하기 위함).
    const titleCandidates = titleItems.length > 1 ? titleItems.map(it => ({
      bldNm: it.get('bldNm'),
      mainPurps: it.get('mainPurpsCdNm'),
      grndFlrCnt: it.get('grndFlrCnt'),
      hhldCnt: it.get('hhldCnt'),
      picked: it === titleItem,
    })) : undefined;

    // ── 3. 캐시에 저장 (write-through) ──
    const { error: upsertErr } = await supabase.from('building_info').upsert({
      sigungu_cd: sigunguCd,
      bjdong_cd:  bjdongCd,
      bun,
      ji:         jiParam,
      bld_nm:     cacheBldNm,
      title_json: title,
      price_json: price,
      floor_json: floors,
      expos_json: exposAreas,
      fetched_at: new Date().toISOString(),
    }, { onConflict: 'sigungu_cd,bjdong_cd,bun,ji,bld_nm' });
    if (upsertErr) console.error('building_info 캐시 저장 에러:', upsertErr.message);

    return res.status(200).json({ title, price, floors, exposAreas, cached: false, debug, titleCandidates });
  } catch (err) {
    console.error('건축물대장 조회 에러:', err.message);
    return res.status(500).json({ error: err.message });
  }
}

/* 배치 캐시조회 - 외부 API는 호출하지 않고 building_info 캐시에 있는 것만 돌려줌.
   ⚠️ 2026-08 실측으로 발견/수정한 버그: 예전엔 sigungu_cd/bjdong_cd를 각각 독립적으로
   .in()해서, 세션 중 여러 시군구(지역)가 섞인 요청이 들어오면 실제로 요청하지 않은
   시군구×동 조합까지 교차로 매칭돼 불필요하게 많은 행을 긁어왔음(예: A시군구+X동,
   B시군구+Y동 두 개만 요청했는데 A시군구+Y동, B시군구+X동까지 결과에 섞여 들어감).
   거기에 .range() 없이 select('*')만 쓰면 Supabase(PostgREST) 기본 응답 상한(1000행)에
   묶여서, 이 상한을 넘기는 순간 뒤쪽 행은 조용히 잘려나가 "캐시가 분명 있는데 없다"고
   잘못 응답하는 문제가 있었음. 여러 지역이 누적된 세션에서 캐시 히트율이 최대 27%까지
   떨어지는 걸 직접 재현 확인함 - 아래처럼 (sigungu_cd,bjdong_cd) 쌍 단위로 정확히 매칭
   시키고, 혹시 그래도 1000행을 넘기면 놓치지 않도록 .range()로 끝까지 페이지네이션함. */
async function handleBatchCacheCheck(req, res) {
  const items = Array.isArray(req.body?.items) ? req.body.items : [];
  if (!items.length) return res.status(200).json({ results: {} });

  const pairMap = new Map();
  items.forEach(i => {
    if (!i.sigunguCd || !i.bjdongCd) return;
    pairMap.set(`${i.sigunguCd}|${i.bjdongCd}`, { sigunguCd: i.sigunguCd, bjdongCd: i.bjdongCd });
  });
  const pairs = [...pairMap.values()];
  if (!pairs.length) return res.status(200).json({ results: {} });

  try {
    const orExpr = pairs
      .map(p => `and(sigungu_cd.eq.${p.sigunguCd},bjdong_cd.eq.${p.bjdongCd})`)
      .join(',');

    const rowMap = {};
    const PAGE_SIZE = 1000;
    let from = 0;
    while (true) {
      const { data, error } = await supabase
        .from('building_info')
        .select('*')
        .or(orExpr)
        .range(from, from + PAGE_SIZE - 1);
      if (error) throw error;
      (data || []).forEach(row => {
        const k = [row.sigungu_cd, row.bjdong_cd, row.bun, row.ji, row.bld_nm].join('|');
        rowMap[k] = row;
      });
      if (!data || data.length < PAGE_SIZE) break;
      from += PAGE_SIZE;
    }

    const results = {};
    items.forEach(it => {
      const jiParam = it.ji || '0000';
      const bldNmKey = (it.bldNm || '').trim();
      const rowKey = [it.sigunguCd, it.bjdongCd, it.bun, jiParam, bldNmKey].join('|');
      const key = it.key || rowKey;
      const row = rowMap[rowKey];
      if (row && (Date.now() - new Date(row.fetched_at).getTime()) < FRESH_MS) {
        results[key] = {
          title: row.title_json,
          price: row.price_json,
          floors: row.floor_json || null,
          exposAreas: row.expos_json || null,
          cached: true,
        };
      } else {
        results[key] = null;
      }
    });

    return res.status(200).json({ results });
  } catch (err) {
    console.error('건축물정보 배치 캐시조회 에러:', err.message);
    return res.status(500).json({ results: {}, error: err.message });
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

/* 단지 내 여러 동(건물)이 같은 지번에 조회될 수 있어, 아래 순서로 가장 적합한 건물을 선택:
   1) dongNo(동번호, 예: "901"/"901동")가 주어지면 표제부 bldNm에서 숫자만 뽑아 정확히
      일치하는 항목을 우선 선택 (가장 신뢰도 높은 매칭)
   2) bldNm(단지명, 예: "주공9단지")이 주어지면 기존처럼 텍스트 유사 매칭
   3) 위 둘 다 실패하면(오래된 단지라 표제부 bldNm이 비어있거나 동번호 표기가 없는 경우):
      3-a) 세대수(hhldCnt)가 등록된 항목 중 세대수가 가장 큰 것 (가장 신뢰도 높은 기준 -
           경로당·관리동·변전실 같은 부속건물은 세대수가 0/공란인 경우가 대부분)
      3-b) 그마저 없으면 주용도(mainPurpsCdNm)에 "공동주택"이 포함된 항목 중 지상층수가
           가장 높은 것. 같은 지번에 1~2층짜리 부속건물이 함께 등록돼 있으면, items[0]을
           그냥 쓸 때 이런 부속건물이 뽑혀서 "총 층수 1층, 건폐율/용적률 0%/0%" 식으로
           잘못 표시되는 문제가 있었음 (2026-08 안산 고잔주공9단지 실측으로 확인됨)
   4) 그래도 못 찾으면 items[0] (최후 안전장치, 기존 동작 유지) */
function pickBestItem(items, bldNm, dongNo) {
  if (!items.length) return null;
  const norm = s => (s || '').replace(/\s/g, '');

  if (dongNo) {
    const dongDigits = String(dongNo).replace(/[^0-9]/g, '');
    if (dongDigits) {
      const byDong = items.find(it => {
        const itDigits = norm(it.get('bldNm')).replace(/[^0-9]/g, '');
        return itDigits && itDigits === dongDigits;
      });
      if (byDong) return byDong;
    }
  }

  if (bldNm) {
    const target = norm(bldNm);
    if (target) {
      const matched = items.find(it => {
        const n = norm(it.get('bldNm'));
        return n && (n.includes(target) || target.includes(n));
      });
      if (matched) return matched;
    }
  }

  // 3-a) 세대수(hhldCnt)가 등록된 항목이 있으면 그 중 세대수가 가장 큰 것을 우선함.
  // 경로당·관리동·변전실 같은 부속건물은 보통 세대수가 0/공란이라, mainPurps 텍스트가
  // 애매하거나 표기가 없는 경우에도 이 기준이 가장 신뢰도 높은 "진짜 주거동" 판별법임.
  const withHouseholds = items.filter(it => (parseInt(it.get('hhldCnt'), 10) || 0) > 0);
  if (withHouseholds.length) {
    withHouseholds.sort((a, b) => (parseInt(b.get('hhldCnt'), 10) || 0) - (parseInt(a.get('hhldCnt'), 10) || 0));
    return withHouseholds[0];
  }

  // 3-b) 세대수 정보가 아예 없으면(오래된 단지 등) 주용도가 "공동주택"인 항목 중
  // 지상층수가 가장 높은 것을 선택
  const apartmentItems = items.filter(it => (it.get('mainPurpsCdNm') || '').includes('공동주택'));
  if (apartmentItems.length) {
    apartmentItems.sort((a, b) => {
      const fa = parseInt(a.get('grndFlrCnt'), 10) || 0;
      const fb = parseInt(b.get('grndFlrCnt'), 10) || 0;
      if (fb !== fa) return fb - fa;
      const ha = parseInt(a.get('hhldCnt'), 10) || 0;
      const hb = parseInt(b.get('hhldCnt'), 10) || 0;
      return hb - ha;
    });
    return apartmentItems[0];
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
