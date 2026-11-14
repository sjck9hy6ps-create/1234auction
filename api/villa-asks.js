/* ════════════════════════════════════
   빌라 주변 호가 수신 (2026-11-14)
   크롬 확장이 네이버 부동산 지도 목록(연립/다세대)을 읽어 보낸 스냅샷을 Supabase Storage(비공개 data 버킷)에
   asks/villa/<날짜>/<시각>-<무작위>.json 로 쌓습니다. 읽는 쪽(검증·계산)은 GitHub Actions가 목록을 받아 집계합니다.
   스냅샷 = { at, lat, lon, zoom, url, items: [ 줄 묶음 문자열 ] } - 한 지도 화면 안의 호가 목록 원문(해석은 나중에 python이 함)
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') { res.setHeader('Access-Control-Allow-Methods', 'POST'); res.setHeader('Access-Control-Allow-Headers', 'Content-Type'); return res.status(204).end(); }
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  const b = req.body || {};
  const lat = Number(b.lat), lon = Number(b.lon), zoom = Number(b.zoom);
  if (!(lat > 33 && lat < 39 && lon > 124 && lon < 132)) return res.status(400).json({ error: '지도 중심 좌표가 필요해요(주소창의 ms=위도,경도,확대)' });
  const items = Array.isArray(b.items) ? b.items.map((x) => String(x || '').slice(0, 600)).filter((x) => /매매/.test(x)).slice(0, 600) : [];
  if (!items.length) return res.status(400).json({ error: '매매 호가 줄이 없어요' });
  const now = new Date();
  const day = now.toISOString().slice(0, 10);
  const path = `asks/villa/${day}/${now.toISOString().replace(/[:.]/g, '')}-${Math.random().toString(36).slice(2, 7)}.json`;
  const body = JSON.stringify({ at: now.toISOString(), lat, lon, zoom: isFinite(zoom) ? zoom : null, url: String(b.url || '').slice(0, 300), enc: String(b.enc || '').slice(0, 40), n: items.length, items });
  try {
    const { error } = await supabase.storage.from('data').upload(path, body, { contentType: 'application/json', upsert: false });
    if (error) return res.status(500).json({ error: error.message });
    return res.status(200).json({ ok: true, path, n: items.length });
  } catch (e) { return res.status(500).json({ error: String(e && e.message || e) }); }
}
