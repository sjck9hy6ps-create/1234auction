// /api/get-house.js
import { createClient } from '@supabase/supabase-client';

const supabase = createClient(process.env.https://qfrhodasxmkciyrxskja.supabase.co, process.env.sb_publishable_t4vxrPNUxo2HeMLV_Y7PDw_CDsuL2Ll);

export default async function handler(req, res) {
    const { lawdCd } = req.query;

    const { data, error } = await supabase
        .from('house_cache')
        .select('*')
        .eq('lawd_cd', lawdCd)
        .single();

    if (error) return res.status(404).json({ error: "Data not found" });

    // 클라이언트가 쓰기 편하게 포맷팅하여 반환
    res.status(200).json({
        apt: data.apt_data,
        rent: data.rent_data,
        updatedAt: data.updated_at
    });
}
