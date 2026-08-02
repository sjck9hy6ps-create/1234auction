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
   법정동별 거래량 순위(topDongs) + 가격상승모멘텀(priceMomentum, "돈되는 지역") - 2026-08
   - 둘 다 (region,dong) 기준 GROUP BY 집계가 필요한데, PostgREST의 count()/avg() "집계
     임베딩" URL 문법(select=region,dong,cnt:count())은 Supabase 프로젝트에서 기본적으로
     꺼져 있어(Database → API 설정에서 별도로 켜야 하는 기능) 실제로는 매번 빈 배열만
     돌아왔음(에러 없이 조용히 실패) - 배포 후 실동작 테스트에서 발견.
   - 그래서 GROUP BY 자체를 Postgres 함수(RPC)로 옮김. RPC는 일반 SQL 함수라 저 설정과
     무관하게 항상 동작하고, 전체 행을 서버로 끌고 오지 않고 DB 안에서 이미 집계된 결과
     (법정동 개수 정도)만 돌려주므로 전국 단위로 조회해도 가볍고 빠름.
   - ⚠️ 아래 두 함수(rpc_top_dongs, rpc_bucket_avg_price)는 Supabase SQL 편집기에서 딱 한
     번만 실행해서 만들어 두면 됨(마이그레이션). 이미 만들어져 있다면 이 배포에서는 별도
     조치 없이 그대로 동작함.
     ------------------------------------------------------------------
     create or replace function rpc_top_dongs(p_cutoff int, p_sido text, p_type text, p_limit int default 20)
     returns table(region text, dong text, cnt bigint)
     language sql stable as $$
       select region, dong, count(*) as cnt from (
         select region, dong from house_trades
           where p_type = 'apt' and deal_date >= p_cutoff and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong from villa_trades
           where p_type = 'villa' and deal_date >= p_cutoff and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong from single_trades
           where p_type = 'villa' and deal_date >= p_cutoff and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
       ) t
       group by region, dong order by cnt desc limit p_limit;
     $$;

     create or replace function rpc_bucket_avg_price(p_start int, p_end int, p_sido text, p_type text)
     returns table(region text, dong text, avg_price numeric, cnt bigint)
     language sql stable as $$
       select region, dong, avg(price) as avg_price, count(*) as cnt from (
         select region, dong, price from house_trades
           where p_type = 'apt' and deal_date >= p_start and deal_date < p_end and size >= 66
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, price from villa_trades
           where p_type = 'villa' and deal_date >= p_start and deal_date < p_end and size >= 66
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, price from single_trades
           where p_type = 'villa' and deal_date >= p_start and deal_date < p_end and size >= 66
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
       ) t
       group by region, dong;
     $$;
     ------------------------------------------------------------------
════════════════════════════════════ */
const SIDO_LIST = ['서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주'];
function sixMonthsAgoInt(months) {
  const d = new Date();
  d.setMonth(d.getMonth() - (months || 6));
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
async function getTopDongs(type, cutoff, sido, limit) {
  try {
    const { data, error } = await supabase.rpc('rpc_top_dongs', {
      p_cutoff: cutoff, p_sido: sido || null, p_type: type, p_limit: limit,
    });
    if (error) { console.warn(`topDongs(rpc): ${type} 조회 실패 -`, error.message); return []; }
    return (data || []).map(r => ({ region: r.region, dong: r.dong, count: Number(r.cnt) }));
  } catch (e) { console.warn(`topDongs(rpc): ${type} 조회 예외 -`, e.message); return []; }
}

const MOMENTUM_PYUNG20_SIZE = 66; // 20평(66.115㎡) 이상 - size는 floor(㎡) 정수 저장(RPC 내부에도 하드코딩됨)
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
async function getBucketAvgPrices(type, start, end, sido) {
  try {
    const { data, error } = await supabase.rpc('rpc_bucket_avg_price', {
      p_start: start, p_end: end, p_sido: sido || null, p_type: type,
    });
    if (error) { console.warn(`priceMomentum(rpc): ${type} 조회 실패 -`, error.message); return {}; }
    const acc = {};
    (data || []).forEach(r => {
      const key = r.region + '|' + r.dong;
      acc[key] = { region: r.region, dong: r.dong, avg: Number(r.avg_price), count: Number(r.cnt) };
    });
    return acc;
  } catch (e) { console.warn(`priceMomentum(rpc): ${type} 조회 예외 -`, e.message); return {}; }
}
async function getPriceMomentum(type, sido, limit) {
  const buckets = momentumBuckets();
  const bucketMaps = await Promise.all(buckets.map(b => getBucketAvgPrices(type, b.start, b.end, sido)));
  const firstMap = bucketMaps[0], lastMap = bucketMaps[5];
  // 6구간 전부에 거래가 있는 (region,dong)만 후보로 삼음(중간에 거래가 끊긴 곳은 추세를 믿기 어려움)
  const keys = Object.keys(firstMap).filter(k => bucketMaps.every(m => m[k] && m[k].count > 0));
  const rankings = keys.map(k => {
    const firstAvg = firstMap[k].avg, lastAvg = lastMap[k].avg;
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
