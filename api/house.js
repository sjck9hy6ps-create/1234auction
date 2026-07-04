export default async function handler(req, res) {
  const { endpoint, lawdCd, dealYmd, pageNo, numOfRows } = req.query;

  const serviceKey = process.env.PUBLIC_DATA_API_KEY;
  const base = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev';

  const url = new URL(base);
  url.searchParams.set('serviceKey', serviceKey);
  url.searchParams.set('LAWD_CD', lawdCd);
  url.searchParams.set('DEAL_YMD', dealYmd);
  url.searchParams.set('pageNo', pageNo || '1');
  url.searchParams.set('numOfRows', numOfRows || '100');

  try {
    const response = await fetch(url.toString(), {
      headers: { Accept: 'application/xml' }
    });

    const text = await response.text();

    res.status(200).setHeader('Content-Type', 'application/xml; charset=utf-8').send(text);
  } catch (error) {
    console.error(error);
    res.status(200).setHeader('Content-Type', 'application/xml; charset=utf-8').send(
      `<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>99</resultCode>
    <resultMsg>ERROR</resultMsg>
  </header>
  <body>
    <items/>
    <numOfRows>0</numOfRows>
    <pageNo>1</pageNo>
    <totalCount>0</totalCount>
  </body>
</response>`
    );
  }
}
