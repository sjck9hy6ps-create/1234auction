import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

function parseCSV(text) {
  const rows = [];
  let cur = '';
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];

    if (ch === '"') {
      if (inQuotes && next === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (!inQuotes && ch === ',') { row.push(cur); cur = ''; continue; }
    if (!inQuotes && ch === '\r') continue;
    if (!inQuotes && ch === '\n') {
      row.push(cur);
      rows.push(row);
      row = [];
      cur = '';
      continue;
    }
    cur += ch;
  }
  if (cur !== '' || row.length > 0) { row.push(cur); rows.push(row); }
  return rows;
}

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
      .from('uploads')
      .download(filePath);

    if (downloadError) throw downloadError;
    if (!data) throw new Error('No file data returned from storage.');

    // EUC-KR 자동 감지 및 디코딩
    const buffer = await data.arrayBuffer();
    let csvText = '';
    try {
      csvText = new TextDecoder('utf-8').decode(buffer);
      if (
        csvText.includes('ï¿½') ||
        csvText.includes('�') ||
        (csvText.charCodeAt(0) > 0x7F && csvText.charCodeAt(0) !== 0xFEFF)
      ) {
        throw new Error('not utf-8');
      }
    } catch {
      csvText = new TextDecoder('euc-kr').decode(buffer);
    }

    // BOM 제거
    if (csvText.charCodeAt(0) === 0xFEFF) csvText = csvText.slice(1);

    // 탭 → 쉼표 변환 (순서 중요: 천단위 콤마 제거보다 먼저)
    csvText = csvText.replace(/\t/g, ',');

    // 천단위 콤마 제거 (예: 61,000 → 61000)
    let prev;
    do {
      prev = csvText;
      csvText = csvText.replace(/(\d+),(\d{3}\b)/g, '$1$2');
    } while (csvText !== prev);

    // 파싱
    const parsed = parseCSV(csvText);
    if (!parsed || parsed.length === 0) return res.status(400).json({ error: 'Empty CSV' });

    // 헤더 탐지: 핵심 컬럼 3개 이상 포함하는 행
    const HEADER_KEYWORDS = ['시군구', '단지명', '계약년월', '거래금액'];
    let headerIndex = parsed.findIndex(r => {
      const joined = r.join('');
      const matchCount = HEADER_KEYWORDS.filter(k => joined.includes(k)).length;
      return matchCount >= 3;
    });
    if (headerIndex === -1) headerIndex = 0;

    // 헤더 파싱 + 앞쪽 빈 컬럼 오프셋 계산
    let headerRow = parsed[headerIndex].map(h => (h || '').replace(/"/g, '').trim());

    let colOffset = 0;
    while (colOffset < headerRow.length && headerRow[colOffset] === '') colOffset++;
    if (colOffset > 0) headerRow = headerRow.slice(colOffset);

    console.log('=== headerIndex:', headerIndex);
    console.log('=== colOffset:', colOffset);
    console.log('=== headerRow:', headerRow);

    // 데이터 행 필터: 헤더 컬럼 수 기준
    const headerLen = headerRow.length;
    const linesArr = parsed
      .slice(headerIndex + 1)
      .filter(r => r.length >= headerLen - 2 && r.join('').trim() !== '');

    console.log('=== 데이터 행 수:', linesArr.length);
    console.log('=== 첫 번째 데이터 행:', linesArr[0]);

    const rowsToInsert = linesArr.map(values => {
      // 앞쪽 빈 컬럼 오프셋 적용
      const offsetValues = colOffset > 0 ? values.slice(colOffset) : values;

      const row = {};
      headerRow.forEach((header, i) => {
        const val = (offsetValues[i] || '').replace(/"/g, '').trim();
        row[header] = val;

        // 동의어 자동 설정
        if (header === '번지') row['지번'] = row['지번'] || val;
        if (header === '지번') row['번지'] = row['번지'] || val;
        if (header === '전용면적(㎡)') row['전용면적'] = row['전용면적'] || val;
        if (header === '전용면적') row['전용면적(㎡)'] = row['전용면적(㎡)'] || val;
        if (header === '거래금액(만원)') row['거래금액'] = row['거래금액'] || val;
        if (header === '거래금액') row['거래금액(만원)'] = row['거래금액(만원)'] || val;
      });

      const toInt = (val) => {
        const cleaned = String(val || '').replace(/[^0-9]/g, '');
        return cleaned ? parseInt(cleaned, 10) : 0;
      };

      const subNumValue = toInt(getField(row, '부번'));

      return {
        region:     getField(row, '시군구'),
        bunji:      getField(row, '번지', '지번'),
        road_name:  getField(row, '도로명'),
        main_num:   toInt(getField(row, '본번')),
        sub_num:    subNumValue === 0 ? null : subNumValue,
        danji:      getField(row, '단지명'),
        floor:      toInt(getField(row, '층')),
        size:       Math.floor(parseFloat(getField(row, '전용면적(㎡)', '전용면적') || '') || 0),
        deal_date:  (getField(row, '계약년월') || '') + (String(getField(row, '계약일') || '').padStart(2, '0')),
        price:      toInt(getField(row, '거래금액(만원)', '거래금액')),
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
