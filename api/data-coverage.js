/* ════════════════════════════════════
   데이터 수집 범위 조회 API
   - 아파트 매매/전월세, 연립다세대·단독다가구 매매/전월세 4개 카테고리의
     최소~최대 deal_date(수집된 데이터 범위)와 건수를 반환합니다.
   - 프론트엔드 지도 화면에 "데이터 수집 범위" 표시 + 과거 데이터 추가 시
     알림 기능에 사용됩니다.
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

// 테이블이 아직 없거나(예: villa_rent/single_rent 생성 전) 비어있어도 에러 없이 null로 처리
// min/max/count를 서로 독립적으로 조회함 - 행이 많은 테이블(house_trades 등)에서
// count 쿼리 하나가 느리거나 실패해도 min/max까지 같이 null이 되지 않도록 함
// ⚠️ 2026-08: house_rent가 count(87만여건)는 정상인데 min/max만 계속 null로 나오는 현상이
// 있었음 - 원인이 console.warn(서버 로그, 프론트에선 못 봄)에만 찍혀서 진단이 안 됐던 것이라,
// 실패 시 이유를 result.warnings에 담아 응답 JSON에도 그대로 노출시킴(임시 디버그용이 아니라
// 앞으로도 이런 조회 실패를 화면에서 바로 알아챌 수 있게 상시 유지).
async function getRange(table) {
  const result = { min: null, max: null, count: 0, warnings: [] };

  try {
    const { data: minRow, error: e1 } = await supabase
      .from(table).select('deal_date').not('deal_date', 'is', null)
      .order('deal_date', { ascending: true }).limit(1);
    if (e1) { console.warn(`data-coverage: ${table} min 조회 실패 -`, e1.message); result.warnings.push(`min 조회 실패: ${e1.message}`); }
    else if (minRow && minRow[0]) result.min = minRow[0].deal_date;
    else result.warnings.push('min 조회는 성공했으나 결과 행이 0건(deal_date가 전부 null이거나 데이터 없음)');
  } catch (e) { console.warn(`data-coverage: ${table} min 조회 예외 -`, e.message); result.warnings.push(`min 조회 예외: ${e.message}`); }

  try {
    const { data: maxRow, error: e2 } = await supabase
      .from(table).select('deal_date').not('deal_date', 'is', null)
      .order('deal_date', { ascending: false }).limit(1);
    if (e2) { console.warn(`data-coverage: ${table} max 조회 실패 -`, e2.message); result.warnings.push(`max 조회 실패: ${e2.message}`); }
    else if (maxRow && maxRow[0]) result.max = maxRow[0].deal_date;
    else result.warnings.push('max 조회는 성공했으나 결과 행이 0건(deal_date가 전부 null이거나 데이터 없음)');
  } catch (e) { console.warn(`data-coverage: ${table} max 조회 예외 -`, e.message); result.warnings.push(`max 조회 예외: ${e.message}`); }

  try {
    // 'exact'는 큰 테이블에서 느려서 타임아웃 위험이 있어 'estimated'(추정치, 빠름)로 변경
    const { count, error: e3 } = await supabase
      .from(table).select('*', { count: 'estimated', head: true });
    if (e3) { console.warn(`data-coverage: ${table} count 조회 실패 -`, e3.message); result.warnings.push(`count 조회 실패: ${e3.message}`); }
    else result.count = count || 0;
  } catch (e) { console.warn(`data-coverage: ${table} count 조회 예외 -`, e.message); result.warnings.push(`count 조회 예외: ${e.message}`); }

  return result;
}

function mergeRanges(a, b) {
  const mins = [a.min, b.min].filter(v => v !== null);
  const maxs = [a.max, b.max].filter(v => v !== null);
  return {
    min: mins.length ? Math.min(...mins) : null,
    max: maxs.length ? Math.max(...maxs) : null,
    count: (a.count || 0) + (b.count || 0),
    warnings: [...(a.warnings || []), ...(b.warnings || [])],
  };
}

/* ════════════════════════════════════
   법정동별 거래량 순위(topDongs) - 2026-08 추가
   - "최근 N개월 기준, 법정동 단위로 거래량이 많은 곳 TOP 20"을 아파트/연립다세대 각각
     따로 보여주기 위한 집계. GROUP BY는 PostgREST의 count() 집계 임베딩 문법
     (select=region,dong,cnt:count())을 그대로 supabase-js에 넘겨서 DB에서 직접
     집계하게 함 - 전체 행을 서버로 끌고 와서 JS에서 세는 방식보다 훨씬 빠르고 가벼움.
   - region 컬럼은 "서울 강남구"처럼 시/도+시군구가 한 문자열로 저장돼 있어(LAWD_CODES
     참고), 시/도 필터는 region이 그 문자열로 시작하는지(LIKE 'xxx%')로 판단함.
   - 연립다세대는 villa_trades(연립다세대)+single_trades(단독다가구) 두 테이블로 나뉘어
     있어, 각각 상위 50개를 뽑아 JS에서 (region,dong) 기준으로 합산한 뒤 다시 정렬함
     (정확한 전수 합산은 아니지만 참고용 순위로는 충분한 근사치).
════════════════════════════════════ */
const SIDO_LIST = ['서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주'];
function sixMonthsAgoInt(months) {
  const d = new Date();
  d.setMonth(d.getMonth() - (months || 6));
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
async function getTopDongsRaw(table, cutoff, sido, limit) {
  try {
    let q = supabase.from(table).select('region,dong,cnt:count()')
      .gte('deal_date', cutoff).not('dong', 'is', null).neq('dong', '');
    if (sido) q = q.like('region', sido + '%');
    q = q.order('cnt', { ascending: false }).limit(limit);
    const { data, error } = await q;
    if (error) { console.warn(`topDongs: ${table} 조회 실패 -`, error.message); return []; }
    return (data || []).map(r => ({ region: r.region, dong: r.dong, count: r.cnt }));
  } catch (e) { console.warn(`topDongs: ${table} 조회 예외 -`, e.message); return []; }
}
async function getTopDongs(type, cutoff, sido, limit) {
  if (type === 'apt') {
    return await getTopDongsRaw('house_trades', cutoff, sido, limit);
  }
  // 연립다세대·단독 - 두 테이블을 넉넉히(상위 50개씩) 뽑아 (region,dong) 기준으로 합산
  const [villaRows, singleRows] = await Promise.all([
    getTopDongsRaw('villa_trades', cutoff, sido, 50),
    getTopDongsRaw('single_trades', cutoff, sido, 50),
  ]);
  const merged = {};
  [...villaRows, ...singleRows].forEach(r => {
    const key = r.region + '|' + r.dong;
    if (!merged[key]) merged[key] = { region: r.region, dong: r.dong, count: 0 };
    merged[key].count += r.count;
  });
  return Object.values(merged).sort((a, b) => b.count - a.count).slice(0, limit);
}

/* ════════════════════════════════════
   법정동별 가격상승모멘텀(priceMomentum, "돈되는 지역") - 2026-08 추가
   - 최근 36개월을 6개월 단위 6구간으로 나눠(가장 오래된 구간→가장 최근 구간 순), 각
     구간의 전용면적 20평(≒66㎡, size는 Math.floor(㎡) 정수 저장이라 size>=66) 이상
     물건의 평균거래가(avg(price), price는 이미 만원 단위)를 (region,dong) 별로 구함.
   - 6구간 전부에 거래가 있는 (region,dong)만 후보로 삼고(중간에 거래가 끊긴 곳은
     추세를 믿기 어려우므로 제외), momentumPct = (마지막구간평균 - 첫구간평균) /
     첫구간평균 * 100 로 상승모멘텀을 계산해 내림차순 정렬.
   - PostgREST 집계 임베딩 문법(select=region,dong,avgPrice:avg(price),cnt:count())으로
     DB에서 직접 GROUP BY + AVG를 계산함 - topDongs의 count() 집계와 같은 방식.
   - 연립다세대(villa)는 villa_trades+single_trades 두 테이블을 구간별로 합쳐(거래건수
     가중평균) 하나의 평균가로 취급함.
   - 구간 쿼리(최대 6구간 × 테이블 1~2개)는 Promise.all로 병렬 실행해 응답시간을 줄임.
════════════════════════════════════ */
const MOMENTUM_PYUNG20_SIZE = 66; // 20평(66.115㎡) 이상 - size는 floor(㎡) 정수 저장
function monthsAgoInt(months) {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
function todayInt() {
  const d = new Date();
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
function momentumBuckets() {
  // idx 0 = 가장 오래된 구간(36~30개월 전), idx 5 = 가장 최근 구간(6~0개월 전)
  const buckets = [];
  const today = todayInt();
  for (let i = 0; i < 6; i++) {
    const startMonths = 36 - i * 6, endMonths = 30 - i * 6;
    buckets.push({
      start: monthsAgoInt(startMonths),
      end: i === 5 ? today + 1 : monthsAgoInt(endMonths), // 마지막 구간만 오늘까지 포함(미래 날짜 데이터 방지용 +1)
    });
  }
  return buckets;
}
async function getBucketAvgPrices(tables, start, end, sido) {
  // key "region|dong" -> { region, dong, sum(가중합), count }
  const results = await Promise.all(tables.map(async (table) => {
    try {
      let q = supabase.from(table).select('region,dong,avgPrice:avg(price),cnt:count()')
        .gte('deal_date', start).lt('deal_date', end)
        .gte('size', MOMENTUM_PYUNG20_SIZE)
        .not('dong', 'is', null).neq('dong', '');
      if (sido) q = q.like('region', sido + '%');
      const { data, error } = await q;
      if (error) { console.warn(`priceMomentum: ${table} 조회 실패 -`, error.message); return []; }
      return data || [];
    } catch (e) { console.warn(`priceMomentum: ${table} 조회 예외 -`, e.message); return []; }
  }));
  const acc = {};
  results.flat().forEach(r => {
    if (!r.cnt || !r.avgPrice) return;
    const key = r.region + '|' + r.dong;
    if (!acc[key]) acc[key] = { region: r.region, dong: r.dong, sum: 0, count: 0 };
    acc[key].sum += r.avgPrice * r.cnt;
    acc[key].count += r.cnt;
  });
  return acc;
}
async function getPriceMomentum(type, sido, limit) {
  const tables = type === 'villa' ? ['villa_trades', 'single_trades'] : ['house_trades'];
  const buckets = momentumBuckets();
  const bucketMaps = await Promise.all(buckets.map(b => getBucketAvgPrices(tables, b.start, b.end, sido)));
  const firstMap = bucketMaps[0], lastMap = bucketMaps[5];
  const keys = Object.keys(firstMap).filter(k => bucketMaps.every(m => m[k] && m[k].count > 0));
  const rankings = keys.map(k => {
    const firstAvg = firstMap[k].sum / firstMap[k].count;
    const lastAvg = lastMap[k].sum / lastMap[k].count;
    if (!firstAvg) return null;
    return {
      region: firstMap[k].region,
      dong: firstMap[k].dong,
      firstPrice: Math.round(firstAvg),
      lastPrice: Math.round(lastAvg),
      momentumPct: Math.round((lastAvg - firstAvg) / firstAvg * 1000) / 10,
    };
  }).filter(r => r !== null);
  rankings.sort((a, b) => b.momentumPct - a.momentumPct);
  return rankings.slice(0, limit);
}

export default async function handler(req, res) {
  if (req.query.mode === 'priceMomentum') {
    // 6구간 병렬조회라도 무거운 집계라 캐시를 넉넉히(1시간) 둠
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');
    try {
      const sido = (req.query.sido || '').trim();
      const typeParam = req.query.type === 'apt' || req.query.type === 'villa' ? req.query.type : 'both';
      const result = {};
      if (typeParam === 'both' || typeParam === 'apt') result.apt = await getPriceMomentum('apt', sido, 20);
      if (typeParam === 'both' || typeParam === 'villa') result.villa = await getPriceMomentum('villa', sido, 20);
      return res.status(200).json({ sidoList: SIDO_LIST, sido: sido || null, ...result });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'topDongs') {
    // 30분 캐시 - 실거래 신고는 매일 여러 번 안 바뀌므로 매번 무겁게 재집계할 필요 없음
    res.setHeader('Cache-Control', 's-maxage=1800, stale-while-revalidate=3600');
    try {
      const months = parseInt(req.query.months, 10) || 6;
      const cutoff = sixMonthsAgoInt(months);
      const sido = (req.query.sido || '').trim();
      const typeParam = req.query.type === 'apt' || req.query.type === 'villa' ? req.query.type : 'both';
      const result = {};
      if (typeParam === 'both' || typeParam === 'apt') result.apt = await getTopDongs('apt', cutoff, sido, 20);
      if (typeParam === 'both' || typeParam === 'villa') result.villa = await getTopDongs('villa', cutoff, sido, 20);
      return res.status(200).json({ sidoList: SIDO_LIST, months, sido: sido || null, cutoff, ...result });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  res.setHeader('Cache-Control', 's-maxage=1800, stale-while-revalidate=3600'); // 30분 캐시 (자주 안 바뀌는 정보라 캐싱)
  try {
    const [aptSale, aptRent, villaSale, singleSale, villaRent, singleRent] = await Promise.all([
      getRange('house_trades'),
      getRange('house_rent'),
      getRange('villa_trades'),
      getRange('single_trades'),
      getRange('villa_rent'),
      getRange('single_rent'),
    ]);
    return res.status(200).json({
      aptSale,
      aptRent,
      nonAptSale: mergeRanges(villaSale, singleSale),
      nonAptRent: mergeRanges(villaRent, singleRent),
      updatedAt: new Date().toISOString(),
    });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
