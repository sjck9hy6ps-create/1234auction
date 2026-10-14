/* 주간 파이프라인 결과 요약 저장(2026-10-15, 사용자: 주간 파이프라인 확인 결과도 주간 리포트에 띄워줘)
   GitHub Actions 실행(run) 하나의 단계별 성공·실패·소요 시간과, 이번 실행이 만든 결과물(입찰후보·낙찰가 모델·환금성 곡선·입찰 경쟁 점수·허가구역 등)의 갱신 시각을 모아
   leader_follower_cache 'signal|__pipeline__' 에 저장(최근 10회 이력 포함) → 앱 주간 리포트의 '🛠 파이프라인' 탭이 보여줌. */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
const supabase = createClient(process.env.SUPABASE_URL?.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });
const REPO = process.env.GITHUB_REPOSITORY, RUN = process.env.RUN_ID || process.env.GITHUB_RUN_ID, TOKEN = process.env.GH_TOKEN;
const gh = (p) => fetch(`https://api.github.com/repos/${REPO}/${p}`, { headers: { Authorization: `Bearer ${TOKEN}`, Accept: 'application/vnd.github+json' } }).then((r) => r.json());
const run = await gh(`actions/runs/${RUN}`);
let jobs = [];
for (let pg = 1; pg <= 3; pg++) { const j = await gh(`actions/runs/${RUN}/jobs?per_page=100&page=${pg}`); jobs = jobs.concat(j.jobs || []); if ((j.jobs || []).length < 100) break; }
const SKIP = /결과 요약 저장|summary/i;
const stages = [];
// 호출된 워크플로의 작업 이름은 "단계 이름 / 작업 이름" 모양 - 단계 이름(앞부분)으로 묶음
const by = new Map();
for (const j of jobs) {
  if (SKIP.test(j.name)) continue;
  const stage = j.name.split(' / ')[0];
  const e = by.get(stage) || { name: stage, start: null, end: null, concl: 'success', status: 'completed', steps: [] };
  if (j.started_at && (!e.start || j.started_at < e.start)) e.start = j.started_at;
  if (j.completed_at && (!e.end || j.completed_at > e.end)) e.end = j.completed_at;
  if (j.status !== 'completed') e.status = j.status;
  if (j.conclusion && j.conclusion !== 'success') e.concl = j.conclusion === 'failure' || e.concl === 'failure' ? 'failure' : j.conclusion;
  for (const st of j.steps || []) if (st.conclusion === 'failure') e.steps.push(st.name);
  by.set(stage, e);
}
for (const e of by.values()) stages.push({ name: e.name, status: e.status, conclusion: e.status === 'completed' ? e.concl : null, start: e.start, end: e.end, minutes: e.start && e.end ? Math.round((new Date(e.end) - new Date(e.start)) / 60000) : null, failedSteps: e.steps.slice(0, 3) });
stages.sort((a, b) => (a.name.match(/^\d+/) ? parseInt(a.name, 10) : 99) - (b.name.match(/^\d+/) ? parseInt(b.name, 10) : 99));
// 결과물 갱신 시각
const ids = ['board|cache|meta', 'board|villa|meta', 'bidscore|meta', 'signal|__winbid__', 'signal|__liqcurve__', 'signal|__weekly_report__', 'signal|__bidval__', 'signal|__permit__', 'signal|__homestay__', 'cycle|__liquidity__'];
const { data: rows } = await supabase.from('leader_follower_cache').select('id,payload,fetched_at').in('id', ids);
const g = Object.fromEntries((rows || []).map((r) => [r.id, r]));
const ts = (r, ...keys) => { if (!r) return null; const p = r.payload || {}; for (const k of keys) { if (p[k]) return typeof p[k] === 'number' ? new Date(p[k]).toISOString() : p[k]; } return r.fetched_at || null; };
const outputs = [
  { name: '입찰후보 계산(아파트)', at: ts(g['board|cache|meta'], 'at'), detail: g['board|cache|meta'] ? (g['board|cache|meta'].payload.count || 0) + '건' : null },
  { name: '입찰후보 계산(빌라)', at: ts(g['board|villa|meta'], 'at'), detail: g['board|villa|meta'] ? (g['board|villa|meta'].payload.count || 0) + '건' : null },
  { name: '입찰 경쟁·매매 활발도 점수', at: ts(g['bidscore|meta'], 'at'), detail: g['bidscore|meta'] ? (g['bidscore|meta'].payload.count || 0) + '건' : null },
  { name: '예상 낙찰가 모델', at: ts(g['signal|__winbid__'], 'generatedAt'), detail: g['signal|__winbid__'] ? '학습 ' + (g['signal|__winbid__'].payload.n || '-') + '건' : null },
  { name: '환금성 곡선', at: ts(g['signal|__liqcurve__'], 'generatedAt'), detail: null },
  { name: '주간 리포트(낙찰 비교)', at: ts(g['signal|__weekly_report__'], 'generatedAt'), detail: null },
  { name: '입찰 경쟁 검증', at: ts(g['signal|__bidval__'], 'generatedAt'), detail: null },
  { name: '토지거래허가구역', at: ts(g['signal|__permit__'], 'refreshedAt', 'checkedAt'), detail: g['signal|__permit__'] ? (Object.keys(g['signal|__permit__'].payload.flagged || {}).length) + '건 허가구역 안' : null },
  { name: '도시민박 집계', at: ts(g['signal|__homestay__'], 'generatedAt'), detail: null },
  { name: '인기·환금성 분석', at: ts(g['cycle|__liquidity__'], 'generatedAt'), detail: null },
];
const startedAt = run.run_started_at || run.created_at, now = new Date().toISOString();
const failed = stages.filter((s) => s.conclusion && s.conclusion !== 'success');
const cur = { runId: Number(RUN), url: run.html_url, event: run.event, startedAt, finishedAt: now, totalMinutes: Math.round((new Date(now) - new Date(startedAt)) / 60000), stages, outputs, ok: failed.length === 0 && stages.length > 0, failedStages: failed.map((s) => s.name) };
const { data: prevRow } = await supabase.from('leader_follower_cache').select('payload').eq('id', 'signal|__pipeline__').maybeSingle();
const hist = ((prevRow && prevRow.payload && prevRow.payload.history) || []).filter((h) => h.runId !== cur.runId);
hist.unshift({ runId: cur.runId, startedAt, totalMinutes: cur.totalMinutes, ok: cur.ok, failedStages: cur.failedStages, stages: stages.length });
const { error } = await supabase.from('leader_follower_cache').upsert({ id: 'signal|__pipeline__', payload: { ...cur, history: hist.slice(0, 10) }, fetched_at: now }, { onConflict: 'id' });
if (error) { console.error('저장 실패:', error.message); process.exit(1); }
console.log(`✅ 파이프라인 요약 저장: ${stages.length}단계, 실패 ${failed.length}, 총 ${cur.totalMinutes}분`);
