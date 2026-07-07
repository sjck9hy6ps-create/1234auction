import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;
  if (!filePath) return res.status(400).json({ error: 'filePath required' });

  try {
    const { data, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;
    if (!data) throw new Error('No file data returned from storage.');

    const csvText = (await data.text()) || ''; // csvText가 빈값이면 빈 문자열로 초기화
    const lines = csvText.split('\n');

    const firstLine = lines[0] || '';
    const headers = firstLine.split(',').map(h => (h || '').replace(/"/g, '').trim());

    const rowsToInsert = lines
      .slice(1)
      .filter(line => line && line.trim())
      .map(line => {
        const values = line.split(',').map(v => (v || '').replace(/"/g, '').trim());
        const row = {};
        headers.forEach((header, i) => {
          row[header] = values[i] || ''; // values[i]가 없을 경우 빈 문자열로 처리
        });

        const toInt = (val) => parseInt(String(val || '').replace(/[^0-9]/g, '')) || 0; // val이 빈값이면 빈 문자열로 처리

        // 1. 부번 처리: 0이면 null (요청 사항)
        const subNumValue = toInt(row['부번']);

        return {
          region: row['시군구'] || '',
          bunji: row['지번'] || '',
          road_name: row['도로명'] || '',
          main_num: toInt(row['본번']),
          sub_num: subNumValue === 0 ? null : subNumValue,
          danji: row['단지명'] || '',
          floor: toInt(row['층']),
          // 2. 면적 처리: 정수화 (요청 사항)
          size: Math.floor(parseFloat(row['전용면적'] || '') || 0),
          deal_date: (row['계약년월'] || '') + (String(row['계약일'] || '').padStart(2, '0')),
          price: toInt(row['거래금액(만원)']),
          build_year: toInt(row['건축년도'])
        };
      });

    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    console.error(error && error.stack ? error.stack : error);
    return res.status(500).json({ error: String(error?.message || error) });
  }
}
