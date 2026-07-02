export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 1. 여기에 본인의 [Encoding] 인증키를 넣으세요.
    const serviceKey = '본인의_인코딩_인증키_입력'; 

    // 2. 날짜 안전장치: 오늘 날짜 구하기
    const now = new Date();
    const todayYm = now.getFullYear() + String(now.getMonth() + 1).padStart(2, '0');

    // 요청 날짜가 오늘보다 미래면 오늘 날짜로 변경 (500 에러 방지)
    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > parseInt(todayYm)) {
        safeYmd = todayYm;
    }

    const baseUrl = endpoint === 'aptRent' 
        ? 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // 3. URL 생성
    const fullUrl = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;

    try {
        const response = await fetch(fullUrl);
        const text = await response.text();

        // 인증키 에러나 서버 에러가 응답에 포함된 경우
        if (text.includes('<resultCode>') && !text.includes('<resultCode>00</resultCode>')) {
            console.error('국토부 API 응답 에러:', text);
            // 지도가 멈추지 않게 빈 결과를 반환
            return res.status(200).send('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header><body><items></items></body></response>');
        }

        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        return res.status(200).send(text);

    } catch (e) {
        // 통신 자체가 실패한 경우
        return res.status(200).send('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header><body><items></items></body></response>');
    }
}
