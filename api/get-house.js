import { createClient } from '@supabase/supabase-js';

export default async function handler(req, res) {
  // 환경 변수가 잘 로드되는지 확인 (로그 확인용)
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseKey) {
    return res.status(500).json({ error: "환경 변수가 설정되지 않았습니다." });
  }

  const supabase = createClient(supabaseUrl, supabaseKey);
  const { lawdCd } = req.query;

  try {
    const { data, error } = await supabase
      .from('house_trades') // 👈 Supabase의 테이블 이름이 정확히 'house_trades'인지 확인!
      .select('*')
      .eq('lawd_cd', lawdCd);

    if (error) throw error;

    res.status(200).json(data || []);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: error.message });
  }
}
