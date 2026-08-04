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

     -- ⚠️ 2026-08(1차): avg_price를 "총 매매가"가 아니라 "평당가(만원/평 = price/size*
     -- 3.305785)"로 바꿈. 국민평형(23~25평)만 보면 단지별 평형 차이를 무시할 수 있어 좋지만,
     -- 그만큼 표본이 작아져서 소도시에서는 우연한 편차가 순위 상위권을 차지하는 문제가
     -- 있었음. 평당가로 정규화하면 모든 평형의 거래를 다 써도 서로 비교 가능해져서 표본이
     -- 훨씬 커짐.
     -- ⚠️ 2026-08(2차): 단순 평균은 신축 프리미엄 건물(아파트는 주변시세 대비 15~20%,
     -- 빌라는 2배 가까이 비싸게 거래되기도 함)이 몇 건만 섞여도 "돈되는 지역"으로 잘못
     -- 뜨는 착시를 만들 수 있어서, build_year 기준 준공 1년 이내(신축) 거래는 집계에서
     -- 빼고 new_cnt/new_avg_price로 별도 반환하도록 바꿈. 신축을 뺀 나머지도 같은
     -- (region,dong) 평균 대비 표준편차 2.5배를 벗어나는 극단적 이상치는 느슨하게
     -- 추가로 걸러냄(로얄동/로얄층 같은 정상 편차는 이 배수로는 안 걸림). 반환 컬럼이
     -- 늘어나서 이번엔 DROP FUNCTION 후 CREATE로 교체해야 함(CREATE OR REPLACE만으로는
     -- 안 됨).
     -- ⚠️ 2026-08(성능 수정): 처음엔 이상치 기준을 중앙값(percentile_cont, 정렬이 필요한
     -- 무거운 연산)으로 만들었는데, "전국"처럼 시/도 없이 조회하면 (region,dong) 그룹 수가
     -- 훨씬 많아져 정렬 비용이 커지면서 응답이 아예 안 오는 문제가 실제 배포 후 테스트에서
     -- 발견됨(시/도 하나로 좁히면 정상, "전국"만 멈춤). AVG/STDDEV_POP(정렬 불필요한
     -- 단일패스 집계)로 교체해 해결함.
     drop function if exists rpc_bucket_avg_price(int, int, text, text, int, int);
     create function rpc_bucket_avg_price(p_start int, p_end int, p_sido text, p_type text, p_min_size int, p_max_size int)
     returns table(region text, dong text, avg_price numeric, cnt bigint, new_cnt bigint, new_avg_price numeric)
     language sql stable as $$
       with raw as (
         select region, dong, price, size, build_year from house_trades
           where p_type = 'apt' and deal_date >= p_start and deal_date < p_end
             and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, price, size, build_year from villa_trades
           where p_type = 'villa' and deal_date >= p_start and deal_date < p_end
             and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
         union all
         select region, dong, price, size, build_year from single_trades
           where p_type = 'villa' and deal_date >= p_start and deal_date < p_end
             and size >= p_min_size and size <= p_max_size
             and dong is not null and dong <> ''
             and (p_sido is null or p_sido = '' or region like p_sido || '%')
       ),
       tagged as (
         select region, dong,
           (price::numeric / nullif(size, 0)) * 3.305785 as ppp,
           (build_year is not null and build_year >= (extract(year from current_date)::int - 1)) as is_new
         from raw
       ),
       existing as (
         select region, dong, ppp from tagged where not is_new
       ),
       stats as (
         select region, dong, avg(ppp) as mean_ppp, stddev_pop(ppp) as sd_ppp
         from existing group by region, dong
       ),
       clipped as (
         select e.region, e.dong, e.ppp
         from existing e
         join stats s on s.region = e.region and s.dong = e.dong
         where e.ppp <= s.mean_ppp + 2.5 * coalesce(s.sd_ppp, 0)
           and e.ppp >= s.mean_ppp - 2.5 * coalesce(s.sd_ppp, 0)
       ),
       new_agg as (
         select region, dong, avg(ppp) as new_avg_price, count(*) as new_cnt
         from tagged where is_new group by region, dong
       )
       select c.region, c.dong,
         avg(c.ppp) as avg_price,
         count(*) as cnt,
         coalesce(n.new_cnt, 0) as new_cnt,
         n.new_avg_price
       from clipped c
       left join new_agg n on n.region = c.region and n.dong = c.dong
       group by c.region, c.dong, n.new_cnt, n.new_avg_price;
     $$;
     ------------------------------------------------------------------
