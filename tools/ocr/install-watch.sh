#!/bin/bash
# 세대열람 그림 감시 프로그램을 맥이 켜질 때마다 자동으로 켜 두기 (2026-11-01)
#   설치: bash tools/ocr/install-watch.sh      끄기: bash tools/ocr/install-watch.sh --uninstall
# 로그: ~/Library/Logs/house-ocr.log
# ⚠️ 처음 켜질 때 맥이 "node가 다운로드 폴더에 접근하려고 해요"라고 물으면 허용해 주세요(허용하지 않으면 그림 폴더를 못 읽어요).
set -e
LABEL="com.auction.house-ocr"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"; ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ "$1" = "--uninstall" ]; then launchctl unload "$PLIST" 2>/dev/null || true; rm -f "$PLIST"; echo "자동 실행을 껐어요."; exit 0; fi
NODE="$(command -v node)"; [ -z "$NODE" ] && { echo "node를 찾을 수 없어요. 터미널에서 node가 되는지 확인하세요."; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$NODE</string><string>$ROOT/tools/ocr/watch-house.mjs</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/house-ocr.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/house-ocr.log</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin</string></dict>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true; launchctl load "$PLIST"
echo "켰어요. 이제 확장프로그램이 세대열람 그림을 저장하면 자동으로 앱에 반영돼요. 로그: ~/Library/Logs/house-ocr.log"
