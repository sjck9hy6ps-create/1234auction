import { createClient } from '@supabase/supabase-client';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    const { data, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    const csvText = await data.text();
    
    // 라이브러리 없이 CSV 줄 단위로 쪼개기
    const lines = csvText.split('\n');
    const headers = lines[0].split(',').map(h => h.replace(/"/g, '').trim());
    
    const rowsToInsert = lines.slice(1).filter(line => line.trim()).map(line => {
      const values = line.split(',').map(v => v.replace(/"/g, '').trim());
      const row = {};
      headers.forEach((header, i) => { row[header] = values[i] || ''; });

      // 숫자 변환 헬퍼
      const toInt = (val) => parseInt(String(val || '0').replace(/[^0-9]/g, '')) || 0;

      // 부번 로직: 0이면 null
      const sNum = toInt(row['부번']);

      return {
        region: row['시군구'],
        bunji: row['지번'],
        road_name: row['도로명'],
        main_num: toInt(row['본번']),
        sub_num: sNum === 0 ? null : sNum,
        danji: row['단지명'],
        floor: toInt(row['층']),
        // 면적 로직: 소수점 버리고 정수로
        size: Math.floor(parseFloat(row['전용면적']) || 0),
        deal_date: (row['계약년월'] && row['계약일']) ? (row['계약년월'] + row['계약일'].padStart(2, '0')) : null,
        price: toInt(row['거래금액(만원)']),
        build_year: toInt(row['건축년도'])
      };
    });

    const { error: insertError } = await supabase.from('real_estate_trades').insert(rowsToInsert);
    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}
