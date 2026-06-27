#!/usr/bin/env bash
# RoleRadar one-command setup (macOS / Linux).
# Creates a virtualenv, installs deps, installs the Playwright browser, and
# prepares your .env. Run from the repo root:   ./setup.sh
#
# Windows teammates: see the "Windows" section in README.md (the steps are the
# same, just with .venv\Scripts\activate instead of source .venv/bin/activate).

set -e  # stop on first error

echo "=== RoleRadar setup ==="

# 1. Find a compatible Python. pyautogen==0.2.35 needs Python 3.9-3.12 (NOT 3.13).
PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    minor=$("$c" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 99)
    major=$("$c" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
    if [ "$major" = "3" ] && [ "$minor" -ge 9 ] && [ "$minor" -le 12 ]; then
      PY="$c"; break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "ERROR: Need Python 3.9-3.12 (found none)."
  echo "       Python 3.13 will NOT work (pyautogen 0.2.x is incompatible)."
  echo "       Install e.g. 'brew install python@3.12' then re-run ./setup.sh"
  exit 1
fi
echo "Using $($PY --version) at $(command -v $PY)"

# 2. Create the virtualenv (in-project .venv; gitignored).
echo "Creating .venv ..."
"$PY" -m venv .venv

# 3. Install dependencies.
echo "Installing Python dependencies ..."
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

# 4. Install the Playwright browser (for JS-heavy career pages).
echo "Installing Playwright Chromium ..."
./.venv/bin/playwright install chromium

# 5. Prepare .env if it doesn't exist yet.
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env created from template — paste the shared Azure key/endpoint into it"
  echo "(or leave blank to run resume analysis in stub mode)."
else
  echo ".env already present — leaving it as-is."
fi

echo ""
echo "=== Done! ==="
echo "Start the app with:   ./.venv/bin/python main.py"
echo "Then open:            http://localhost:8000"
echo "You'll see the shared dataset (seed.db) pre-loaded."
