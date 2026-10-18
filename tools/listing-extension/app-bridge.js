// 앱 탭에서 동작: 백그라운드가 "호가가 도착했어요" 신호를 보내면 앱 페이지에 전달 → 앱이 새로고침 없이 바로 수신함을 처리·화면 갱신
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === 'inbox') window.postMessage({ source: 'hg-ext', type: 'inbox', id: msg.id }, '*');
});
