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

// 헤더 동의어 조회 유틸
function getField(rowObj, ...names) {
  for (const n of names) {
    if (rowObj[n] !== undefined && rowObj[n] !== '') return rowObj[n];
  }
  return '';
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
    // 탭으로 구분된 파일 처리: 탭을 쉼표로 변환
    csvText = csvText.replace(/\t/g, ',');

    // 파싱
    const parsed = parseCSV(csvText); // 배열의 배열
    if (!parsed || parsed.length === 0) return res.status(400).json({ error: 'Empty CSV' });

    // 1) 헤더 행 자동 탐지: '시군구'와 '번지'를 포함하는 행을 헤더로 사용
    let headerIndex = parsed.findIndex(r => r.join('').includes('시군구') && r.join('').includes('번지'));
    if (headerIndex === -1) headerIndex = 0;
    const headerRow = parsed[headerIndex].map(h => (h || '').replace(/"/g, '').trim());
    const linesArr = parsed.slice(headerIndex + 1).filter(r => r.join('').trim() !== '');

    const rowsToInsert = linesArr.map(values => {
      const row = {};
      headerRow.forEach((header, i) => {
        row[header] = (values[i] || '').replace(/"/g, '').trim();
      });

      const toInt = (val) => parseInt(String(val || '').replace(/[^0-9]/g, '')) || 0;

      const subNumValue = toInt(getField(row, '부번'));

      return {
        region: getField(row, '시군구'),
        bunji: getField(row, '번지', '지번'),
        road_name: getField(row, '도로명'),
        main_num: toInt(getField(row, '본번')),
        sub_num: subNumValue === 0 ? null : subNumValue,
        danji: getField(row, '단지명'),
        floor: toInt(getField(row, '층')),
        size: Math.floor(parseFloat(getField(row, '전용면적(㎡)', '전용면적') || '') || 0),
        deal_date: (getField(row, '계약년월') || '') + (String(getField(row, '계약일') || '').padStart(2, '0')),
        price: toInt(getField(row, '거래금액(만원)', '거래금액')),
        build_year: toInt(getField(row, '건축년도'))
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
