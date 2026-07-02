import { fetchAuctionData } from '../utils/fetch-auction';

export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    const baseUrl = 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc';
    const apiPath = endpoint === 'aptRent' 
        ? `/getRTMSDataSvcAptRent`
        : `/getRTMSDataSvcAptTradeDev`;
    
    // URL 뒤에 현재 시간을 붙여서 Vercel의 잘못된 DNS 캐싱을 강제로 회피합니다.
    const fullUrl = `${baseUrl}${apiPath}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}&_t=${Date.now()}`;

    try {
        const data = await fetchAuctionData(fullUrl);
        
        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.status(200).send(data);
    } catch (error) {
        console.error('House API Critical Error:', error.message);
        // 에러 발생 시 빈 값을 주지 않고 500을 줘서 프론트엔드가 재시도하게 하거나 에러를 알게 합니다.
        res.status(500).json({ error: error.message });
    }
}
