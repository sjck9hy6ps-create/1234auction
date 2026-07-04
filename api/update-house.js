import { createClient } from '@supabase/supabase-js';

// ✅ 환경 변수 이름으로 호출 (실제 값은 Vercel Settings에 넣으세요)
const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_ANON_KEY;
const GOV_KEY = process.env.PUBLIC_DATA_API_KEY;

const supabase = createClient(supabaseUrl, supabaseKey);

export default async function handler(req, res) {
    // 1. 환경 변수 로드 확인 (에러 방지)
    if (!supabaseUrl || !supabaseKey || !GOV_KEY) {
        return res.status(200).json({ 
            error: "환경 변수 설정이 누락되었습니다. Vercel Settings를 확인하세요." 
        });
    }

    const { lawdCd = "11440", dealYmd = "202405" } = req.query;

    try {
        console.log(`수집 시작: \${lawdCd}, \${dealYmd}`);
        
        // 2. 국토부 API 호출
        const endpoint = 'getRTMSDataSvcAptTradeDev';
        const url = `https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?serviceKey=${GOV_KEY}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}&pageNo=1&numOfRows=100`;
        
        const response = await fetch(url);
        const text = await response.text();

        // 3. XML 파싱 (간이 정규식)
        const itemMatches = text.match(/<item>([\s\S]*?)<\/item>/g) || [];
        const items = itemMatches.map(item => {
            const getVal = (tag) => item.match(new RegExp(`<${tag}>([^<]*)`))?.[1] || "";
            return {
                lawd_cd: lawdCd,
                deal_year: parseInt(getVal('dealYear')),
                deal_month: parseInt(getVal('dealMonth')),
                deal_day: parseInt(getVal('dealDay')),
                apartment_name: getVal('aptNm'),
                exclusive_area: parseFloat(getVal('excluUseAr')),
                deal_amount: getVal('dealAmount').trim().replace(/,/g, ''),
                floor: parseInt(getVal('floor')),
                build_year: getVal('buildYear'),
                road_name: getVal('roadNm')
            };
        });

        if (items.length === 0) {
            return res.status(200).json({ success: true, message: "수집된 데이터가 없습니다." });
        }

        // 4. Supabase DB 저장
        const { error } = await supabase
            .from('house_trades')
            .upsert(items, { onConflict: 'lawd_cd,deal_year,deal_month,deal_day,apartment_name,exclusive_area,floor' });

        if (error) throw error;

        return res.status(200).json({ success: true, count: items.length });

    } catch (e) {
        return res.status(200).json({ error: "실행 중 오류", message: e.message });
    }
}
