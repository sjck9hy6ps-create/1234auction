const https = require('https');

export default function handler(req, res) {
    const { endpoint, lawdCd, dealYmd } = req.query;
    const serviceKey = 'ca4e98f4254eccbbabfbb3f9f972e17eba48507e804a9ac2bc97260423a090d6';

    let safeYmd = dealYmd || '202412';
    if (parseInt(safeYmd) > 202412) safeYmd = '202412';

    const baseUrl = endpoint === 'aptRent' 
        ? 'https://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent'
        : 'https://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev';

    // 전체 URL을 하나로 합칩니다.
    const finalUrl = `${baseUrl}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${safeYmd}`;

    // https.get에 URL 문자열을 직접 전달하여 DNS 오작동을 방지합니다.
    https.get(finalUrl, (response) => {
        let data = '';
        response.on('data', (chunk) => { data += chunk; });
        response.on('end', () => {
            res.setHeader('Content-Type', 'application/xml; charset=utf-8');
            res.setHeader('Access-Control-Allow-Origin', '*');
            
            if (!data || data.includes('INVALID_REQUEST_PARAMETER_ERROR')) {
                res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
            } else {
                res.status(200).send(data);
            }
        });
    }).on('error', (e) => {
        console.error('Final Network Error:', e.message);
        res.status(200).send('<?xml version="1.0" encoding="UTF-8"?><response><body><items></items></body></response>');
    });
}
