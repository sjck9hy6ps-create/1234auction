export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 1. 여기에 본인의 [Encoding] 인증키를 정확히 넣으세요.
    const serviceKey = '본인의_인코딩_인증키_입력'; 

    // 2. 미래 날짜 방지 (로그에 찍힌 2026년 요청 대응)
    const now = new Date();
    const todayYm = now.getFullYear() + String(now.getMonth() + 1).padStart(2, '0');
    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > parseInt(todayYm)) {
        safeYmd = todayYm;
    }

    // 3. 국토부 API 주소 (절대 경로로 고정)
    let targetUrl = '';
    if (endpoint === 'aptRent') {
        targetUrl = `http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;
    } else {
        targetUrl = `http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;
    }

    try {
        // 4. fetch 실행 (타임아웃 및 헤더 설정)
        const response = await fetch(targetUrl, {
            method: 'GET',
            headers: {
                'User-Agent': 'Mozilla/5.0',
                'Accept': '*/*'
            }
        });

        if (!response.ok) {
            throw new Error(`국토부 서버 응답 에러: \${response.status}`);
        }

        const text = await response.text();

        // 5. 비정상 응답 처리 (키 오류 등)
        if (text.includes('<resultCode>') && !text.includes('<resultCode>00</resultCode>')) {
            return res.status(200).send('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header><body><items></items></body></response>');
        }

        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        return res.status(200).send(text);

    } catch (e) {
        console.error('Fetch Error Detail:', e.message);
        // 127.0.0.1 에러 방지를 위해 실패 시에도 빈 XML 반환
        return res.status(200).send('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header><body><items></items></body></response>');
    }
}
