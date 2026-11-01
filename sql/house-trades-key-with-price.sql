-- 아파트 매매(house_trades) 저장 키에 가격(price) 추가 (2026-11-01)
-- 이유: 키가 (region,dong,danji,size,floor,deal_date)라서 같은 단지·면적·층·날짜에 서로 다른 가격의 거래가 둘 이상이면
--       한 건만 남았음(공식 국토부 CSV와 대조하면 약 1.1%). 가격을 키에 넣어 서로 다른 거래를 따로 저장함.
-- 실행: Supabase 대시보드 > SQL Editor 에 이 파일 전체를 붙여넣고 실행. (실행 전/후 수집 스크립트는 자동으로 알맞은 키를 씀)
-- 안전: 새 키는 예전 키보다 느슨해서(가격이 하나 더 들어감) 기존 행이 새 키를 어기는 일은 없음. 실행 중 잠깐 테이블 쓰기가 대기할 수 있음.
-- 되돌리기: 맨 아래 주석의 ROLLBACK 절 참고(되돌리면 같은 키 거래는 다시 합쳐질 수 있음 - 중복 정리가 먼저 필요).
BEGIN;

-- 1) 예전 키(price 없는 6개 열)로 만들어진 유니크 제약/인덱스를 찾아 지움 (이름을 몰라도 열 구성으로 찾음)
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT i.indexrelid::regclass AS idx, c.conname
    FROM pg_index i
    LEFT JOIN pg_constraint c ON c.conindid = i.indexrelid AND c.contype = 'u'
    WHERE i.indrelid = 'public.house_trades'::regclass AND i.indisunique AND NOT i.indisprimary
      AND (SELECT array_agg(a.attname::text ORDER BY a.attname::text) FROM pg_attribute a WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey))
          = ARRAY['danji','deal_date','dong','floor','region','size']
  LOOP
    IF r.conname IS NOT NULL THEN EXECUTE format('ALTER TABLE public.house_trades DROP CONSTRAINT %I', r.conname);
    ELSE EXECUTE format('DROP INDEX %s', r.idx); END IF;
    RAISE NOTICE '지운 예전 키: %', r.idx;
  END LOOP;
END $$;

-- 2) 가격 포함 새 키
ALTER TABLE public.house_trades
  ADD CONSTRAINT house_trades_key_with_price UNIQUE (region, dong, danji, size, floor, deal_date, price);

COMMIT;

-- ROLLBACK(필요할 때만, 같은 6열 키로 겹치는 행을 먼저 지운 뒤 실행):
--   ALTER TABLE public.house_trades DROP CONSTRAINT house_trades_key_with_price;
--   ALTER TABLE public.house_trades ADD CONSTRAINT house_trades_key_old UNIQUE (region, dong, danji, size, floor, deal_date);
