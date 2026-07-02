const https = require('https');

export default function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    // 날짜 보정
    let safeYmd = dealYmd;
    if (parseInt(dealYmd) > 202412) safeYmd = '202412';

    // 국토부 API는 http와 https 둘 다 지원하지만, 보안 연결(https)로 시도합니다.
    const baseUrl = endpoint === 'aptRent' 
        ? '/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : '/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

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
        response.on('data', (chunk) => { data += chunk; });
        response.on('end', () => {
            res.setHeader('Content-Type', 'application/xml; charset=utf-8');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.status(200).send(data);
        });
    });

    request.on('error', (e) => {
        console.error('Final Attempt Error:', e.message);
        // 에러 시 빈 XML 반환
        res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
    });

    request.end();
}
