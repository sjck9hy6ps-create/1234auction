import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_ANON_KEY;
const GOV_KEY = process.env.PUBLIC_DATA_API_KEY;
const supabase = createClient(supabaseUrl, supabaseKey);

export default async function handler(req, res) {
    if (!supabaseUrl || !supabaseKey || !GOV_KEY) {
        return res.status(200).json({ error: "환경 변수 설정 누락" });
    }

    const { lawdCd = "11440", dealYmd = "202405" } = req.query;

    try {
        const url = `https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?serviceKey=${GOV_KEY}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}&pageNo=1&numOfRows=1000`;
        
        const response = await fetch(url);
        const text = await response.text();

        const itemMatches = text.match(/<item>([\s\S]*?)<\/item>/g) || [];
        const rawItems = itemMatches.map(item => {
            const getVal = (tag) => item.match(new RegExp(`<${tag}>([^<]*)`))?.[1] || "";
            return {
                lawd_cd: lawdCd,
                deal_year: parseInt(getVal('dealYear')),
                deal_month: parseInt(getVal('dealMonth')),
                deal_day: parseInt(getVal('dealDay')),
                apartment_name: getVal('aptNm').trim(),
                exclusive_area: parseFloat(getVal('excluUseAr')),
                deal_amount: getVal('dealAmount').trim().replace(/,/g, ''),
                floor: parseInt(getVal('floor')),
                build_year: getVal('buildYear'),
                road_name: getVal('roadNm')
            };
        });

        // ✅ 핵심: 요청 데이터 내에서 중복 제거 (Unique Key 기준)
        const uniqueItems = [];
        const seen = new Set();

        for (const item of rawItems) {
            const key = `${item.lawd_cd}-${item.deal_year}-${item.deal_month}-${item.deal_day}-${item.apartment_name}-${item.exclusive_area}-${item.floor}`;
            if (!seen.has(key)) {
                seen.add(key);
                uniqueItems.push(item);
            }
        }

        if (uniqueItems.length === 0) {
            return res.status(200).json({ success: true, message: "수집된 데이터가 없습니다." });
        }

        // 4. Supabase DB 저장
        const { error } = await supabase
            .from('house_trades')
            .upsert(uniqueItems, { 
                onConflict: 'lawd_cd,deal_year,deal_month,deal_day,apartment_name,exclusive_area,floor' 
            });

        if (error) throw error;

        return res.status(200).json({ success: true, count: uniqueItems.length });

    } catch (e) {
        return res.status(200).json({ error: "실행 중 오류", message: e.message });
    }
}
