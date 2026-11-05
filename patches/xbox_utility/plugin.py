"""Parche «Utilidades Xbox» para ReForge Studio (API v1)."""


def register(api):
    from .page import XboxUtilityPage
    page = XboxUtilityPage(api)
    api.add_page("main", "✦   Utilidades Xbox", "Utilidades Xbox", page)
    api.add_home_tile("✦", "Utilidades Xbox", "Lotes ISO · Xbox Clásica · GOD · FTP",
                      lambda: api.go("main"))
