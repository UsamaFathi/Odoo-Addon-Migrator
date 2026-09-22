# Ubuntu installation

Odoo Addon Migrator supports Ubuntu x86_64 with two distribution formats.

## Recommended: Debian package

Download the latest `.deb` package and install it with:

```bash
sudo apt install ./OdooAddonMigrator_*-amd64.deb
```

After installation, launch **Odoo Addon Migrator** from the applications menu or run:

```bash
odoo-addon-migrator
```

The package installs the application under `/opt/odoo-addon-migrator`, adds a launcher under `/usr/bin`, and installs a desktop-menu entry and icon.

## Portable build

Download `OdooAddonMigrator-Ubuntu-x86_64.tar.gz`, then:

```bash
tar -xzf OdooAddonMigrator-Ubuntu-x86_64.tar.gz
cd OdooAddonMigrator
./OdooAddonMigrator
```

If the executable bit was removed during transfer:

```bash
chmod +x OdooAddonMigrator
```

## Odoo source acquisition

Git is recommended when the app needs to download verified official Odoo Community snapshots:

```bash
sudo apt install git
```

Git is not required when every required Odoo version is configured as a validated **Local Exact Source**.

Local Odoo source folders are read-only inputs: the application does not fetch, reset, clean, or modify them.

## Compatibility

The official Ubuntu binary is built on Ubuntu 22.04 x86_64 to keep the glibc baseline compatible with Ubuntu 22.04 and newer releases such as 24.04.

Static validation does not guarantee runtime Odoo compatibility. Always install and test migrated addons on the target Odoo version before production use.
