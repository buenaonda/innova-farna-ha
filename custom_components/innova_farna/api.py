"""Async client for the Innova FÄRNA / v2 cloud API (REST auth + gRPC control).

Reverse-engineered from the Android app tech.solutiontech.innova v3.0.0.
See ../proto/innova.proto for the request/command definitions.

State reading: SendDevice{shared.get_state} returns a deeply-nested, UI-oriented
message (each setting is {value, options} or {value, min, max, step}). Rather than
model every wrapper, we navigate the wire format by the observed field-number path
(stable schema). Commands use the compiled proto (validated live: a setpoint change
is echoed back over SubscribeEvents).
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

import aiohttp
import grpc

from . import innova_pb2 as pb
from . import innova_pb2_grpc as pb_grpc

_LOGGER = logging.getLogger(__name__)

REST_BASE = "https://v2.api.innova.solutiontech.tech/app"
GRPC_TARGET = "v2.grpc.innova.solutiontech.tech:443"
USER_AGENT = "Innova/3.0.0 (Android 13)"


class InnovaAuthError(Exception):
    """Invalid credentials / expired token."""


class InnovaDeviceOffline(Exception):
    """The device is not currently connected to the Innova cloud."""


class InnovaError(Exception):
    """Generic API error."""


def mac_to_bytes(mac: str) -> bytes:
    """'E4:B3:23:8E:64:84' -> 6 raw bytes."""
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
    """Decoded air-conditioner state."""
    power: bool
    current_temperature: float | None
    target_temperature: float | None
    min_temp: float | None
    max_temp: float | None
    temp_step: float | None
    hvac_mode: int | None   # raw enum value (see const.HVAC_MODE_TO_HA)
    fan_speed: int | None   # raw enum value (see const.FAN_TO_HA)


# ---- protobuf wire-format helpers (single-level parse, no heuristics) -------
def _fields(data: bytes) -> dict[int, list]:
    """Parse one protobuf level -> {field_number: [values]} (int|float|bytes)."""
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


def _parse_ac_state(resp: bytes) -> AcState:
    """Navigate SendDevice(get_state) response -> AcState.

    Path: resp.f2(device).f1.f1.f2(state).f2.f1 = the AC block, where
    f2=power, f3={setpoint,min,max,step}, f4={mode,opts}, f5={fan,opts}, f7=ambient.
    """
    top = _fields(resp)
    d = _fields(_one(top, 2))          # device
    d = _fields(_one(d, 1))
    d = _fields(_one(d, 1))
    s = _fields(_one(d, 2))            # state
    s = _fields(_one(s, 2))
    ac = _fields(_one(s, 1))           # AC block
    tb = _fields(_one(ac, 3) or b"")   # temp block
    mode = _fields(_one(ac, 4) or b"")
    fan = _fields(_one(ac, 5) or b"")
    return AcState(
        power=bool(_one(ac, 2)),
        current_temperature=round(_one(ac, 7), 1) if _one(ac, 7) is not None else None,
        target_temperature=round(_one(tb, 1), 1) if _one(tb, 1) is not None else None,
        min_temp=round(_one(tb, 2), 1) if _one(tb, 2) is not None else None,
        max_temp=round(_one(tb, 3), 1) if _one(tb, 3) is not None else None,
        temp_step=round(_one(tb, 4), 2) if _one(tb, 4) is not None else None,
        hvac_mode=_one(mode, 1),
        fan_speed=_one(fan, 1),
    )


class InnovaClient:
    """Talks to the Innova cloud: REST for auth/inventory, gRPC for state/commands."""

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

    async def login(self, email: str, password: str) -> str:
        sess = await self._sess()
        async with sess.post(
            f"{REST_BASE}/users/login",
            json={"email": email, "password": password},
            headers={"User-Agent": USER_AGENT},
        ) as r:
            if r.status == 401:
                raise InnovaAuthError("Invalid credentials")
            if r.status != 200:
                raise InnovaError(f"login HTTP {r.status}: {await r.text()}")
            data = await r.json()
        self._token = data["token"]
        return self._token

    async def request_code(self, email: str) -> None:
        """Trigger the verification-code email (for Google-only accounts)."""
        sess = await self._sess()
        async with sess.get(
            f"{REST_BASE}/users/send-reset-password/{email}",
            headers={"User-Agent": USER_AGENT},
        ) as r:
            if r.status not in (200, 204):
                raise InnovaError(f"send-reset-password HTTP {r.status}")

    async def login_with_code(self, email: str, verification_code: str) -> str:
        sess = await self._sess()
        async with sess.post(
            f"{REST_BASE}/users/reset-password",
            json={"email": email, "verificationCode": verification_code},
            headers={"User-Agent": USER_AGENT},
        ) as r:
            if r.status != 200:
                raise InnovaAuthError(f"reset-password HTTP {r.status}")
            data = await r.json()
        self._token = data["token"]
        return self._token

    def set_token(self, token: str) -> None:
        self._token = token

    async def get_homes(self) -> list[dict]:
        if not self._token:
            raise InnovaAuthError("not logged in")
        sess = await self._sess()
        async with sess.get(
            f"{REST_BASE}/homes",
            headers={"Authorization": f"Bearer {self._token}", "User-Agent": USER_AGENT},
        ) as r:
            if r.status == 401:
                raise InnovaAuthError("token expired")
            if r.status != 200:
                raise InnovaError(f"homes HTTP {r.status}")
            return await r.json()

    async def list_devices(self) -> list[Device]:
        out: list[Device] = []
        for home in await self.get_homes():
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

    def _md(self) -> list[tuple[str, str]]:
        if not self._token:
            raise InnovaAuthError("not logged in")
        return [("authorization", f"Bearer {self._token}")]

    async def _send(self, req: pb.DeviceRequest) -> bytes:
        """SendDevice unary call; returns raw response bytes."""
        ch = self._channel_()
        call = ch.unary_unary(
            "/services.app.AppService/SendDevice",
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=lambda b: b,
        )
        try:
            return await call(req, metadata=self._md(), timeout=25)
        except grpc.aio.AioRpcError as e:
            code = e.code()
            if code == grpc.StatusCode.UNAVAILABLE:
                raise InnovaDeviceOffline(e.details()) from e
            if code in (
                grpc.StatusCode.UNAUTHENTICATED,
                grpc.StatusCode.PERMISSION_DENIED,
            ):
                raise InnovaAuthError(e.details()) from e
            raise InnovaError(f"{code}: {e.details()}") from e

    async def get_state(self, mac: str, node_id: int = 0) -> AcState:
        """Read the AC state. Raises InnovaDeviceOffline if the unit isn't reachable."""
        req = pb.DeviceRequest(mac_address=mac_to_bytes(mac), node_id=node_id)
        req.request.shared.get_state.SetInParent()
        resp = await self._send(req)
        # Error wrapper (e.g. code 1 = RESPONSE_TIMEOUT) or no device payload -> offline.
        top = _fields(resp)
        if 1 in top and 2 not in top:
            raise InnovaDeviceOffline("cloud could not reach the unit")
        try:
            return _parse_ac_state(resp)
        except Exception as err:  # malformed / unexpected -> treat as offline
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
        req = pb.DeviceRequest(mac_address=mac_to_bytes(mac), node_id=node_id)
        ss = req.request.ac.set_state
        if power is not None:
            ss.power = power
        if temperature_setpoint is not None:
            ss.temperature_setpoint = temperature_setpoint
        if hvac_mode is not None:
            ss.hvac_mode = hvac_mode
        if fan_speed is not None:
            ss.fan_speed = fan_speed
        if flap_swing is not None:
            ss.flap_swing = flap_swing
        await self._send(req)

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None
