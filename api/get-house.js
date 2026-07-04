import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
    const { lawdCd } = req.query;

    try {
        // 1. 아파트 매매 데이터 조회
        const { data: aptData, error: aptError } = await supabase
            .from('house_trades')
            .select('*')
            .eq('lawd_cd', lawdCd)
            .order('deal_year', { ascending: false })
            .order('deal_month', { ascending: false });

        if (aptError) throw aptError;

        // 2. 클라이언트가 기대하는 구조로 반환
        // index.html의 loadAllData가 dbData.apt를 읽으려 하므로 구조를 맞춰줍니다.
        return res.status(200).json({
            apt: aptData || [],
            rent: [] // 전세 데이터는 나중에 추가하더라도 구조는 유지
        });

    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
}
