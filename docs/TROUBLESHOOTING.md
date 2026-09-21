# Troubleshooting

## Git is missing

Install Git for Windows and restart the application so PATH is refreshed. Source acquisition cannot proceed without Git. An existing compatible local source cache can be used offline.

## Source download failed

Check network access and disk permissions. The source manager rejects an unexpected repository origin, dirty cache, corrupt Git directory, or checkout that does not match the configured verified commit. Retry after fixing the cache rather than using an unverified tree.

## Permission denied

Choose a folder where the current Windows user can read the addon project and create its sibling output. Avoid protected Windows installation directories.

## Output already exists

The migrator never deletes an existing output directory. Choose another destination or move the old result yourself after confirming it is no longer needed.

## Mixed addon versions

The scan reports each manifest version. Select the intended source explicitly and confirm the project is meant to be migrated as one coherent release.

## Blocker findings

Blockers represent missing target dependencies/models or other conditions where continuing automatically is unsafe. Review the exact file, object, source/target state, and suggested action before rerunning analysis.

## No available target

The target list is generated from registered adjacent packs. Odoo 19 has no higher target in this release. Downgrades are not supported.

## Static validation versus runtime

Static validation checks source structure, manifests, XML, and dependencies. It does not install the addon, connect to PostgreSQL, render browser screens, or prove business behavior.
