#!/usr/bin/env bash
# ============================================================
# smoke-test.sh — Post-generation integration smoke test
#
# Starts the backend, logs in, and verifies every API endpoint
# returns 200 with non-empty data. Fails fast on any error.
#
# Usage: ./scripts/smoke-test.sh <project_dir>
# Example: ./scripts/smoke-test.sh /path/to/srm-platform
# ============================================================

set -euo pipefail

PROJECT_DIR="${1:?Usage: smoke-test.sh <project_dir>}"
PORT="${SMOKE_TEST_PORT:-8080}"
MAX_WAIT=60
PASSED=0
FAILED=0
ERRORS=()

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[SMOKE]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }

# --- Step 1: Build ---
log "Building project..."
cd "$PROJECT_DIR"
if [ -f "pom.xml" ]; then
  mvn clean install -DskipTests -q 2>&1 | tail -5
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
  ./gradlew build -x test -q 2>&1 | tail -5
else
  fail "No build file found (pom.xml / build.gradle)"
  exit 1
fi
log "Build complete."

# --- Step 2: Start application ---
log "Starting application on port $PORT..."

# Find the runnable jar or module
if [ -f "pom.xml" ]; then
  # Maven multi-module: find the web module
  WEB_JAR=$(find . -path "*/target/*.jar" -name "*-web-*" -o -path "*/target/*.jar" -name "*web*" 2>/dev/null | grep -v sources | head -1)
  if [ -z "$WEB_JAR" ]; then
    WEB_JAR=$(find . -path "*/target/*.jar" -not -name "*-sources.jar" -not -name "original-*" 2>/dev/null | head -1)
  fi
  if [ -z "$WEB_JAR" ]; then
    fail "No runnable JAR found in target/"
    exit 1
  fi
  java -jar "$WEB_JAR" --server.port="$PORT" &
  APP_PID=$!
fi

# Wait for startup
log "Waiting for application to start (max ${MAX_WAIT}s)..."
ELAPSED=0
while ! curl -s -o /dev/null -w "" "http://localhost:$PORT" 2>/dev/null; do
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  if [ $ELAPSED -ge $MAX_WAIT ]; then
    fail "Application failed to start within ${MAX_WAIT}s"
    kill $APP_PID 2>/dev/null || true
    exit 1
  fi
  # Check if process is still alive
  if ! kill -0 $APP_PID 2>/dev/null; then
    fail "Application process died during startup"
    exit 1
  fi
done
log "Application started (${ELAPSED}s)."

# --- Step 3: Login ---
log "Logging in..."
LOGIN_RESPONSE=$(curl -s -X POST "http://localhost:$PORT/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' 2>/dev/null || echo "CURL_FAILED")

if [ "$LOGIN_RESPONSE" = "CURL_FAILED" ]; then
  # Try alternate login path
  LOGIN_RESPONSE=$(curl -s -X POST "http://localhost:$PORT/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}' 2>/dev/null || echo "CURL_FAILED")
fi

TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token','') if isinstance(d.get('data'),dict) else d.get('token',''))" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  warn "Login failed or no token returned. Response: $LOGIN_RESPONSE"
  warn "Continuing without auth token..."
  AUTH_HEADER=""
else
  log "Login successful. Token obtained."
  AUTH_HEADER="Authorization: Bearer $TOKEN"
fi

# --- Step 4: Test endpoints ---
check_endpoint() {
  local method="$1"
  local path="$2"
  local description="$3"
  local expect_data="${4:-true}"

  local url="http://localhost:$PORT${path}"
  local status
  local body

  if [ -n "$AUTH_HEADER" ]; then
    body=$(curl -s -w "\n%{http_code}" -X "$method" -H "$AUTH_HEADER" -H "Content-Type: application/json" "$url" 2>/dev/null)
  else
    body=$(curl -s -w "\n%{http_code}" -X "$method" -H "Content-Type: application/json" "$url" 2>/dev/null)
  fi

  status=$(echo "$body" | tail -1)
  body=$(echo "$body" | sed '$d')

  if [ "$status" = "200" ]; then
    if [ "$expect_data" = "true" ]; then
      # Check for non-empty data
      local has_data
      has_data=$(echo "$body" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  data=d.get('data')
  if data is None: print('empty')
  elif isinstance(data,dict) and 'records' in data: print('ok' if len(data['records'])>0 else 'empty')
  elif isinstance(data,list): print('ok' if len(data)>0 else 'empty')
  elif isinstance(data,(int,float)): print('ok')
  else: print('ok')
except: print('parse_error')
" 2>/dev/null)
      if [ "$has_data" = "empty" ]; then
        warn "$description → 200 but EMPTY data: $path"
        ERRORS+=("EMPTY: $description ($path)")
        FAILED=$((FAILED + 1))
        return
      fi
    fi
    PASSED=$((PASSED + 1))
  else
    fail "$description → HTTP $status: $path"
    ERRORS+=("HTTP $status: $description ($path)")
    FAILED=$((FAILED + 1))
  fi
}

log "Testing API endpoints..."

# Auto-discover endpoints from Controller files if available
if [ -d "$PROJECT_DIR" ]; then
  # Extract API paths from Java controllers
  CONTROLLERS=$(find "$PROJECT_DIR" -name "*Controller.java" -path "*/controller/*" 2>/dev/null)
  if [ -n "$CONTROLLERS" ]; then
    log "Found $(echo "$CONTROLLERS" | wc -l | tr -d ' ') controllers. Extracting endpoints..."

    while IFS= read -r controller; do
      # Extract class-level @RequestMapping
      class_path=$(grep -oP '@RequestMapping\("([^"]+)"\)' "$controller" | grep -oP '"[^"]+"' | tr -d '"' | head -1)
      [ -z "$class_path" ] && class_path=""

      # Extract GET endpoints (list/detail)
      while IFS= read -r line; do
        method_path=$(echo "$line" | grep -oP '"[^"]+"' | tr -d '"')
        full_path="/api${class_path}${method_path}"
        # Skip paths with {id} or export
        if echo "$full_path" | grep -qE '\{|export'; then continue; fi
        controller_name=$(basename "$controller" .java)
        check_endpoint "GET" "$full_path" "$controller_name: GET $full_path"
      done < <(grep -n '@GetMapping' "$controller" 2>/dev/null || true)

      # Check the base list endpoint
      if [ -n "$class_path" ]; then
        check_endpoint "GET" "/api${class_path}" "$(basename "$controller" .java): GET /api${class_path}"
      fi
    done <<< "$CONTROLLERS"
  fi
fi

# --- Step 5: Summary ---
echo ""
echo "============================================"
echo "  SMOKE TEST RESULTS"
echo "============================================"
log "Passed: $PASSED"
if [ $FAILED -gt 0 ]; then
  fail "Failed: $FAILED"
  echo ""
  fail "Failures:"
  for err in "${ERRORS[@]}"; do
    fail "  - $err"
  done
fi
echo "============================================"

# --- Cleanup ---
log "Stopping application..."
kill $APP_PID 2>/dev/null || true
wait $APP_PID 2>/dev/null || true

if [ $FAILED -gt 0 ]; then
  fail "SMOKE TEST FAILED: $FAILED endpoint(s) broken"
  exit 1
else
  log "ALL ENDPOINTS PASSED ($PASSED total)"
  exit 0
fi
