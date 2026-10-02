"""Apply the opt-in network guard to pytest and inherited Python children."""

import os

if os.environ.get("KOMI_CI_NETWORK") == "loopback":
    from local_network import install

    install()
