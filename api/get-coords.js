/* ════════════════════════════════════
   좌표/법정동코드 캐시 - 여러 단지 키를 한 번에 조회
   지역을 로딩할 때, 화면에 뜰 단지들의 캐시 키를 전부 모아서 이 API로
   한 번에 물어봅니다. 이미 지오코딩된 적 있는 단지는 카카오 API를
   다시 호출하지 않고 여기서 즉시 좌표를 받아옵니다.
   - .in()/필터 방식은 URL 쿼리스트링에 값을 실어 보내다 보니 단지명에 괄호/쉼표가
     있거나 키 개수가 많으면 계속 Bad Request가 나서, Supabase RPC 함수
     get_complex_coords(keys text[])를 만들어 POST 본문으로 통째로 넘기는
     방식으로 바꿨습니다. (get_complex_coords_function.sql을 Supabase에 먼저 실행)
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

  const keys = Array.isArray(req.body?.keys) ? req.body.keys.filter(Boolean) : [];
  if (!keys.length) return res.status(200).json({ coords: {} });

  try {
    const { data, error } = await supabase.rpc('get_complex_coords', { keys });
    if (error) throw error;

    const coords = {};
    (data || []).forEach(row => {
      coords[row.cache_key] = {
        lat: row.lat,
        lon: row.lon,
        sigunguCd: row.sigungu_cd || null,
        bjdongCd: row.bjdong_cd || null,
      };
    });

    return res.status(200).json({ coords });
  } catch (err) {
    console.error('get-coords 에러:', err.message);
    return res.status(500).json({ coords: {}, error: err.message });
  }
}
