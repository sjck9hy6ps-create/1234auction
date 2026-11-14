// 빌라 호가(0.7.2): 네이버가 페이지를 연 직후 주소의 ms=위도,경도를 암호 같은 글자(예: 2AIWpC,3zk8iO)로 바꿔 버려서, 바뀌기 전(document_start)의 좌표를 탭 안에 기억해 둠.
(function () {
  try {
    const mm = decodeURIComponent(location.href).match(/[?&]ms=(\d{2}\.\d+)[,:](\d{3}\.\d+)(?:[,:](\d+))?/);
    if (mm) sessionStorage.setItem('hg_ms0', JSON.stringify({ lat: +mm[1], lon: +mm[2], z: +(mm[3] || 0), enc: null, at: Date.now() }));
  } catch (e) {}
})();
