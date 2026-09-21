from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule


class Manifest16To17Rule(ManifestVersionRule):
    """Update only the deterministic Odoo major prefix in addon manifests."""

    def __init__(self):
        super().__init__(16, 17)
        self.rule_id = "manifest.version.16_to_17"
        self.evidence = (
            "Official Odoo 16.0 and 17.0 addon manifests at commits "
            "2df25c68396510abdb85f9b94ae0ba73f8cb340d and "
            "5553002ba26972ba855585bfa37b54d4fee1fc56 use their respective major prefixes."
        )
