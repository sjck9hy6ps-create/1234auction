import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

// 간단하지만 따옴표로 감싼 필드와 쉼표를 처리하는 파서
function parseCSV(text) {
  const rows = [];
  let cur = '';
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];

    if (ch === '"') {
      if (inQuotes && next === '"') { // double quote escape -> add one quote
        cur += '"';
        i++; // skip next
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (!inQuotes && ch === ',') {
      row.push(cur);
      cur = '';
      continue;
    }

    if (!inQuotes && ch === '\r') {
      // ignore, handled on \n
      continue;
    }

    if (!inQuotes && ch === '\n') {
      row.push(cur);
      rows.push(row);
      row = [];
      cur = '';
      continue;
    }

    cur += ch;
  }
  // 마지막 필드/행 처리
  if (cur !== '' || row.length > 0) {
    row.push(cur);
    rows.push(row);
  }
  return rows;
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;
  if (!filePath) return res.status(400).json({ error: 'filePath required' });

  try {
    const { data, error: downloadError } = await supabase.storage
      .from('uploads') // 보드에서 요청하신 대로 'uploads' 사용
      .download(filePath);

    if (downloadError) throw downloadError;
    if (!data) throw new Error('No file data returned from storage.');

    let csvText = (await data.text()) || '';
    // BOM 제거
    if (csvText.charCodeAt(0) === 0xFEFF) csvText = csvText.slice(1);

    // 파싱
    const parsed = parseCSV(csvText); // 배열의 배열
    if (!parsed || parsed.length === 0) return res.status(400).json({ error: 'Empty CSV' });

    const headerRow = parsed[0].map(h => (h || '').replace(/"/g, '').trim());
    const linesArr = parsed.slice(1).filter(r => r.join('').trim() !== '');

    const rowsToInsert = linesArr.map(values => {
      const row = {};
      headerRow.forEach((header, i) => {
        row[header] = (values[i] || '').replace(/"/g, '').trim();
      });

      const toInt = (val) => parseInt(String(val || '').replace(/[^0-9]/g, '')) || 0;

      const subNumValue = toInt(row['부번']);

      return {
        region: row['시군구'] || '',
        bunji: row['지번'] || '',
        road_name: row['도로명'] || '',
        main_num: toInt(row['본번']),
        sub_num: subNumValue === 0 ? null : subNumValue,
        danji: row['단지명'] || '',
        floor: toInt(row['층']),
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
