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

    // 탭 → 쉼표 변환
    csvText = csvText.replace(/\t/g, ',');

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

    // ✅ 각 컬럼 절대 인덱스 확보
    const IDX = {
      region:    headerRow.indexOf('시군구'),
      bunji:     headerRow.indexOf('번지') !== -1 ? headerRow.indexOf('번지') : headerRow.indexOf('지번'),
      mainNum:   headerRow.indexOf('본번'),
      subNum:    headerRow.indexOf('부번'),
      danji:     headerRow.indexOf('단지명'),
      size:      headerRow.indexOf('전용면적(㎡)') !== -1 ? headerRow.indexOf('전용면적(㎡)') : headerRow.indexOf('전용면적'),
      yearMonth: headerRow.indexOf('계약년월'),
      day:       headerRow.indexOf('계약일'),
      price:     headerRow.indexOf('거래금액(만원)') !== -1 ? headerRow.indexOf('거래금액(만원)') : headerRow.indexOf('거래금액'),
      floor:     headerRow.indexOf('층'),
      buildYear: headerRow.indexOf('건축년도'),
      roadName:  headerRow.indexOf('도로명'),
    };

    console.log('=== headerIndex:', headerIndex);
    console.log('=== colOffset:', colOffset);
    console.log('=== headerRow:', headerRow);
    console.log('=== IDX:', IDX);

    // 데이터 행 필터: 완전히 빈 행만 제거 (컬럼 수 조건 제거)
    const linesArr = parsed
      .slice(headerIndex + 1)
      .filter(r => r.join('').trim() !== '');

    console.log('=== 데이터 행 수:', linesArr.length);
    console.log('=== 첫 번째 데이터 행:', linesArr[0]);

    const toInt = (val) => {
      const cleaned = String(val || '').replace(/,/g, '').replace(/[^0-9]/g, '');
      return cleaned ? parseInt(cleaned, 10) : 0;
    };

    const rowsToInsert = linesArr.map(values => {
      // 앞쪽 빈 컬럼 오프셋 적용
      const v = colOffset > 0 ? [...values.slice(colOffset)] : [...values];

      // ✅ 절대 인덱스로 값 꺼내기
      const get = (idx) => idx !== -1 ? (v[idx] || '').replace(/"/g, '').trim() : '';

      // ✅ 단지명: danji ~ size 사이 값을 전부 합침 (쉼표 포함 단지명 대응)
      let danjiVal = '';
      if (IDX.danji !== -1 && IDX.size !== -1 && IDX.size > IDX.danji + 1) {
        danjiVal = v.slice(IDX.danji, IDX.size).join(',').replace(/"/g, '').trim();
      } else {
        danjiVal = get(IDX.danji);
      }

      // ✅ 뒤쪽 컬럼들은 단지명 길이 보정 없이 절대 인덱스 기준으로 뒤에서부터 역산
      // (단지명이 N칸 늘어났으면 뒤 컬럼도 N칸 밀림 → 뒤에서부터 고정 오프셋으로 꺼냄)
      const totalCols = v.length;
      const tailOffset = totalCols - (headerRow.length - IDX.size);

      const getTail = (idx) => {
        if (idx === -1) return '';
        const tailIdx = tailOffset + (idx - IDX.size);
        return tailIdx >= 0 && tailIdx < totalCols
          ? (v[tailIdx] || '').replace(/"/g, '').trim()
          : '';
      };

      const subNumValue = toInt(getTail(IDX.subNum) || get(IDX.subNum));

      // 단지명 이전 컬럼은 절대 인덱스 그대로, 이후는 getTail 사용
      return {
        region:     get(IDX.region),
        bunji:      get(IDX.bunji),
        road_name:  getTail(IDX.roadName),
        main_num:   toInt(get(IDX.mainNum)),
        sub_num:    toInt(get(IDX.subNum)) === 0 ? null : toInt(get(IDX.subNum)),
        danji:      danjiVal,
        floor:      toInt(getTail(IDX.floor)),
        size:       Math.floor(parseFloat(getTail(IDX.size)) || 0),
        deal_date:  getTail(IDX.yearMonth) + String(getTail(IDX.day)).padStart(2, '0'),
        price:      toInt(getTail(IDX.price)),
        build_year: toInt(getTail(IDX.buildYear)),
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
