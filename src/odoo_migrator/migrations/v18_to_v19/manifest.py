from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule


class Manifest18To19Rule(ManifestVersionRule):
    def __init__(self):
        super().__init__(18, 19)
        self.rule_id = "manifest.version.18_to_19"
        self.evidence = (
            "Official Odoo 18.0 and 19.0 addon manifests at commits "
            "3c3e3b3d17cbd98584c7685e607d9085712adfe0 and "
            "dd153b3cb418c2e4d4302ac62398ef95d51c9891 use their respective "
            "major version prefixes. No universal manifest-key or dependency "
            "rename is safe for arbitrary custom addons."
        )
