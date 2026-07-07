import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;
  if (!filePath) return res.status(400).json({ error: 'Missing filePath' });

  try {
    // 1. Storage에서 파일 다운로드
    const { fileBlob, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    // 2. Blob을 Text로 변환 (가장 안전한 Buffer 방식 사용)
    const arrayBuffer = await fileBlob.arrayBuffer();
    const csvText = Buffer.from(arrayBuffer).toString('utf-8');

    // 3. PapaParse 실행 (결과는 .data에 배열로 들어있음)
    const parsed = Papa.parse(csvText, { 
      header: true, 
      skipEmptyLines: true 
    });

    const rowsToInsert = parsed.data.map(row => {
      const getV = (name) => {
        const key = Object.keys(row).find(k => k.trim() === name);
        return key ? String(row[key]).trim() : '';
      };

      const toInt = (val) => {
        const cleaned = val.replace(/[^0-9]/g, '');
        return parseInt(cleaned) || 0;
      };

      // 부번 처리: 0이면 null
      const sNum = toInt(getV('부번'));
      
      // 날짜 처리: 계약년월(6자리) + 계약일(2자리) = 8자리
      const ym = getV('계약년월');
      const d = getV('계약일').padStart(2, '0');
      const fullDate = (ym && d) ? ym + d : null;

      return {
        region: getV('시군구'),
        bunji: getV('지번'),
        road_name: getV('도로명'),
        main_num: toInt(getV('본번')),
        sub_num: sNum === 0 ? null : sNum,
        danji: getV('단지명'),
        floor: toInt(getV('층')),
        // 면적: 소수점 버리고 정수로 변환
        size: Math.floor(parseFloat(getV('전용면적')) || 0),
        deal_date: fullDate,
        price: toInt(getV('거래금액(만원)')),
        build_year: toInt(getV('건축년도'))
      };
    });

    // 4. DB Insert
    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    console.error('Server Error:', error.message);
    return res.status(500).json({ error: error.message });
  }
}
