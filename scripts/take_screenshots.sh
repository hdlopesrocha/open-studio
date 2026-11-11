#!/usr/bin/env bash
# Capture one screenshot per sub-page from the demo build.
# Requires Google Chrome or Chromium on the host. The demo build uses bundled
# sample data, so no backend or model has to run.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="${CHROME:-$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)}"
if [ -z "$CHROME" ]; then
    echo "Google Chrome/Chromium not found. Install it or set CHROME=/path/to/chrome." >&2
    exit 1
fi

PORT="${SCREENSHOT_PORT:-8099}"
OUT="docs/screenshots"
mkdir -p "$OUT"
cd frontend
if [ ! -d node_modules ]; then npm install --silent; fi
npm run build:demo >/dev/null
VITE_API_PROXY="${SCREENSHOT_API_PROXY:-http://127.0.0.1:9}" \
    npx vite preview --host 127.0.0.1 --port "$PORT" >/tmp/openstudio-preview.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
    curl -fsS "http://127.0.0.1:$PORT/" >/dev/null 2>&1 && break
    sleep 0.5
done

shoot() {
    local route="$1" name="$2" height="${3:-1200}"
    echo "  capturing $name..."
    "$CHROME" --headless=new --no-sandbox --disable-dev-shm-usage --hide-scrollbars \
        --window-size=1600,"$height" --force-device-scale-factor=1 \
        --virtual-time-budget=4500 --user-data-dir="/tmp/openstudio-chrome-$name" \
        --screenshot="$PWD/../$OUT/$name.png" \
        "http://127.0.0.1:$PORT$route" >/dev/null 2>&1 || true
}

echo "Capturing Open Studio screenshots on port $PORT..."
shoot "/" dashboard 1100
shoot "/setup?demo-auth=setup" setup 1000
shoot "/login?demo-auth=login" login 1000
shoot "/music" music 1200
shoot "/video" video 1200
shoot "/voice" voice 1200
shoot "/subtitles" subtitles 1200
shoot "/images" images 1200
shoot "/documents" documents 1200
shoot "/translate" translate 1000
shoot "/summary" summary 1000
shoot "/ffmpeg" ffmpeg 1200
shoot "/ytdlp" ytdlp 1200
shoot "/qvac" qvac 1200
shoot "/files" files 1000
shoot "/jobs" jobs 1100
shoot "/settings" settings 1000

echo "Screenshots written to $OUT"
