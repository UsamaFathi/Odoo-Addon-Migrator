#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x dist/OdooAddonMigrator/OdooAddonMigrator ]]; then
  echo "Linux application is missing. Run scripts/build_linux.sh first." >&2
  exit 1
fi

PY_VERSION="$(python -c "from importlib.metadata import version; print(version('odoo-addon-migrator'))")"
DISPLAY_VERSION="$(python -c "from odoo_migrator.ui.version import display_version; print(display_version('$PY_VERSION'))")"
DEB_VERSION="$(printf '%s' "$PY_VERSION" | sed -E 's/rc([0-9]+)/~rc\1/')"
ARCH="amd64"
PKG_ROOT="build/deb/odoo-addon-migrator"

rm -rf "$PKG_ROOT"
mkdir -p   "$PKG_ROOT/DEBIAN"   "$PKG_ROOT/opt/odoo-addon-migrator"   "$PKG_ROOT/usr/bin"   "$PKG_ROOT/usr/share/applications"   "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps"

cp -a dist/OdooAddonMigrator/. "$PKG_ROOT/opt/odoo-addon-migrator/"
install -m 0755 packaging/linux/odoo-addon-migrator.sh "$PKG_ROOT/usr/bin/odoo-addon-migrator"
install -m 0644 packaging/linux/odoo-addon-migrator.desktop "$PKG_ROOT/usr/share/applications/odoo-addon-migrator.desktop"
install -m 0644 src/odoo_migrator/ui/assets/migrator.svg "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps/odoo-addon-migrator.svg"

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: odoo-addon-migrator
Version: $DEB_VERSION
Section: devel
Priority: optional
Architecture: $ARCH
Maintainer: Usama Fathi
Depends: libc6, libx11-6, libxcb1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-xinerama0, libdbus-1-3, libgl1, libegl1, libfontconfig1
Recommends: git, xdg-utils
Description: Source-aware migration assistant for custom Odoo addons
 Odoo Addon Migrator analyzes and migrates custom addons across supported
 Odoo Community versions. Local Exact Source mode can operate without Git.
EOF

OUTPUT="dist/OdooAddonMigrator_${DISPLAY_VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUTPUT"

echo "Built $OUTPUT"
