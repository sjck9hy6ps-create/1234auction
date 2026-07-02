export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 여기에 본인의 [Encoding] 키를 정확히 입력하세요.
    const serviceKey = '여기에_인코딩된_키를_붙여넣으세요'; 

    const baseUrl = endpoint === 'aptRent' 
        ? 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // Vercel에서 공공데이터 서버로 보낼 전체 URL 조립 (인코딩 중복 방지)
    const fullUrl = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}`;

    try {
        const response = await fetch(fullUrl, {
            method: 'GET',
            headers: {
                'Accept': 'application/xml',
            }
        });

        const text = await response.text();

        // XML 응답이 오지 않고 에러 메시지가 포함된 경우 체크
        if (text.includes('<returnAuthMsg>HTTP_ERROR</returnAuthMsg>') || text.includes('SERVICE_KEY_IS_NOT_REGISTERED_ERROR')) {
            return res.status(401).json({ error: 'API 키 인증 실패. 공공데이터 포털에서 키 활성화를 확인하세요.' });
        }

        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        return res.status(200).send(text);

    } catch (e) {
        console.error('API Fetch Error:', e);
        return res.status(500).json({ error: '공공데이터 서버와 통신할 수 없습니다.' });
    }
}
