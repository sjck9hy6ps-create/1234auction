import { createClient } from '@supabase/supabase-js';
import formidable from 'formidable';
import fs from 'fs';
import { parse } from 'csv-parse';

export const config = { api: { bodyParser: false } };

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY;
const PREVIEW_ROWS = parseInt(process.env.UPLOAD_PREVIEW_ROWS || '100', 10);

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

function parseFirstN(filePath, n){
  return new Promise((resolve, reject) => {
    const rows = [];
    let headers = null;
    const parser = fs.createReadStream(filePath)
      .pipe(parse({ bom: true, trim: true })) // no header: we'll use first row as header if present
      .on('error', err => reject(err))
      .on('data', (record) => {
        if(!headers){
          headers = record; // treat first row as header
          return;
        }
        const obj = {};
        for(let i=0;i<headers.length;i++) obj[headers[i]] = record[i] ?? '';
        rows.push(obj);
        if(rows.length >= n){
          parser.destroy(); // stop reading further
        }
      })
      .on('end', () => resolve({ headers, rows }));
  });
}

function mapRowToDb(r){
  // 단순 매핑: CSV 헤더명에 따라 필요한 필드 추출(예시)
  const get = k => r[k] ?? r[k?.toLowerCase?.()] ?? '';
  const ym = String(get('계약년월')||get('계약년월')||'').trim();
  const year = ym.length>=4? parseInt(ym.slice(0,4),10): null;
  const month = ym.length>=6? parseInt(ym.slice(4,6),10): null;
  const amountRaw = String(get('거래금액(만원)')||get('거래금액')||get('거래금액(만원)')||'').replace(/,/g,'').trim();
  const areaRaw = String(get('전용면적(㎡)')||get('전용면적')||'').replace(/,/g,'').trim();
  return {
    lawd_cd: null,
    sigungu: get('시군구') || '',
    bunji: get('번지') || '',
    bonbun: get('본번') || '',
    bubun: get('부번') || '',
    apartment_name: get('단지명') || '',
    exclusive_area: areaRaw===''? null: Number(areaRaw),
    deal_year: year,
    deal_month: month,
    deal_day: parseInt(get('계약일')||'0',10) || null,
    deal_amount: amountRaw===''? null: Number(amountRaw),
    dong: get('동') || '',
    floor: get('층') || '',
    buyer: get('매수자') || '',
    seller: get('매도자') || '',
    build_year: get('건축년도') || '',
    road_name: get('도로명') || '',
    cancel_date: get('해제사유발생일') || '',
    deal_type: get('거래유형') || '',
    agency: get('중개사소재지') || '',
    regist_date: get('등기일자') || '',
  };
}

export default async function handler(req, res){
  if(req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const form = formidable({ multiples: false });
  form.parse(req, async (err, fields, files) => {
    if(err) return res.status(500).json({ error: err.message });
    const file = files.file;
    if(!file) return res.status(400).json({ error: 'file required' });

    try{
      const tmpPath = file.filepath || file.path;
      const originalName = file.originalFilename || file.name || 'upload.csv';
      const destName = `${Date.now()}_${originalName}`;

      // 1) Supabase Storage에 업로드
      const fileBuffer = fs.readFileSync(tmpPath);
      const { data: uploadData, error: uploadErr } = await supabase.storage
        .from('uploads')
        .upload(destName, fileBuffer, { contentType: file.mimetype || 'text/csv' });
      if(uploadErr) throw uploadErr;

      // 2) 임시파일에서 첫 PREVIEW_ROWS 파싱
      const { headers, rows } = await parseFirstN(tmpPath, PREVIEW_ROWS);

      // 3) rows를 DB 매핑 및 upsert (간단 예시: 바로 upsert)
      const mapped = rows.map(mapRowToDb);

      // 로컬 중복 제거(간단)
      const uniq = [];
      const seen = new Set();
      mapped.forEach(item=>{
        const key = `${item.sigungu||''}-${item.deal_year||''}-${item.deal_month||''}-${item.deal_day||''}-${(item.apartment_name||'').trim()}-${item.exclusive_area||''}-${item.floor||''}`;
        if(!seen.has(key)){ seen.add(key); uniq.push(item); }
      });

      // Supabase upsert (테이블명: house_trades, onConflict는 미리 설정 필요)
      const { error: upsertErr } = await supabase.from('house_trades')
        .upsert(uniq, { onConflict: 'lawd_cd,deal_year,deal_month,deal_day,apartment_name,exclusive_area,floor' });

      if(upsertErr) throw upsertErr;

      // (선택) public URL
      const { publicURL } = supabase.storage.from('uploads').getPublicUrl(uploadData.path);

      return res.status(200).json({
        success: true,
        uploaded_path: uploadData.path,
        public_url: publicURL,
        preview_rows: rows.length,
        inserted_rows: uniq.length
      });
    }catch(e){
      return res.status(500).json({ error: e.message || String(e) });
    }finally{
      // 임시파일 삭제(선택)
      try{ fs.unlinkSync(file.filepath || file.path); }catch(e){}
    }
  });
}
