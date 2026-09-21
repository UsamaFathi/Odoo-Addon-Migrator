from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule


class Manifest17To18Rule(ManifestVersionRule):
    def __init__(self):
        super().__init__(17, 18)
        self.rule_id = "manifest.version.17_to_18"
        self.evidence = (
            "Official Odoo 17.0 and 18.0 addon manifests at commits "
            "5553002ba26972ba855585bfa37b54d4fee1fc56 and "
            "3c3e3b3d17cbd98584c7685e607d9085712adfe0 use their respective major prefixes."
        )
