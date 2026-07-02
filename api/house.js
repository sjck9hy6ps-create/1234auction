export default async function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 1. 인증키 (인코딩/디코딩 이슈 방지를 위해 직접 입력)
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    // 2. 날짜 보정 (미래 날짜 요청 시 2024년 12월로 고정)
    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > 202506) {
        safeYmd = '202412';
    }

    // 3. API URL 설정 (가장 안정적인 TradeDev 엔드포인트 사용)
    const baseUrl = endpoint === 'aptRent' 
        ? 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : 'http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // 4. URLSearchParams를 사용하여 안전하게 쿼리 스트링 생성
    // (이 방식이 인증키의 특수문자 문제를 가장 잘 해결합니다)
    const params = new URLSearchParams({
        serviceKey: serviceKey,
        LAWD_CD: lawdCd,
        DEAL_YMD: safeYmd
    });

    const targetUrl = `${baseUrl}?${params.toString()}`;

    try {
        const response = await fetch(targetUrl, {
            method: 'GET',
            headers: {
                'Accept': 'application/xml'
            }
        });

        const text = await response.text();

        // 브라우저가 XML로 인식하도록 헤더 설정
        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Access-Control-Allow-Origin', '*');
        
        // 만약 응답이 비어있거나 에러라면 빈 XML 구조라도 보내서 지도가 멈추지 않게 함
        if (!text || text.includes('LIMITED NUMBER OF SERVICE')) {
            return res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode></header><body><items></items></body></response>');
        }

        return res.status(200).send(text);

    } catch (e) {
        console.error('Fetch Error:', e.message);
        return res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
    }
}
