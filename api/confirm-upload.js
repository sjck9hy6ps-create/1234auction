import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    const { fileData, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    const csvText = await fileData.text();
    const parsed = Papa.parse(csvText, { header: true, skipEmptyLines: true });

    const rowsToInsert = parsed.data.map(row => {
      const getV = (fixedName) => {
        const key = Object.keys(row).find(k => k.trim() === fixedName);
        return key ? row[key] : null;
      };

      const toInt = (val) => {
        const num = parseInt(String(val || '0').replace(/[^0-9]/g, ''));
        return isNaN(num) ? 0 : num;
      };

      // 부번 처리 로직
      const sNum = toInt(getV('부번'));
      
      // 날짜 처리 로직
      const ym = String(getV('계약년월') || '');
      const d = String(getV('계약일') || '').padStart(2, '0');
      const fDate = ym && d ? ym + d : null;

      return {
        region: getV('시군구'),
        bunji: getV('지번'),
        road_name: getV('도로명'),
        main_num: toInt(getV('본번')),
        sub_num: sNum === 0 ? null : sNum, // 0이면 무시
        danji: getV('단지명'),
        floor: toInt(getV('층')),
        size: Math.floor(parseFloat(String(getV('전용면적') || '0').replace(/,/g, ''))) || 0,
        deal_date: fDate,
        price: toInt(getV('거래금액(만원)')),
        build_year: toInt(getV('건축년도')),
        raw_row: row
      };
    });

    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });
  } catch (error) {
    console.error('Server Error:', error);
    return res.status(500).json({ error: error.message });
  }
}
