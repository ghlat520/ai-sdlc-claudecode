#!/usr/bin/env bash
# ============================================================
# completeness-check.sh — Static completeness scan
#
# Detects empty function stubs, missing API endpoints,
# frontend-backend contract mismatches, and missing seed data.
#
# Usage: ./scripts/completeness-check.sh <project_dir>
# ============================================================

set -euo pipefail

PROJECT_DIR="${1:?Usage: completeness-check.sh <project_dir>}"
PASSED=0
WARNINGS=0
ERRORS=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[CHECK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; ERRORS+=("$*"); }

# ---- Check 1: Empty function bodies in Vue/JS files ----
log "Scanning for empty function bodies..."
EMPTY_FUNCS=$(grep -rn '=> {' "$PROJECT_DIR" --include="*.vue" --include="*.js" --include="*.ts" \
  | grep -E '=> \{\s*(//.*)?$' \
  | grep -v 'node_modules' \
  | grep -v '.nuxt' || true)

if [ -n "$EMPTY_FUNCS" ]; then
  fail "Found empty function bodies (B-Stub defects):"
  echo "$EMPTY_FUNCS" | head -20
else
  log "No empty function bodies found."
  PASSED=$((PASSED + 1))
fi

# ---- Check 2: TODO/FIXME in generated code ----
log "Scanning for TODO/FIXME placeholders..."
TODOS=$(grep -rn 'TODO\|FIXME\|HACK\|XXX' "$PROJECT_DIR" --include="*.vue" --include="*.js" --include="*.java" \
  | grep -v 'node_modules' \
  | grep -v '.git' \
  | grep -v 'target/' || true)

if [ -n "$TODOS" ]; then
  TODO_COUNT=$(echo "$TODOS" | wc -l | tr -d ' ')
  warn "Found $TODO_COUNT TODO/FIXME placeholders:"
  echo "$TODOS" | head -10
else
  log "No TODO/FIXME found."
  PASSED=$((PASSED + 1))
fi

# ---- Check 3: Frontend API calls vs Backend endpoints ----
log "Checking frontend-backend API contract alignment..."

# Extract frontend API paths
FRONTEND_APIS=$(grep -rhoP "request\.(get|post|put|delete)\(['\"]([^'\"]+)['\"]" "$PROJECT_DIR" --include="*.js" --include="*.vue" \
  | grep -v 'node_modules' \
  | sed "s/request\.\(get\|post\|put\|delete\)(['\"]//;s/['\"].*//" \
  | sort -u 2>/dev/null || true)

# Extract backend API paths
BACKEND_APIS=$(grep -rhoP '@(Get|Post|Put|Delete|Request)Mapping\([^)]*"([^"]+)"' "$PROJECT_DIR" --include="*.java" \
  | grep -v 'target/' \
  | sed 's/@.*Mapping([^"]*"//;s/".*//' \
  | sort -u 2>/dev/null || true)

if [ -n "$FRONTEND_APIS" ] && [ -n "$BACKEND_APIS" ]; then
  # Normalize paths for comparison
  FRONTEND_NORMALIZED=$(echo "$FRONTEND_APIS" | sed 's|^/api||;s|^/v1||;s|/[0-9]*$||' | sort -u)
  BACKEND_NORMALIZED=$(echo "$BACKEND_APIS" | sed 's|^/api||;s|^/v1||' | sort -u)

  MISSING=$(comm -23 <(echo "$FRONTEND_NORMALIZED") <(echo "$BACKEND_NORMALIZED") 2>/dev/null || true)
  if [ -n "$MISSING" ]; then
    fail "Frontend calls APIs that backend doesn't have (A-Contract defects):"
    echo "$MISSING" | head -10
  else
    log "All frontend API paths have matching backend endpoints."
    PASSED=$((PASSED + 1))
  fi
else
  warn "Could not extract API paths for contract comparison."
fi

# ---- Check 4: Seed data coverage ----
log "Checking seed data coverage..."

SQL_FILES=$(find "$PROJECT_DIR" -name "*.sql" -not -path "*/target/*" -not -path "*/node_modules/*" 2>/dev/null || true)
if [ -n "$SQL_FILES" ]; then
  # Extract tables from CREATE TABLE
  TABLES=$(grep -rhoP 'CREATE TABLE\s+(IF NOT EXISTS\s+)?`?(\w+)`?' $SQL_FILES \
    | sed 's/CREATE TABLE\s*\(IF NOT EXISTS\s*\)\?`\?//;s/`\?.*//' \
    | sort -u 2>/dev/null || true)

  # Extract tables that have INSERT statements
  SEEDED_TABLES=$(grep -rhoP 'INSERT INTO\s+`?(\w+)`?' $SQL_FILES \
    | sed 's/INSERT INTO\s*`\?//;s/`\?.*//' \
    | sort -u 2>/dev/null || true)

  if [ -n "$TABLES" ] && [ -n "$SEEDED_TABLES" ]; then
    MISSING_SEED=$(comm -23 <(echo "$TABLES") <(echo "$SEEDED_TABLES") 2>/dev/null || true)
    if [ -n "$MISSING_SEED" ]; then
      warn "Tables without seed data (C-Data defects):"
      echo "$MISSING_SEED"
    else
      log "All tables have seed data."
      PASSED=$((PASSED + 1))
    fi
  fi
else
  warn "No SQL files found."
fi

# ---- Check 5: hardcoded demo data ----
log "Checking for hardcoded demo data..."
HARDCODED=$(grep -rn 'Promise.resolve\|hardcode\|demo.*data\|mock.*data' "$PROJECT_DIR" --include="*.vue" --include="*.js" \
  | grep -v 'node_modules' \
  | grep -v '.git' || true)

if [ -n "$HARDCODED" ]; then
  fail "Found potential hardcoded/mock data:"
  echo "$HARDCODED" | head -10
else
  log "No hardcoded demo data found."
  PASSED=$((PASSED + 1))
fi

# ---- Summary ----
echo ""
echo "============================================"
echo "  COMPLETENESS CHECK RESULTS"
echo "============================================"
log "Passed: $PASSED"
warn "Warnings: $WARNINGS"
if [ ${#ERRORS[@]} -gt 0 ]; then
  fail "Errors: ${#ERRORS[@]}"
  for err in "${ERRORS[@]}"; do
    fail "  - $err"
  done
fi
echo "============================================"

if [ ${#ERRORS[@]} -gt 0 ]; then
  exit 1
else
  exit 0
fi
