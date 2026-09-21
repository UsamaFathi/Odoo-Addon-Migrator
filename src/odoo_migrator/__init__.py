from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


try:
    __version__ = version("odoo-addon-migrator")
except PackageNotFoundError:
    try:
        with (Path(__file__).parents[2] / "pyproject.toml").open("rb") as project_file:
            __version__ = tomllib.load(project_file)["project"]["version"]
    except (OSError, KeyError, TypeError):
        __version__ = "0+unknown"