════════════════════════════════════ */
const SIDO_LIST = ['서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주'];
function sixMonthsAgoInt(months) {
  return monthsAgoInt(months || 6);
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

// 2026-08: 국민평형(23~25평)만 보던 걸 폐지하고 전체 평형을 다 씀 - 대신 avg_price가
// "평당가"로 바뀌었으니(RPC 참고) 평형이 달라도 그대로 비교 가능함. size 범위는 데이터
// 오류(0㎡ 등) 배제용 최소한의 안전장치일 뿐, 더 이상 특정 평형대를 걸러내는 필터가 아님.
const MOMENTUM_SIZE_MIN = 10;
const MOMENTUM_SIZE_MAX = 300;
// 표본 신뢰도 기준(구간당 거래건수) - 2026-08: 이 값 미만이어도 더 이상 후보에서 완전히
// 빼지 않음(아래 getPriceMomentum 참고). 대신 그 구간에 "표본부족" 플래그를 남겨 프론트에서
// 신뢰도가 낮다고 표시하는 용도로만 씀. 아파트/연립다세대는 원래 거래 빈도 차이가 커서
// (연립다세대가 훨씬 뜸함 - 기존 급등지역 로직도 이걸 감안해 연립다세대는 3개월 대신
// 6개월 단기창을 씀) 기준을 서로 다르게 둠.
const MOMENTUM_MIN_BUCKET_COUNT_APT = 7;
const MOMENTUM_MIN_BUCKET_COUNT_VILLA = 4;
// 구간 길이(일, 타입별로 다름) - 원래 "달력상 1개월"(28~31일, 월마다 길이가 달라짐)이었는데
// 고정폭으로 변경함(총 6구간 × 이 값 = 되돌아보는 총 일수). 날짜 계산도 setDate() 기반이라
// monthsAgoInt()의 월말 오버플로우 문제와 무관하게 항상 정확한 간격이 나옴.
// ⚠️ 2026-08: 아파트는 house_trades 수집 시작일(2025-12-01)에 맞춰 40일(총 240일)로,
// 연립다세대는 원래 거래가 뜸해서 더 넓게 60일(총 360일, 수집 시작일 2025-01-01 안에 넉넉히
// 들어옴)로 서로 다르게 둠.
const MOMENTUM_BUCKET_DAYS_APT = 40;
const MOMENTUM_BUCKET_DAYS_VILLA = 60;
function minBucketCountFor(type) { return type === 'villa' ? MOMENTUM_MIN_BUCKET_COUNT_VILLA : MOMENTUM_MIN_BUCKET_COUNT_APT; }
function bucketDaysFor(type) { return type === 'villa' ? MOMENTUM_BUCKET_DAYS_VILLA : MOMENTUM_BUCKET_DAYS_APT; }
// 추세 일관성 필터 - 6구간(=5번의 구간 전환) 중 상승한 횟수가 이보다 적으면 제외함. 처음↔
// 마지막 구간만 비교하면 중간에 들쭉날쭉해도 "모멘텀"으로 잡히는 문제를 막기 위함.
const MOMENTUM_MIN_UP_TRANSITIONS = 3;
// 거래량 급감 경고 - 직전 구간 대비 거래량이 이 비율 미만으로 줄면 신뢰도가 떨어진다고 보고
// 결과에서 완전히 빼지는 않되(정보 자체는 유의미할 수 있어서) 프론트에 경고로 표시함.
const MOMENTUM_VOLUME_DROP_RATIO = 0.3;
// N개월 전 날짜(YYYYMMDD 정수) - Date.setMonth()을 그냥 쓰면 "그 달에 없는 날짜"로 넘어갈 때
// 다음달로 오버플로우되는 버그가 있음(예: 3/31 - 1개월 => 2월엔 31일이 없어서 JS가 자동으로
// 3/3으로 튕겨버림 - 의도한 "2월 말"보다 한 달 가까이 어긋난 엉뚱한 날짜가 됨). 이게 실제로
// 벌어지면 이 날짜를 구간 경계로 쓰는 돈되는 지역 6구간의 길이가 서로 달라지거나 겹쳐서
// "거래량 급감"처럼 보이는 가짜 신호나 평단가 오류를 만들 수 있어서, 대상 월의 마지막
// 날짜로 클램프하는 방식(예: 3/31 - 1개월 => 2/28)으로 2026-08에 수정함.
function monthsAgoInt(months) {
  const now = new Date();
  const totalMonths = now.getFullYear() * 12 + now.getMonth() - months;
  const y = Math.floor(totalMonths / 12);
  const m = totalMonths - y * 12; // 0-indexed month
  const daysInTargetMonth = new Date(y, m + 1, 0).getDate();
  const day = Math.min(now.getDate(), daysInTargetMonth);
  const mm = String(m + 1).padStart(2, '0'), dd = String(day).padStart(2, '0');
  return parseInt(`${y}${mm}${dd}`, 10);
}
function todayInt() {
  const d = new Date();
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
// N일 전 날짜(YYYYMMDD 정수) - Date.setDate()는 setMonth()와 달리 월/년 경계를 자동으로
// 정확히 처리하므로(예: 3/5 - 10일 => 2/23) 별도 클램프 로직이 필요 없음.
function daysAgoInt(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return parseInt(`${y}${m}${day}`, 10);
}
function momentumBuckets(type) {
  // 2026-08: 달력상 1개월(28~31일, 월마다 길이가 다름) 구간 → 타입별 고정폭(bucketDaysFor)×6구간
  // 으로 변경. idx 0 = 가장 오래된 구간, idx 5 = 가장 최근 구간
  const bucketDays = bucketDaysFor(type);
  const buckets = [];
  const today = todayInt();
  for (let i = 0; i < 6; i++) {
    const startDays = bucketDays * (6 - i), endDays = bucketDays * (5 - i);
    buckets.push({
      start: daysAgoInt(startDays),
      end: i === 5 ? today + 1 : daysAgoInt(endDays), // 마지막 구간만 오늘까지 포함(미래 날짜 데이터 방지용 +1)
    });
  }
  return buckets;
}
// 진단용: 특정 (region,dong,type) 구간의 rpc_bucket_avg_price 집계 뒤에 숨은
// 원본 거래 목록을 그대로 보여줌 - "왜 이 구간 평단가가 이렇게 나왔는지" 근거자료
// 확인용. 범위가 (region,dong,40~60일)로 좁아서 가볍고 빠름. 신규 서버리스 함수를
// 새로 만들지 않고 기존 mode 분기 방식 그대로 씀.
async function getBucketDetailRows(type, region, dong, start, end) {
  const cols = 'region,dong,danji,price,size,floor,deal_date,build_year';
  let rows = [];
  if (type === 'villa') {
    const [{ data: v, error: e1 }, { data: s, error: e2 }] = await Promise.all([
      supabase.from('villa_trades').select(cols).eq('region', region).eq('dong', dong)
        .gte('deal_date', start).lt('deal_date', end)
        .gte('size', MOMENTUM_SIZE_MIN).lte('size', MOMENTUM_SIZE_MAX),
      supabase.from('single_trades').select(cols).eq('region', region).eq('dong', dong)
        .gte('deal_date', start).lt('deal_date', end)
        .gte('size', MOMENTUM_SIZE_MIN).lte('size', MOMENTUM_SIZE_MAX),
    ]);
    if (e1) throw e1;
    if (e2) throw e2;
    rows = [...(v || []), ...(s || [])];
  } else {
    const { data, error } = await supabase.from('house_trades').select(cols)
      .eq('region', region).eq('dong', dong)
      .gte('deal_date', start).lt('deal_date', end)
      .gte('size', MOMENTUM_SIZE_MIN).lte('size', MOMENTUM_SIZE_MAX);
    if (error) throw error;
    rows = data || [];
  }
  const curYear = new Date().getFullYear();
  return rows
    .map(r => ({
      danji: r.danji, price: r.price, size: r.size, floor: r.floor, deal_date: r.deal_date,
      build_year: r.build_year,
      ppp: r.size ? Math.round((r.price / r.size) * 3.305785 * 10) / 10 : null,
      isNew: r.build_year != null && r.build_year >= curYear - 1,
    }))
    .sort((a, b) => a.deal_date - b.deal_date);
}
async function getBucketAvgPrices(type, start, end, sido) {
  try {
    const { data, error } = await supabase.rpc('rpc_bucket_avg_price', {
      p_start: start, p_end: end, p_sido: sido || null, p_type: type,
      p_min_size: MOMENTUM_SIZE_MIN, p_max_size: MOMENTUM_SIZE_MAX,
    });
    if (error) { console.warn(`priceMomentum(rpc): ${type} 조회 실패 -`, error.message); return {}; }
    const acc = {};
    (data || []).forEach(r => {
      const key = r.region + '|' + r.dong;
      // newCount/newAvg: 신축(준공 1년 이내)으로 분류돼 avg/count 집계에서 제외된 거래
      // (RPC 쪽에서 이미 신축 제외 + 이상치 클리핑까지 끝낸 값이 avg_price/cnt로 옴)
      acc[key] = {
        region: r.region, dong: r.dong, avg: Number(r.avg_price), count: Number(r.cnt),
        newCount: Number(r.new_cnt) || 0,
        newAvg: r.new_avg_price != null ? Number(r.new_avg_price) : null,
      };
    });
    return acc;
  } catch (e) { console.warn(`priceMomentum(rpc): ${type} 조회 예외 -`, e.message); return {}; }
}
async function getPriceMomentum(type, sido, limit) {
  const minCount = minBucketCountFor(type);
  const buckets = momentumBuckets(type);
  const bucketMaps = await Promise.all(buckets.map(b => getBucketAvgPrices(type, b.start, b.end, sido)));
  // 2026-08: 예전엔 "6구간 전부 최소건수 이상"을 만족해야만 후보로 삼았는데, 이러면 거래가
  // 뜸한 동은 흐름이 통째로 끊겨(후보 탈락) 정보가 아예 안 보이는 문제가 있었음. 대신 6구간
  // 중 하나라도 거래가 있는 (region,dong)은 모두 후보로 삼고(합집합), 거래가 없는 구간은
  // 가장 가까운 유효 구간의 값을 그대로 이어붙여(carry-forward) 흐름이 끊기지 않게 하며,
  // 표본이 적은(count < minCount) 구간은 lowSample 플래그만 남겨 프론트에서 "신뢰도 낮음"으로
  // 표시하게 함(결과에서 완전히 빼지 않음).
  const allKeys = new Set();
  bucketMaps.forEach(m => Object.keys(m).forEach(k => allKeys.add(k)));
  const rankings = [];
  allKeys.forEach(k => {
    let meta = null;
    for (const m of bucketMaps) { if (m[k]) { meta = m[k]; break; } }
    if (!meta) return;
    const prices = [], counts = [], lowSample = [], newCounts = [];
    let lastKnownPrice = null;
    bucketMaps.forEach(m => {
      const b = m[k];
      // newCounts: 이 구간에서 신축(준공 1년 이내)이라 avg_price/cnt 집계에서 빠진 거래 건수.
      // b가 없어도(=신축만 있어서 clipped 집계에 아예 안 잡힌 경우 등) 0으로 둠 - 참고용
      // 정보라 흐름 로직(carry-forward)에는 영향 없음.
      newCounts.push(b ? b.newCount : 0);
      if (b && b.count > 0) {
        const p = Math.round(b.avg);
        prices.push(p); counts.push(b.count); lowSample.push(b.count < minCount);
        lastKnownPrice = p;
      } else {
        prices.push(lastKnownPrice); counts.push(0); lowSample.push(true); // 거래 자체가 없는 구간 - 일단 null로 두고 아래서 보정
      }
    });
    const firstValid = prices.find(p => p !== null);
    if (firstValid == null) return; // 이론상 allKeys에 있으면 항상 하나는 있음
    for (let i = 0; i < prices.length; i++) { if (prices[i] === null) prices[i] = firstValid; else break; } // 앞쪽이 비어있으면 뒤쪽 첫 유효값으로 역보정(backward-fill)
    const firstAvg = prices[0], lastAvg = prices[5];
    if (!firstAvg) return;
    // 추세 일관성: 5번의 구간 전환(idx0→1, 1→2, ..., 4→5) 중 상승한 횟수
    let upTransitions = 0;
    for (let i = 1; i < prices.length; i++) { if (prices[i] > prices[i - 1]) upTransitions++; }
    // 거래량 급감 경고: 실제 거래가 있던 직전 구간 대비 급격히 줄어든 경우만 표시
    // (carry-forward로 채워진 0건 구간끼리 비교해서 오탐하지 않도록 counts[i-1]>0 조건을 둠)
    let volumeDrop = false;
    for (let i = 1; i < counts.length; i++) { if (counts[i - 1] > 0 && counts[i] < counts[i - 1] * MOMENTUM_VOLUME_DROP_RATIO) volumeDrop = true; }
    const newCntTotal = newCounts.reduce((a, b) => a + b, 0);
    rankings.push({
      region: meta.region,
      dong: meta.dong,
      prices, // 6구간 평당가(만원/평) 흐름 - 프론트 추세 표시용(빈 구간은 직전/직후 값으로 채움)
      counts, // 6구간 실제 거래건수 흐름(0이면 그 구간엔 거래가 없었다는 뜻)
      lowSample, // 6구간 각각 표본이 minCount 미만이었는지(0건 포함)
      newCounts, // 6구간 각각 신축(준공2년내)이라 위 prices/counts 집계에서 빠진 거래 건수(참고용)
      newCntTotal, // newCounts 합계 - 프론트에서 "신축 거래 별도" 배지 표시 여부 판단용
      upTransitions, // 5번의 구간 전환 중 상승한 횟수(0~5)
      volumeDrop,
      momentumPct: Math.round((lastAvg - firstAvg) / firstAvg * 1000) / 10,
    });
  });
  const filtered = rankings.filter(r => r.upTransitions >= MOMENTUM_MIN_UP_TRANSITIONS);
  filtered.sort((a, b) => b.momentumPct - a.momentumPct);
  return filtered.slice(0, limit);
}

/* ════════════════════════════════════
   법정동(읍면동) 경계 폴리곤 조회 - 2026-08: 원래 api/get-boundary.js라는 별도
   함수였는데, Vercel Hobby 12개 함수 한도에 이미 꽉 차 있어서(auction.js,
   data-coverage.js, export-table.js, get-building.js, get-coords.js,
   get-house.js, get-official-price.js, import-csv-batch.js, parse-auction.js,
   parse-registry.js, save-coord.js, search-complex.js = 12개) 새 파일을 추가할
   수 없었음. data-coverage.js가 이미 mode 분기 방식(topDongs/priceMomentum)을
   쓰고 있어서 여기에 mode=boundary로 합침. 로직 자체는 get-boundary.js와 동일:
   VWorld Data API(LT_C_ADEMD_INFO 레이어)를 시군구코드(sggCd) 단위로 조회하고,
   dong_boundaries 테이블에 영구 캐시(법정동 경계는 거의 안 바뀜) - 이후 같은
   시군구는 VWorld 재호출 없이 DB에서 바로 반환됨.
   ════════════════════════════════════ */
async function getBoundary(sggCd, wantRaw) {
  // 1순위: DB에 이미 저장된 경계가 있으면 VWorld를 호출하지 않고 바로 반환
  try {
    const { data: cached, error: cacheErr } = await supabase
      .from('dong_boundaries')
      .select('emd_cd, emd_nm, geometry')
      .eq('sgg_cd', sggCd);
    if (cacheErr) console.error('dong_boundaries 조회 에러:', cacheErr.message);
    if (cached && cached.length > 0) {
      const boundaries = cached.map((row) => ({ emdCd: row.emd_cd, emdNm: row.emd_nm, geometry: row.geometry }));
      return { status: 200, body: { boundaries, source: 'db' } };
    }
  } catch (e) {
    console.error('dong_boundaries 조회 실패:', e.message);
    // DB 조회가 실패해도 아래 VWorld 호출로 계속 진행 (캐시 미스와 동일하게 취급)
  }

  const VWORLD_KEY = process.env.VWORLD_API_KEY;
  if (!VWORLD_KEY) {
    return { status: 500, body: { error: 'VWORLD_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' } };
  }

  // domain은 VWorld 키 발급 시 등록한 도메인과 반드시 일치해야 함
  const DOMAIN = 'https://1234auction.vercel.app';

  // ⚠️ 2026-08: LT_C_ADEMD_INFO 레이어는 attrFilter로 걸 수 있는 필드가
  // [emd_eng_nm, ag_geom, emd_kor_nm, full_nm, emd_cd] 뿐이라 원래 쓰던
  // "sggCd:=:..." 필터는 VWorld가 INVALID_RANGE 에러로 거부함(실제 배포 후
  // 라이브 호출로 확인) - 애초에 이 필터가 안 먹혀서 법정동 경계선 기능이
  // 한 번도 정상 동작한 적이 없었던 것. emd_cd(10자리 법정동코드 = 앞5자리
  // 시군구코드+뒤5자리 동코드)를 LIKE로 앞자리(sggCd) 일치 검색하는 방식으로 교체.
  const url = `https://api.vworld.kr/req/data?service=data&request=GetFeature&data=LT_C_ADEMD_INFO`
    + `&key=${encodeURIComponent(VWORLD_KEY)}&domain=${encodeURIComponent(DOMAIN)}`
    + `&attrFilter=emd_cd:like:${sggCd}&size=200&format=json&crs=EPSG:4326`;

  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const data = await r.json();

    if (data?.response?.status !== 'OK') {
      return {
        status: 502,
        body: { error: 'VWorld 응답 오류: ' + (data?.response?.status || 'UNKNOWN'), raw: data?.response?.error || null },
      };
    }

    const features = data?.response?.result?.featureCollection?.features || [];
    // ⚠️ VWorld 응답의 속성 필드명은 데이터셋 버전에 따라 emd_cd/emdCd, emd_kor_nm/emdKorNm 등으로
    // 다를 수 있습니다. wantRaw=true로 한 번 호출해서 실제 필드명을 확인할 수 있음.
    const boundaries = features.map((f) => {
      const p = f.properties || {};
      return {
        emdCd: p.emd_cd || p.emdCd || p.EMD_CD || '',
        emdNm: p.emd_kor_nm || p.emdKorNm || p.EMD_KOR_NM || p.full_nm || '',
        geometry: f.geometry,
      };
    });

    if (wantRaw) return { status: 200, body: { raw: data } };

    // DB에 영구 저장 - 다음부터는 이 시군구는 VWorld 재호출 없이 DB에서 바로 반환됨
    const rows = boundaries
      .filter((b) => b.emdCd && b.geometry)
      .map((b) => ({ emd_cd: b.emdCd, sgg_cd: sggCd, emd_nm: b.emdNm, geometry: b.geometry }));
    if (rows.length > 0) {
      const { error: upsertErr } = await supabase
        .from('dong_boundaries')
        .upsert(rows, { onConflict: 'emd_cd' });
      if (upsertErr) console.error('dong_boundaries 저장 에러:', upsertErr.message);
    }

    return { status: 200, body: { boundaries, source: 'vworld' } };
  } catch (err) {
    return { status: 500, body: { error: err.message } };
  }
}

export default async function handler(req, res) {
  if (req.query.mode === 'boundary') {
    res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate=604800');
    const sggCd = req.query.sggCd;
    if (!sggCd || String(sggCd).length !== 5) {
      return res.status(400).json({ error: 'sggCd(5자리 시군구코드)가 필요합니다.' });
    }
    try {
      const { status, body } = await getBoundary(String(sggCd), req.query.raw === 'true');
      return res.status(status).json(body);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'bucketDetail') {
    // 진단용 - "돈되는 지역" 특정 구간 평단가의 근거가 된 원본 거래를 그대로 보여줌.
    // 캐시하지 않음(디버깅용, 최신 상태를 바로바로 봐야 함).
    res.setHeader('Cache-Control', 'no-store');
    const { region, dong, type, start, end } = req.query;
    if (!region || !dong || !start || !end) {
      return res.status(400).json({ error: 'region, dong, start, end 쿼리파라미터가 필요합니다.' });
    }
    try {
      const rows = await getBucketDetailRows(
        type === 'villa' ? 'villa' : 'apt', region, dong, parseInt(start, 10), parseInt(end, 10)
      );
      return res.status(200).json({ region, dong, start, end, count: rows.length, rows });
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  if (req.query.mode === 'priceMomentum') {
    // 6구간 병렬조회라도 무거운 집계라 캐시를 넉넉히(1시간) 둠
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');
    try {
      const sido = (req.query.sido || '').trim();
      const typeParam = req.query.type === 'apt' || req.query.type === 'villa' ? req.query.type : 'both';
      const result = {};
      // 2026-08: apt/villa를 순차 await하면 "전국"처럼 무거운 조회에서 둘의 시간이
      // 그대로 합산돼 더 느려짐 - Promise.all로 병렬 실행해 전체 응답시간을 줄임.
      const jobs = [];
      if (typeParam === 'both' || typeParam === 'apt') jobs.push(getPriceMomentum('apt', sido, 20).then(r => { result.apt = r; }));
      if (typeParam === 'both' || typeParam === 'villa') jobs.push(getPriceMomentum('villa', sido, 20).then(r => { result.villa = r; }));
      await Promise.all(jobs);
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
