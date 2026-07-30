"""Async client for the Innova FÄRNA / v2 cloud API (REST auth + gRPC control).

Reverse-engineered from the Android app tech.solutiontech.innova v3.0.0.
See ../proto/innova.proto for a human-readable description of the messages.

We talk gRPC over a raw ``grpc.aio`` channel and build/parse the (small, fixed)
protobuf messages by hand — this avoids shipping generated ``*_pb2`` code, which
would pin ``protobuf``/``grpcio`` to versions that clash with Home Assistant's
own constraints. The only third-party dependency is ``grpcio`` (the transport).

State read: ``SendDevice{shared.get_state}`` returns a deeply-nested, UI-oriented
message; we navigate it by the observed field-number path (validated live).
Commands: ``SendDevice{ac.set_state{...}}`` (validated live — a setpoint change
echoes back over SubscribeEvents).
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
from dataclasses import dataclass

import aiohttp
import grpc

_LOGGER = logging.getLogger(__name__)

REST_BASE = "https://v2.api.innova.solutiontech.tech/app"
GRPC_TARGET = "v2.grpc.innova.solutiontech.tech:443"
USER_AGENT = "Innova/3.0.0 (Android 13)"
SEND_DEVICE_METHOD = "/services.app.AppService/SendDevice"
REST_TIMEOUT = aiohttp.ClientTimeout(total=15)
GRPC_TIMEOUT = 15


class InnovaError(Exception):
    """Base error for the Innova client."""


class InnovaAuthError(InnovaError):
    """Invalid credentials / expired token."""


class InnovaDeviceOffline(InnovaError):
    """The device is not currently reachable through the Innova cloud."""


# --- protobuf wire-format encode helpers (build requests by hand) -----------
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            break
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _ld(field: int, payload: bytes) -> bytes:
    """length-delimited field (wire type 2)."""
    return _tag(field, 2) + _varint(len(payload)) + payload


def _vint(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def _f32(field: int, value: float) -> bytes:
    return _tag(field, 5) + struct.pack("<f", value)


# --- protobuf wire-format decode (single level, no schema) ------------------
def _fields(data: bytes) -> dict[int, list]:
    i, n, out = 0, len(data), {}
    while i < n:
        tag = 0
        shift = 0
        while i < n:
            b = data[i]
            i += 1
            tag |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            v = 0
            shift = 0
            while i < n:
                b = data[i]
                i += 1
                v |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        elif wt == 5:
            v = struct.unpack("<f", data[i : i + 4])[0]
            i += 4
        elif wt == 1:
            v = struct.unpack("<q", data[i : i + 8])[0]
            i += 8
        elif wt == 2:
            ln = 0
            shift = 0
            while i < n:
                b = data[i]
                i += 1
                ln |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            v = data[i : i + ln]
            i += ln
        else:
            break
        out.setdefault(fn, []).append(v)
    return out


def _one(d: dict, fn: int):
    v = d.get(fn)
    return v[0] if v else None


def mac_to_bytes(mac: str) -> bytes:
    """'AA:BB:CC:DD:EE:FF' -> 6 raw bytes."""
    return bytes.fromhex(mac.replace(":", "").replace("-", ""))


@dataclass
class Device:
    mac_address: str
    node_id: int
    name: str
    serial_number: str
    home_name: str
    room_name: str


@dataclass
class AcState:
    """Decoded air-conditioner state (raw enum ints; see const for HA mapping)."""
    power: bool
    current_temperature: float | None
    target_temperature: float | None
    min_temp: float | None
    max_temp: float | None
    temp_step: float | None
    hvac_mode: int | None
    fan_speed: int | None


def _build_get_state(mac: str, node_id: int) -> bytes:
    # DeviceRequest{ mac(1), node(2, omitted if 0), request(3)=Command{shared(2)=Shared{get_state(1)={}}} }
    command = _ld(2, _ld(1, b""))
    req = _ld(1, mac_to_bytes(mac))
    if node_id:
        req += _vint(2, node_id)
    return req + _ld(3, command)


def _build_set_state(mac: str, node_id: int, ss: bytes) -> bytes:
    # DeviceRequest{ mac(1), node(2?), request(3)=Command{ac(3)=Ac{set_state(1)=SetState}} }
    command = _ld(3, _ld(1, ss))
    req = _ld(1, mac_to_bytes(mac))
    if node_id:
        req += _vint(2, node_id)
    return req + _ld(3, command)


def _parse_ac_state(resp: bytes) -> AcState:
    """Navigate the get_state response: resp.f2.f1.f1.f2.f2.f1 = the AC block."""
    d = _fields(_one(_fields(resp), 2))   # device
    d = _fields(_one(d, 1))
    d = _fields(_one(d, 1))
    s = _fields(_one(d, 2))               # state
    s = _fields(_one(s, 2))
    ac = _fields(_one(s, 1))              # AC block
    tb = _fields(_one(ac, 3) or b"")      # {setpoint, min, max, step}
    mode = _fields(_one(ac, 4) or b"")
    fan = _fields(_one(ac, 5) or b"")

    def r(v, nd=1):
        return round(v, nd) if v is not None else None

    return AcState(
        power=bool(_one(ac, 2)),
        current_temperature=r(_one(ac, 7)),
        target_temperature=r(_one(tb, 1)),
        min_temp=r(_one(tb, 2)),
        max_temp=r(_one(tb, 3)),
        temp_step=r(_one(tb, 4), 2),
        hvac_mode=_one(mode, 1),
        fan_speed=_one(fan, 1),
    )


class InnovaClient:
    """REST for auth/inventory, raw gRPC for state/commands."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._own_session = session is None
        self._token: str | None = None
        self._channel: grpc.aio.Channel | None = None

    # ---------------- REST ----------------
    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _rest(self, method: str, path: str, *, payload=None, auth=False) -> dict | None:
        sess = await self._sess()
        headers = {"User-Agent": USER_AGENT}
        if auth:
            if not self._token:
                raise InnovaAuthError("not logged in")
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with sess.request(
                method, f"{REST_BASE}/{path}", json=payload, headers=headers,
                timeout=REST_TIMEOUT,
            ) as r:
                if r.status in (401, 403):
                    raise InnovaAuthError(f"HTTP {r.status}")
                if r.status not in (200, 204):
                    raise InnovaError(f"{method} {path} -> HTTP {r.status}")
                if r.status == 204:
                    return None
                text = await r.text()
                return json.loads(text) if text else None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise InnovaError(f"network error on {path}: {err}") from err

    async def login(self, email: str, password: str) -> str:
        data = await self._rest("POST", "users/login", payload={"email": email, "password": password})
        token = (data or {}).get("token")
        if not token:
            raise InnovaAuthError("login response had no token")
        self._token = token
        return token

    async def request_code(self, email: str) -> None:
        """Trigger the verification-code email (Google-only accounts)."""
        await self._rest("GET", f"users/send-reset-password/{email}")

    async def login_with_code(self, email: str, verification_code: str) -> str:
        data = await self._rest(
            "POST", "users/reset-password",
            payload={"email": email, "verificationCode": verification_code},
        )
        token = (data or {}).get("token")
        if not token:
            raise InnovaAuthError("reset-password response had no token")
        self._token = token
        return token

    def set_token(self, token: str) -> None:
        self._token = token

    async def list_devices(self) -> list[Device]:
        homes = await self._rest("GET", "homes", auth=True) or []
        out: list[Device] = []
        for home in homes:
            rooms = {rm["id"]: rm.get("name", "") for rm in home.get("rooms", [])}
            for dev in home.get("devices", []):
                out.append(
                    Device(
                        mac_address=dev["macAddress"],
                        node_id=dev.get("nodeId", 0),
                        name=dev.get("name", "Innova"),
                        serial_number=dev.get("serialNumber", ""),
                        home_name=home.get("name", ""),
                        room_name=rooms.get(dev.get("roomId"), ""),
                    )
                )
        return out

    # ---------------- gRPC ----------------
    def _channel_(self) -> grpc.aio.Channel:
        if self._channel is None:
            self._channel = grpc.aio.secure_channel(
                GRPC_TARGET, grpc.ssl_channel_credentials()
            )
        return self._channel

    async def _send(self, request: bytes) -> bytes:
        if not self._token:
            raise InnovaAuthError("not logged in")
        call = self._channel_().unary_unary(
            SEND_DEVICE_METHOD,
            request_serializer=lambda b: b,
            response_deserializer=lambda b: b,
        )
        try:
            return await call(
                request,
                metadata=(("authorization", f"Bearer {self._token}"),),
                timeout=GRPC_TIMEOUT,
            )
        except grpc.aio.AioRpcError as e:
            code = e.code()
            if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                raise InnovaDeviceOffline(str(e.details())) from e
            if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
                raise InnovaAuthError(str(e.details())) from e
            raise InnovaError(f"{code}: {e.details()}") from e

    async def get_state(self, mac: str, node_id: int = 0) -> AcState:
        """Read AC state. Raises InnovaDeviceOffline if the unit isn't reachable."""
        resp = await self._send(_build_get_state(mac, node_id))
        top = _fields(resp)
        if 1 in top and 2 not in top:  # error wrapper (e.g. code 1 = RESPONSE_TIMEOUT)
            raise InnovaDeviceOffline("cloud could not reach the unit")
        try:
            return _parse_ac_state(resp)
        except Exception as err:
            _LOGGER.debug("Unparseable get_state for %s: %s (raw=%s)", mac, err, resp.hex())
            raise InnovaDeviceOffline(f"unparseable state: {err}") from err

    async def set_state(
        self,
        mac: str,
        node_id: int = 0,
        *,
        power: bool | None = None,
        temperature_setpoint: float | None = None,
        hvac_mode: int | None = None,
        fan_speed: int | None = None,
        flap_swing: bool | None = None,
    ) -> None:
        """SendDevice{ac.set_state{...}} — only provided fields are sent."""
        ss = b""
        if power is not None:
            ss += _vint(1, 1 if power else 0)
        if temperature_setpoint is not None:
            ss += _f32(2, temperature_setpoint)
        if hvac_mode is not None:
            ss += _vint(3, hvac_mode)
        if fan_speed is not None:
            ss += _vint(4, fan_speed)
        if flap_swing is not None:
            ss += _vint(5, 1 if flap_swing else 0)
        await self._send(_build_set_state(mac, node_id, ss))

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None
