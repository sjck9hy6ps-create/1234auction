import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

function normalizeSearchStr(s) {
  return (s || '').replace(/\s/g, '').toLowerCase();
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');

  const q = (req.query.q || '').trim();
  if (!q || q.length < 2) return res.status(200).json({ results: [] });

  try {
    // danji/dong/bunji 중 하나라도 부분일치하면 후보로 넉넉히 가져온 뒤,
    // 공백 무시 부분일치로 다시 한번 정확히 걸러냅니다.
    const [aptResult, villaResult] = await Promise.all([
      supabase
        .from('house_trades')
        .select('region,dong,danji,bunji,road_name,main_num,sub_num,deal_date')
        .or(`danji.ilike.%${q}%,dong.ilike.%${q}%,bunji.ilike.%${q}%`)
        .order('deal_date', { ascending: false })
        .limit(500),
      supabase
        .from('villa_trades')
        .select('region,dong,danji,bunji,road_name,main_num,sub_num,deal_date')
        .or(`danji.ilike.%${q}%,dong.ilike.%${q}%,bunji.ilike.%${q}%`)
        .order('deal_date', { ascending: false })
        .limit(500),
    ]);

    if (aptResult.error) {
      console.error('house_trades 검색 에러:', aptResult.error.message);
      throw aptResult.error;
    }
    if (villaResult.error) {
      console.error('villa_trades 검색 에러:', villaResult.error.message);
    }

    const qNorm = normalizeSearchStr(q);
    const rows = [
      ...(aptResult.data || []).map(r => ({ ...r, buildingType: 'apt' })),
      ...(villaResult.error ? [] : (villaResult.data || []).map(r => ({ ...r, buildingType: 'villa' }))),
    ];

    const filtered = rows.filter(row => {
      const danjiNorm     = normalizeSearchStr(row.danji);
      const dongBunjiNorm = normalizeSearchStr((row.dong || '') + (row.bunji || ''));
      return danjiNorm.includes(qNorm) || dongBunjiNorm.includes(qNorm);
    });

    // 단지 단위로 중복 제거 (같은 danji+dong+region 조합은 최신 거래 1건만 대표로)
    const groupMap = new Map();
    filtered.forEach(row => {
      const key = `${row.buildingType}|${row.region}|${row.dong}|${row.danji || ''}|${row.bunji || ''}`;
      const existing = groupMap.get(key);
      if (!existing || String(row.deal_date) > String(existing.deal_date)) {
        groupMap.set(key, row);
      }
    });

    const results = Array.from(groupMap.values())
      .sort((a, b) => normalizeSearchStr(a.danji || '').length - normalizeSearchStr(b.danji || '').length)
      .slice(0, 30)
      .map(row => ({
        buildingType: row.buildingType,
        region: row.region,
        dong: row.dong,
        danji: row.danji,
        bunji: row.bunji,
        road_name: row.road_name,
        main_num: row.main_num,
        sub_num: row.sub_num,
      }));

    return res.status(200).json({ results });
  } catch (err) {
    console.error('search-complex 에러:', err.message);
    return res.status(500).json({ error: err.message, results: [] });
  }
}
