export default async function handler(req, res) {
  const { lawdCd, dealYmd, pageNo, numOfRows } = req.query;

  // ✅ process.env.등록한_이름 형식으로 써야 합니다.
  const serviceKey = process.env.PUBLIC_DATA_API_KEY; 
  
  const base = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev';

  // URL 생성 시 인코딩 문제를 방지하기 위해 decodeURIComponent를 사용하는 것이 안전합니다.
  const url = `${base}?serviceKey=${serviceKey}&LAWD_CD=${lawdCd}&DEAL_YMD=${dealYmd}&pageNo=${pageNo || '1'}&numOfRows=${numOfRows || '100'}`;

  try {
    const response = await fetch(url, {
      headers: { 'Accept': 'application/xml' }
    });

    const text = await response.text();
    res.status(200).setHeader('Content-Type', 'application/xml; charset=utf-8').send(text);
  } catch (error) {
    console.error(error);
    // ... 에러 처리 로직 ...
  }
}
