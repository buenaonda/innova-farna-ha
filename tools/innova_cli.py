#!/usr/bin/env python3
"""Standalone CLI to exercise the Innova FÄRNA cloud protocol (auth + gRPC).

Used to validate the reverse-engineered protocol against a live device and to
confirm the hvac_mode / fan_speed enum values.

    pip install grpcio protobuf
    python tools/innova_cli.py login   --email you@x.com --password ***
    python tools/innova_cli.py homes   --token <JWT>
    python tools/innova_cli.py get     --token <JWT> --mac AA:BB:CC:DD:EE:FF --node 0
    python tools/innova_cli.py set      --token <JWT> --mac AA:BB:CC:DD:EE:FF --power on --temp 22 --mode 2 --fan 1
    # passwordless (Google accounts): request a code, then log in with it
    python tools/innova_cli.py send-code --email you@x.com
    python tools/innova_cli.py code      --email you@x.com --code 123456
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "innova_farna"))
import grpc  # noqa: E402
import innova_pb2 as pb  # noqa: E402
import innova_pb2_grpc as pb_grpc  # noqa: E402

REST = "https://v2.api.innova.solutiontech.tech/app"
GRPC = "v2.grpc.innova.solutiontech.tech:443"
UA = "Innova/3.0.0 (Android 13)"


def _post(path, body):
    req = urllib.request.Request(
        f"{REST}/{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _get(path, token=None):
    h = {"User-Agent": UA}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{REST}/{path}", headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _stub():
    ch = grpc.secure_channel(GRPC, grpc.ssl_channel_credentials())
    return pb_grpc.AppServiceStub(ch)


def _md(token):
    return [("authorization", f"Bearer {token}")]


def mac_bytes(mac):
    return bytes.fromhex(mac.replace(":", ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("login", "code"):
        p = sub.add_parser(name)
        p.add_argument("--email", required=True)
        p.add_argument("--password" if name == "login" else "--code", required=True)
    p = sub.add_parser("send-code"); p.add_argument("--email", required=True)
    p = sub.add_parser("homes"); p.add_argument("--token", required=True)
    for name in ("get", "set"):
        p = sub.add_parser(name)
        p.add_argument("--token", required=True)
        p.add_argument("--mac", required=True)
        p.add_argument("--node", type=int, default=0)
        if name == "set":
            p.add_argument("--power", choices=["on", "off"])
            p.add_argument("--temp", type=float)
            p.add_argument("--mode", type=int, help="hvac_mode enum value")
            p.add_argument("--fan", type=int, help="fan_speed enum value")
            p.add_argument("--swing", choices=["on", "off"])
    a = ap.parse_args()

    if a.cmd == "login":
        print(json.dumps(_post("users/login", {"email": a.email, "password": a.password}), indent=2))
    elif a.cmd == "send-code":
        _get(f"users/send-reset-password/{a.email}"); print("code sent")
    elif a.cmd == "code":
        print(json.dumps(_post("users/reset-password", {"email": a.email, "verificationCode": a.code}), indent=2))
    elif a.cmd == "homes":
        print(_get("homes", a.token).decode())
    elif a.cmd == "get":
        req = pb.DeviceRequest(mac_address=mac_bytes(a.mac), node_id=a.node)
        req.request.shared.get_state.SetInParent()
        resp = _stub().SendDevice(req, metadata=_md(a.token), timeout=25)
        print(resp)
    elif a.cmd == "set":
        req = pb.DeviceRequest(mac_address=mac_bytes(a.mac), node_id=a.node)
        ss = req.request.ac.set_state
        if a.power:
            ss.power = a.power == "on"
        if a.temp is not None:
            ss.temperature_setpoint = a.temp
        if a.mode is not None:
            ss.hvac_mode = a.mode
        if a.fan is not None:
            ss.fan_speed = a.fan
        if a.swing:
            ss.flap_swing = a.swing == "on"
        resp = _stub().SendDevice(req, metadata=_md(a.token), timeout=25)
        print(resp)


if __name__ == "__main__":
    main()
