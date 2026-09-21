import subprocess
import sys


def test_package_import_has_no_tomllib_requirement():
    result = subprocess.run(
        [sys.executable, "-c", "import odoo_migrator; assert odoo_migrator.__version__"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
