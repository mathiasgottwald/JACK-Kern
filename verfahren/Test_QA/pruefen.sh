#!/bin/bash
# Abnahme-Muster fuer Playbook "Test_QA" (F-74). Aufruf: pruefen.sh (aus der JACK-Wurzel)
set -u
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JACK="$(cd "$HIER/../.." && pwd)"
cd "$JACK" || exit 1
python3 -m unittest discover -s abnahme -p "test_*.py" > /tmp/f74_test_qa_lauf.log 2>&1
CODE=$?
if [ $CODE -ne 0 ]; then
  echo "BEFUND: Testsuite nicht gruen (Exit $CODE) - siehe /tmp/f74_test_qa_lauf.log" >&2
  tail -20 /tmp/f74_test_qa_lauf.log >&2
  exit 1
fi
echo "Test_QA: Testsuite gruen."
exit 0
