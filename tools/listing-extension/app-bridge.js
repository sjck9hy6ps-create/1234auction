// 앱 탭에서 동작: 백그라운드가 "호가가 도착했어요" 신호를 보내면 앱 페이지에 전달 → 앱이 새로고침 없이 바로 수신함을 처리·화면 갱신
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === 'inbox') window.postMessage({ source: 'hg-ext', type: 'inbox', id: msg.id }, '*');
});

// 앱의 🟦 탱크옥션 버튼(개별 모으기): 앱이 보낸 요청을 백그라운드에 전달하고 결과를 앱에 돌려줌
window.addEventListener('message', (e) => {
  const d = e.data;
  if (e.source !== window || !d || d.source !== 'hg-app' || d.type !== 'collectCase') return;
  try { chrome.runtime.sendMessage({ type: 'collectOne', caseNo: String(d.caseNo || ''), name: String(d.name || '') }, (r) => window.postMessage({ source: 'hg-ext', type: 'collectAck', ok: !chrome.runtime.lastError && !!(r && r.ok) }, '*')); }
  catch (err) { window.postMessage({ source: 'hg-ext', type: 'collectAck', ok: false }, '*'); }
});
