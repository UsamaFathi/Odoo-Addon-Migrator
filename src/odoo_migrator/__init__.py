from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("odoo-addon-migrator")
except PackageNotFoundError:
    __version__ = "0+unknown"
