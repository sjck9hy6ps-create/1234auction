/* ════════════════════════════════════
   좌표/법정동코드 캐시 - 여러 단지 키를 한 번에 조회
   지역을 로딩할 때, 화면에 뜰 단지들의 캐시 키를 전부 모아서 이 API로
   한 번에 물어봅니다. 이미 지오코딩된 적 있는 단지는 카카오 API를
   다시 호출하지 않고 여기서 즉시 좌표를 받아옵니다.
   - keys가 너무 많으면(새 지역 첫 로딩, 웜업 직후 등) Supabase .in() 쿼리가
     한 번에 너무 커져 400(Bad Request)이 나므로, 200개씩 나눠서 조회합니다.
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

const CHUNK_SIZE = 200;

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'POST only' });
  }

  const keys = Array.isArray(req.body?.keys) ? req.body.keys.filter(Boolean) : [];
  if (!keys.length) return res.status(200).json({ coords: {} });

  try {
    const coords = {};

    for (let i = 0; i < keys.length; i += CHUNK_SIZE) {
      const chunk = keys.slice(i, i + CHUNK_SIZE);
      const { data, error } = await supabase
        .from('complex_coords')
        .select('cache_key, lat, lon, sigungu_cd, bjdong_cd')
        .in('cache_key', chunk);

      if (error) throw error;

      (data || []).forEach(row => {
        coords[row.cache_key] = {
          lat: row.lat,
          lon: row.lon,
          sigunguCd: row.sigungu_cd || null,
          bjdongCd: row.bjdong_cd || null,
        };
      });
    }

    return res.status(200).json({ coords });
  } catch (err) {
    console.error('get-coords 에러:', err.message);
    return res.status(500).json({ coords: {}, error: err.message });
  }
}
