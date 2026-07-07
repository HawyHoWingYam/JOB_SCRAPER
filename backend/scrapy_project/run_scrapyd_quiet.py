"""Launch scrapyd with Twisted and access log noise suppressed."""

from __future__ import annotations

import logging

from twisted.web import server

logging.getLogger("twisted").setLevel(logging.WARNING)
logging.getLogger("twisted.python.log").setLevel(logging.WARNING)


class QuietSite(server.Site):
    def log(self, request):
        return None


def install_quiet_site() -> None:
    server.Site = QuietSite


def main() -> None:
    install_quiet_site()
    from scrapyd.__main__ import main as scrapyd_main

    scrapyd_main()


if __name__ == "__main__":
    main()
