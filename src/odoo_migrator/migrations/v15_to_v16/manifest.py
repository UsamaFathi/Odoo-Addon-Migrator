from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule


class Manifest15To16Rule(ManifestVersionRule):
    """Update only the verified major-version prefix in addon manifests."""

    def __init__(self):
        super().__init__(15, 16)
        self.rule_id = "manifest.version.15_to_16"
        self.evidence = (
            "Official Odoo 15.0 and 16.0 addon manifests at commits "
            "3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187 and "
            "2df25c68396510abdb85f9b94ae0ba73f8cb340d use their respective major prefixes."
        )
