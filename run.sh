#!/bin/bash
cd "$(dirname "$0")"

# Prefer Homebrew Python (not the SIP-protected system Python)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"

PYTHON=$(command -v python3)

# Install dependencies if needed
if ! "$PYTHON" -c "import flask, weasyprint, pypdf, reportlab" 2>/dev/null; then
  echo "מתקין תלויות..."
  "$PYTHON" -m pip install -r requirements.txt
fi

echo "מפעיל כלי נספחים → http://localhost:5050"
exec "$PYTHON" app.py
