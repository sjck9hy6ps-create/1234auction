const https = require('https');

export default function handler(req, res) {
    // index.html에서 넘겨주는 파라미터들
    const { endpoint, lawdCd, dealYmd } = req.query;
    
    // 인증키
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    // 날짜가 없거나 2025년 이후면 최신 데이터가 있는 202412로 고정
    let safeYmd = dealYmd || '202412';
    if (parseInt(safeYmd) > 202412) safeYmd = '202412';

    // 국토부 엔드포인트 설정
    const baseUrl = endpoint === 'aptRent' 
        ? '/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : '/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // 최종 요청 URL 생성 (LAWD_CD, DEAL_YMD 대문자 필수)
    const fullPath = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;

    const options = {
        hostname: 'openapi.molit.go.kr',
        port: 443,
        path: fullPath,
        method: 'GET',
        headers: {
            'User-Agent': 'Mozilla/5.0'
        }
    };

    const request = https.get(options, (response) => {
        let data = '';
        response.setEncoding('utf8');
        response.on('data', (chunk) => { data += chunk; });
        response.on('end', () => {
            // 브라우저에게 XML임을 알림
            res.setHeader('Content-Type', 'application/xml; charset=utf-8');
            res.setHeader('Access-Control-Allow-Origin', '*');
            
            // 데이터가 비어있을 경우 대비
            if (!data || data.includes('INVALID_REQUEST_PARAMETER_ERROR')) {
                return res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode></header><body><items></items></body></response>');
            }
            
            res.status(200).send(data);
        });
    });

    request.on('error', (e) => {
        console.error('House API Error:', e.message);
        res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
    });

    request.end();
}
