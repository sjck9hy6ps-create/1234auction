/* 옛 빌라 계산 묶음 한 번 지우기(2026-11-25, 사용자 승인): 'board|villa|meta'의 n보다 큰 번호의 묶음만 삭제 */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
const supabase = createClient(process.env.SUPABASE_URL?.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });
const { data: m } = await supabase.from('leader_follower_cache').select('payload').eq('id', 'board|villa|meta').maybeSingle();
const n = m && m.payload && m.payload.n; if (!(n >= 1)) { console.log('meta 없음 - 중단'); process.exit(1); }
const { data: olds } = await supabase.from('leader_follower_cache').select('id').like('id', 'board|villa|%');
const stale = (olds || []).map((o) => o.id).filter((id) => /^board\|villa\|\d+$/.test(id) && Number(id.split('|')[2]) >= n);
console.log(`현재 묶음 ${n}개, 지울 옛 묶음 ${stale.length}개`, stale.join(','));
if (stale.length) { const { error } = await supabase.from('leader_follower_cache').delete().in('id', stale); console.log(error ? '실패 ' + error.message : '삭제 완료'); }
