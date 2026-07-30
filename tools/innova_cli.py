#!/usr/bin/env python3
"""Standalone CLI to exercise the Innova FÄRNA cloud protocol (auth + gRPC).

Handy for debugging and for confirming enum values against a real unit. Reuses
the integration's ``api.py`` client (no generated protobuf — messages are built
and parsed by hand there).

    pip install grpcio aiohttp
    python tools/innova_cli.py login    --email you@x.com --password ***
    python tools/innova_cli.py devices  --token <JWT>
    python tools/innova_cli.py get      --token <JWT> --mac AA:BB:CC:DD:EE:FF
    python tools/innova_cli.py set       --token <JWT> --mac AA:BB:CC:DD:EE:FF --power on --temp 22 --mode 3 --fan 1
    # passwordless (Google accounts): request a code, then log in with it
    python tools/innova_cli.py send-code --email you@x.com
    python tools/innova_cli.py code      --email you@x.com --code 123456
"""
import argparse
import asyncio
import os
import sys

# api.py has no Home Assistant imports, so it loads fine standalone.
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "innova_farna")
)
import api  # noqa: E402


async def run(a: argparse.Namespace) -> None:
    client = api.InnovaClient()
    try:
        if a.cmd == "login":
            print(await client.login(a.email, a.password))
        elif a.cmd == "send-code":
            await client.request_code(a.email)
            print("verification code sent by email")
        elif a.cmd == "code":
            print(await client.login_with_code(a.email, a.code))
        elif a.cmd == "devices":
            client.set_token(a.token)
            for d in await client.list_devices():
                print(d)
        elif a.cmd == "get":
            client.set_token(a.token)
            print(await client.get_state(a.mac, a.node))
        elif a.cmd == "set":
            client.set_token(a.token)
            await client.set_state(
                a.mac,
                a.node,
                power=None if a.power is None else a.power == "on",
                temperature_setpoint=a.temp,
                hvac_mode=a.mode,
                fan_speed=a.fan,
                flap_swing=None if a.swing is None else a.swing == "on",
            )
            print("command sent")
    finally:
        await client.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)

    p = sub.add_parser("send-code")
    p.add_argument("--email", required=True)

    p = sub.add_parser("code")
    p.add_argument("--email", required=True)
    p.add_argument("--code", required=True)

    p = sub.add_parser("devices")
    p.add_argument("--token", required=True)

    for name in ("get", "set"):
        p = sub.add_parser(name)
        p.add_argument("--token", required=True)
        p.add_argument("--mac", required=True)
        p.add_argument("--node", type=int, default=0)
        if name == "set":
            p.add_argument("--power", choices=["on", "off"])
            p.add_argument("--temp", type=float)
            p.add_argument("--mode", type=int, help="hvac_mode: 1=auto 2=heat 3=cool 4=dry 5=fan")
            p.add_argument("--fan", type=int, help="fan_speed: 1=auto 2=low 3=medium 4=high 5=max")
            p.add_argument("--swing", choices=["on", "off"])

    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
