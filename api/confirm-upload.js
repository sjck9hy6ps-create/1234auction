import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    // 1. [수정] 불확실한 변수명 대신 Supabase 표준인 'data'를 사용
    const { data, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    // 2. [수정] data가 확실히 있을 때만 text() 호출
    const csvText = await data.text();
    const parsed = Papa.parse(csvText, { header: true, skipEmptyLines: true });

    const rowsToInsert = parsed.data.map(row => {
      // 안전하게 값을 가져오는 최소한의 기능
      const getRaw = (key) => {
        const actualKey = Object.keys(row).find(k => k.trim() === key);
        return actualKey ? String(row[actualKey]).trim() : '';
      };

      // 숫자로 변환하는 최소한의 기능
      const getNum = (key) => {
        const val = getRaw(key).replace(/[^0-9]/g, '');
        return val ? parseInt(val) : 0;
      };

      // [부번 로직] 변수 선언 없이 바로 처리하여 충돌 방지
      const subNum = getNum('부번');

      return {
        region: getRaw('시군구'),
        bunji: getRaw('지번'),
        road_name: getRaw('도로명'),
        main_num: getNum('본번'),
        // 부번이 0이면 null, 아니면 숫자 저장
        sub_num: subNum === 0 ? null : subNum, 
        danji: getRaw('단지명'),
        floor: getNum('층'),
        size: Math.floor(parseFloat(getRaw('전용면적')) || 0),
        deal_date: getRaw('계약년월') + getRaw('계약일').padStart(2, '0'),
        price: getNum('거래금액(만원)'),
        build_year: getNum('건축년도')
      };
    });

    const { error: insertError } = await supabase.from('real_estate_trades').insert(rowsToInsert);
    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    // 서버가 죽지 않도록 모든 에러를 JSON으로 포착
    return res.status(500).json({ error: error.message });
  }
}
