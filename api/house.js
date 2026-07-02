export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 1. 제공해주신 디코딩 키를 안전하게 인코딩하여 사용합니다.
    const rawKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';
    const serviceKey = encodeURIComponent(rawKey); 

    // 2. 날짜 보정 (미래 날짜 방지 - 2026년 요청 대응)
    const now = new Date();
    const currentYm = now.getFullYear() + String(now.getMonth() + 1).padStart(2, '0');
    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > parseInt(currentYm)) {
        safeYmd = currentYm;
    }

    // 3. API URL 설정
    const baseUrl = endpoint === 'aptRent' 
        ? 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // 4. URL 조립 (serviceKey를 인코딩된 값으로 넣음)
    const targetUrl = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;

    try {
        const response = await fetch(targetUrl, {
            method: 'GET',
            headers: {
                'Accept': 'application/xml'
            }
        });

        const text = await response.text();

        // 인증 에러 메시지가 응답에 포함되어 있는지 확인
        if (text.includes('SERVICE_KEY_IS_NOT_REGISTERED')) {
            console.error('국토부 API 키 미등록 에러');
            return res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>99</resultCode></header><body><items></items></body></response>');
        }

        // 정상 응답 전달
        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        return res.status(200).send(text);

    } catch (e) {
        console.error('Fetch 실패:', e.message);
        return res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
    }
}
