"""Async client for the Innova FÄRNA / v2 cloud API (REST auth + gRPC control).

Reverse-engineered from the Android app tech.solutiontech.innova v3.0.0.
See ../proto/innova.proto for the message/service definitions.
"""
from __future__ import annotations

import logging
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
    """'E4:B3:23:8E:64:84' -> b'\\xe4\\xb3\\x23\\x8e\\x64\\x84' (6 raw bytes)."""
    return bytes.fromhex(mac.replace(":", "").replace("-", ""))


@dataclass
class Device:
    mac_address: str
    node_id: int
    name: str
    serial_number: str
    home_name: str
    room_name: str


class InnovaClient:
    """Talks to the Innova cloud: REST for auth/inventory, gRPC for state/commands."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._own_session = session is None
        self._token: str | None = None
        self._channel: grpc.aio.Channel | None = None
        self._stub: pb_grpc.AppServiceStub | None = None

    # ---------------- REST ----------------
    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def login(self, email: str, password: str) -> str:
        """POST users/login -> JWT token."""
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

    async def login_with_code(self, email: str, verification_code: str) -> str:
        """Passwordless login for Google-only accounts.

        First call ``request_code(email)`` to receive the 6-digit code by email.
        POST users/reset-password {email, verificationCode} -> token.
        """
        sess = await self._sess()
        async with sess.post(
            f"{REST_BASE}/users/reset-password",
            json={"email": email, "verificationCode": verification_code},
            headers={"User-Agent": USER_AGENT},
        ) as r:
            if r.status != 200:
                raise InnovaAuthError(f"reset-password HTTP {r.status}: {await r.text()}")
            data = await r.json()
        self._token = data["token"]
        return self._token

    async def request_code(self, email: str) -> None:
        """Trigger the verification-code email (GET users/send-reset-password/{email})."""
        sess = await self._sess()
        async with sess.get(
            f"{REST_BASE}/users/send-reset-password/{email}",
            headers={"User-Agent": USER_AGENT},
        ) as r:
            if r.status not in (200, 204):
                raise InnovaError(f"send-reset-password HTTP {r.status}")

    def set_token(self, token: str) -> None:
        self._token = token

    async def get_homes(self) -> list[dict]:
        """GET homes -> raw homes json (homes -> rooms/devices)."""
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
    async def _ensure_stub(self) -> pb_grpc.AppServiceStub:
        if self._stub is None:
            self._channel = grpc.aio.secure_channel(
                GRPC_TARGET, grpc.ssl_channel_credentials()
            )
            self._stub = pb_grpc.AppServiceStub(self._channel)
        return self._stub

    def _md(self) -> list[tuple[str, str]]:
        if not self._token:
            raise InnovaAuthError("not logged in")
        return [("authorization", f"Bearer {self._token}")]

    async def get_state(self, mac: str, node_id: int = 0) -> pb.AcState:
        """SendDevice{shared.get_state} -> AC state.

        Raises InnovaDeviceOffline if the cloud could not reach the unit
        (error code set, e.g. RESPONSE_TIMEOUT) or returned no state.
        """
        stub = await self._ensure_stub()
        req = pb.DeviceRequest(mac_address=mac_to_bytes(mac), node_id=node_id)
        req.request.shared.get_state.SetInParent()
        resp = await self._send(stub, req)
        if resp.error.code != 0:
            raise InnovaDeviceOffline(f"error code {resp.error.code}")
        which = resp.device.WhichOneof("type")
        if which is None or resp.device.ac.ByteSize() == 0:
            raise InnovaDeviceOffline("empty state (device not reporting)")
        return resp.device.ac

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
        """SendDevice{ac.set_state{...}} — only the provided fields are set."""
        stub = await self._ensure_stub()
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
        await self._send(stub, req)

    async def _send(self, stub, req) -> pb.DeviceResponse:
        try:
            return await stub.SendDevice(req, metadata=self._md(), timeout=25)
        except grpc.aio.AioRpcError as e:
            code = e.code()
            if code == grpc.StatusCode.UNAVAILABLE:
                raise InnovaDeviceOffline(e.details()) from e
            if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
                raise InnovaAuthError(e.details()) from e
            raise InnovaError(f"{code}: {e.details()}") from e

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None
