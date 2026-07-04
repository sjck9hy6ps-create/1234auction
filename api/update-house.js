import { createClient } from '@supabase/supabase-client';

// Supabase 연결
const supabase = createClient(process.env.https://qfrhodasxmkciyrxskja.supabase.co, process.env.sb_publishable_t4vxrPNUxo2HeMLV_Y7PDw_CDsuL2Ll);
const GOV_KEY = process.env.ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6;

export default async function handler(req, res) {
    // 보안: Vercel Cron 요청인지 확인
    if (req.headers.authorization !== `Bearer \${process.env.CRON_SECRET}`) {
        return res.status(401).json({ error: 'Unauthorized' });
    }

    // 수집할 대상 지역 코드 (여기에 필요한 지역 코드를 추가하세요)
    const lawdCodes = ["11680", "11650", "11500"]; 
    
    // 수집할 기간 설정 (현재로부터 8년 전까지의 월 리스트 생성)
    const months = [];
    const now = new Date();
    for (let i = 0; i < 96; i++) { // 8년 = 96개월
        const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
        const ym = d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0');
        months.push(ym);
    }

    try {
        for (const code of lawdCodes) {
            console.log(`Starting collection for: \${code}`);
            let allAptSales = [];
            let allAptRents = [];

            // 8년치 데이터를 월별로 순회하며 수집
            for (const ym of months) {
                // 매매 데이터 수집
                const sales = await fetchFullPages('getRTMSDataSvcAptTradeDev', code, ym);
                allAptSales = allAptSales.concat(sales);

                // 전월세 데이터 수집
                const rents = await fetchFullPages('getRTMSDataSvcAptRent', code, ym);
                allAptRents = allAptRents.concat(rents);
            }

            // Supabase DB에 저장 (8년치 통째로 저장)
            const { error } = await supabase.from('house_cache').upsert({
                lawd_cd: code,
                apt_allAptSales,
                rent_allAptRents,
                updated_at: new Date()
            });

            if (error) throw error;
        }

        return res.status(200).json({ success: true, message: "8 Years data updated" });
    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
}

// 국토부 API 호출 및 페이지네이션 처리 함수
async function fetchFullPages(endpoint, lawdCd, ym) {
    let pageNo = 1;
    let items = [];
    let totalCount = 0;

    try {
        do {
            const url = `http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/${endpoint}?serviceKey=${GOV_KEY}&LAWD_CD=${lawdCd}&DEAL_YMD=${ym}&pageNo=${pageNo}&numOfRows=100`;
            const response = await fetch(url);
            const text = await response.text();
            
            // XML 파싱 (서버 측 파싱을 위해 간단한 정규식 또는 라이브러리 사용)
            const itemMatches = text.match(/<item>([\s\S]*?)<\/item>/g) || [];
            const pageItems = itemMatches.map(item => {
                const obj = {};
                const fields = item.match(/<([^>]+)>([^<]*)/g) || [];
                fields.forEach(f => {
                    const parts = f.match(/<([^>]+)>([^<]*)/);
                    if (parts) obj[parts[1]] = parts[2];
                });
                return obj;
            });

            if (pageNo === 1) {
                const totalMatch = text.match(/<totalCount>(\d+)<\/totalCount>/);
                totalCount = totalMatch ? parseInt(totalMatch[1]) : 0;
            }

            items = items.concat(pageItems);
            pageNo++;
        } while (items.length < totalCount && totalCount > 0);
    } catch (err) {
        console.error(`Fetch error: \${ym}`, err);
    }
    return items;
}
