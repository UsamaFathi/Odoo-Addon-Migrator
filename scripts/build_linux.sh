#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_TESTS="${1:-}"
if [[ "$SKIP_TESTS" != "--skip-tests" ]]; then
  python -m pytest -q
fi

python -m pip install -e ".[desktop,build]"

rm -rf build dist/OdooAddonMigrator dist/OdooAddonMigrator-Ubuntu-x86_64.tar.gz
python -m PyInstaller --noconfirm --clean packaging/OdooAddonMigrator-linux.spec

QT_QPA_PLATFORM=offscreen ./dist/OdooAddonMigrator/OdooAddonMigrator --smoke-test

tar -C dist -czf dist/OdooAddonMigrator-Ubuntu-x86_64.tar.gz OdooAddonMigrator

echo "Built:"
echo "  dist/OdooAddonMigrator/OdooAddonMigrator"
echo "  dist/OdooAddonMigrator-Ubuntu-x86_64.tar.gz"
