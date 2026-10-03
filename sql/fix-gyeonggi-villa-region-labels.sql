-- ════════════════════════════════════════════════════════════
-- 경기 양평·연천·가평 빌라 거래 지역명 바로잡기 (2026-10-03)
-- 수도권 빌라 배지 전수 점검에서 발견: 2025~2026년 연립다세대 거래 일부가 옆 지역 이름으로
-- 저장돼 있었음(양평군 거래 → '경기 여주시', 연천군 → '경기 양주시', 가평군 → '경기 포천시',
-- 안성시 죽산면 → '경기 이천시'). 이름이 틀리니 지도에서 위치를 못 찾아 배지가 안 떴음.
-- 지금 수집 코드 목록은 맞음(lawd-codes/shared-villa 대조 완료) - 예전에 들어온 행만 틀림.
-- 경북·경남 때와 같은 방식: 거래마다 읍·면 이름(dong의 첫 단어)으로 실제 지역을 정함.
-- 아래 읍·면은 모두 해당 군에만 있는 이름이라(여주·양주·포천·이천에는 없음) 안전하게 옮길 수 있음.
-- 중복(같은 거래가 맞는 이름으로도 이미 있는 경우)은 먼저 지우고, 임시 표식 → 확정 3단계.
-- Supabase SQL Editor에 이 파일 전체를 붙여넣고 Run 한 번이면 됨.
-- ════════════════════════════════════════════════════════════

BEGIN;

CREATE TEMP TABLE em_map (src text, em text, county text);
INSERT INTO em_map VALUES
('경기 여주시','양평읍','경기 양평군'),
('경기 여주시','강상면','경기 양평군'),
('경기 여주시','강하면','경기 양평군'),
('경기 여주시','양서면','경기 양평군'),
('경기 여주시','옥천면','경기 양평군'),
('경기 여주시','서종면','경기 양평군'),
('경기 여주시','단월면','경기 양평군'),
('경기 여주시','청운면','경기 양평군'),
('경기 여주시','양동면','경기 양평군'),
('경기 여주시','지평면','경기 양평군'),
('경기 여주시','용문면','경기 양평군'),
('경기 여주시','개군면','경기 양평군'),
('경기 양주시','연천읍','경기 연천군'),
('경기 양주시','전곡읍','경기 연천군'),
('경기 양주시','군남면','경기 연천군'),
('경기 양주시','청산면','경기 연천군'),
('경기 양주시','백학면','경기 연천군'),
('경기 양주시','미산면','경기 연천군'),
('경기 양주시','왕징면','경기 연천군'),
('경기 양주시','신서면','경기 연천군'),
('경기 양주시','중면','경기 연천군'),
('경기 양주시','장남면','경기 연천군'),
('경기 포천시','가평읍','경기 가평군'),
('경기 포천시','청평면','경기 가평군'),
('경기 포천시','설악면','경기 가평군'),
('경기 포천시','조종면','경기 가평군'),
('경기 포천시','상면','경기 가평군'),
('경기 포천시','북면','경기 가평군'),
('경기 이천시','죽산면','경기 안성시');

CREATE FUNCTION pg_temp.fix_region(r text, d text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE((SELECT county FROM em_map WHERE src = r AND em = split_part(d, ' ', 1)), r)
$$;

-- ---- villa_trades ----
DELETE FROM villa_trades t USING (
  SELECT ctid FROM (
    SELECT ctid, ROW_NUMBER() OVER (
      PARTITION BY pg_temp.fix_region(region, dong), dong, danji, size, floor, deal_date
      ORDER BY (pg_temp.fix_region(region, dong) = region) DESC, ctid) AS rn
    FROM villa_trades WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시', '경기 양평군', '경기 연천군', '경기 가평군', '경기 안성시')
  ) x WHERE rn > 1
) dup WHERE t.ctid = dup.ctid;
UPDATE villa_trades SET region = 'ZZFIX_' || pg_temp.fix_region(region, dong)
  WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시') AND pg_temp.fix_region(region, dong) <> region;
UPDATE villa_trades SET region = substring(region from 7) WHERE region LIKE 'ZZFIX\_%';

-- ---- single_trades ----
DELETE FROM single_trades t USING (
  SELECT ctid FROM (
    SELECT ctid, ROW_NUMBER() OVER (
      PARTITION BY pg_temp.fix_region(region, dong), dong, danji, size, floor, deal_date
      ORDER BY (pg_temp.fix_region(region, dong) = region) DESC, ctid) AS rn
    FROM single_trades WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시', '경기 양평군', '경기 연천군', '경기 가평군', '경기 안성시')
  ) x WHERE rn > 1
) dup WHERE t.ctid = dup.ctid;
UPDATE single_trades SET region = 'ZZFIX_' || pg_temp.fix_region(region, dong)
  WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시') AND pg_temp.fix_region(region, dong) <> region;
UPDATE single_trades SET region = substring(region from 7) WHERE region LIKE 'ZZFIX\_%';

-- ---- villa_rent ----
DELETE FROM villa_rent t USING (
  SELECT ctid FROM (
    SELECT ctid, ROW_NUMBER() OVER (
      PARTITION BY pg_temp.fix_region(region, dong), dong, danji, size, floor, deal_date
      ORDER BY (pg_temp.fix_region(region, dong) = region) DESC, ctid) AS rn
    FROM villa_rent WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시', '경기 양평군', '경기 연천군', '경기 가평군', '경기 안성시')
  ) x WHERE rn > 1
) dup WHERE t.ctid = dup.ctid;
UPDATE villa_rent SET region = 'ZZFIX_' || pg_temp.fix_region(region, dong)
  WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시') AND pg_temp.fix_region(region, dong) <> region;
UPDATE villa_rent SET region = substring(region from 7) WHERE region LIKE 'ZZFIX\_%';

COMMIT;

-- ---- 확인: 이름과 읍·면이 안 맞는 행이 남았는지(모두 0이어야 정상) ----
SELECT 'villa_trades' AS tbl, count(*) AS mismatched FROM villa_trades WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시') AND pg_temp.fix_region(region, dong) <> region
UNION ALL SELECT 'single_trades', count(*) FROM single_trades WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시') AND pg_temp.fix_region(region, dong) <> region
UNION ALL SELECT 'villa_rent', count(*) FROM villa_rent WHERE region IN ('경기 여주시', '경기 양주시', '경기 포천시', '경기 이천시') AND pg_temp.fix_region(region, dong) <> region;
