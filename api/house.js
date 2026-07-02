export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 1. 여기에 본인의 [Encoding] 인증키를 정확히 넣으세요.
    const serviceKey = '본인의_인코딩_인증키_입력'; 

    // 2. 날짜 안전장치 (미래 날짜 방지)
    const now = new Date();
    const todayYm = now.getFullYear() + String(now.getMonth() + 1).padStart(2, '0');
    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > parseInt(todayYm)) {
        safeYmd = todayYm;
    }

    // 3. 국토부 API 주소 설정
    const baseUrl = endpoint === 'aptRent' 
        ? 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // 4. URL 조립 (가장 안전한 방식)
    // 키가 이미 인코딩되어 있으므로 중복 인코딩을 방지하기 위해 템플릿 리터럴로 직접 조립합니다.
    const targetUrl = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;

    try {
        const response = await fetch(targetUrl);
        
        if (!response.ok) {
            throw new Error(`국토부 서버 응답 오류: \${response.status}`);
        }

        const text = await response.text();

        // 5. 공공데이터 포털 에러 메시지 처리
        if (text.includes('<resultCode>') && !text.includes('<resultCode>00</resultCode>')) {
            console.error('국토부 API 에러:', text);
            return res.status(200).send('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header><body><items></items></body></response>');
        }

        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        return res.status(200).send(text);

    } catch (e) {
        console.error('Fetch Error:', e.message);
        // 에러 발생 시에도 빈 XML을 반환하여 지도가 멈추지 않게 함
        return res.status(200).send('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header><body><items></items></body></response>');
    }
}
