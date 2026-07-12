/* ════════════════════════════════════
   좌표/법정동코드 캐시 - 단건 저장(upsert)
   클라이언트가 카카오 API로 새로 지오코딩/법정동코드 조회에 성공할 때마다
   fire-and-forget으로 호출해서 결과를 영구 저장합니다.
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'POST only' });
  }

  const { cacheKey, lat, lon, sigunguCd, bjdongCd } = req.body || {};
  if (!cacheKey || !lat || !lon) {
    return res.status(400).json({ error: 'cacheKey, lat, lon 필요' });
  }

  try {
    const { error } = await supabase.from('complex_coords').upsert({
      cache_key: cacheKey,
      lat,
      lon,
      sigungu_cd: sigunguCd || null,
      bjdong_cd: bjdongCd || null,
    }, { onConflict: 'cache_key' });

    if (error) throw error;
    return res.status(200).json({ ok: true });
  } catch (err) {
    console.error('save-coord 에러:', err.message);
    return res.status(500).json({ ok: false, error: err.message });
  }
}
