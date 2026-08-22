from __future__ import annotations

import argparse
import asyncio
import json

from .connectors import WebConnectionCounterConnector
from .models import ConnectionSettings, ScanMode
from .service import ProfilerService
from .snmp_client import PySnmpCollector, SnmpCollectionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan one bizhub Office device over SNMP")
    parser.add_argument("host", help="IP address or hostname")
    parser.add_argument("--community", default="public", help="SNMP read community")
    parser.add_argument("--port", type=int, default=161)
    parser.add_argument("--version", choices=("1", "2c", "3"), default="2c")
    parser.add_argument("--mode", choices=("quick", "deep"), default="quick")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--v3-user", default="")
    parser.add_argument("--v3-security", choices=("noAuthNoPriv", "authNoPriv", "authPriv"), default="authPriv")
    parser.add_argument("--v3-auth-password", default="")
    parser.add_argument("--v3-priv-password", default="")
    parser.add_argument("--v3-context", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        settings = ConnectionSettings(
            host=args.host,
            community=args.community,
            port=args.port,
            version=args.version,
            timeout=args.timeout,
            retries=args.retries,
            v3_username=args.v3_user,
            v3_security_level=args.v3_security,
            v3_auth_password=args.v3_auth_password,
            v3_priv_password=args.v3_priv_password,
            v3_context=args.v3_context,
        )
        snapshot = asyncio.run(
            ProfilerService(
                PySnmpCollector(scan_mode=ScanMode(args.mode)),
                WebConnectionCounterConnector(),
            ).scan(settings)
        )
    except (ValueError, SnmpCollectionError) as err:
        print(f"Error: {err}")
        return 1
    print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
