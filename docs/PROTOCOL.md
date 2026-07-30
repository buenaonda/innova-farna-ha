# Innova FÄRNA / v2 cloud protocol — reverse-engineering notes

Reverse-engineered from the Android app `tech.solutiontech.innova` v3.0.0 (jadx decompile)
and validated live against a real unit. This is what the `innova_farna` integration
implements. Answers HA issue danielrivard/homeassistant-innova#278.

The new Innova platform has **no local API** (every TCP port on the unit is closed); it
only talks to Innova's cloud. Auth + inventory are plain REST; live state + commands are
gRPC.

## Endpoints
- REST API base: `https://v2.api.innova.solutiontech.tech/app/`
- gRPC: `v2.grpc.innova.solutiontech.tech:443` (TLS, HTTP/2). Cert-pinning is client-side
  only, so a normal client connects fine; server reflection is disabled.
- Firebase config shipped in the APK (apiKey/appId, project `innova-e5b57`) is for
  Crashlytics/Analytics only — **not** user auth — and is unused here.

## Auth (REST) → Bearer token
- `POST users/login` body `{"email","password"}` → `{"token","user"}` (token = JWT).
- Passwordless (Google-only accounts): `GET users/send-reset-password/{email}` emails a
  6-digit code, then `POST users/reset-password` body `{"email","verificationCode"}` →
  `{"token","user"}` (returns a token directly). `PATCH users/change-password` `{"password"}`
  sets a password so email+password login works afterwards.
- Every other REST call and every gRPC call sends: `Authorization: Bearer <token>`.

## REST surface (interface `defpackage/c.java`)
De-obfuscated Retrofit verbs: `zu3`=POST, `s42`=GET, `yu3`=PATCH (confirmed via `Allow`
header), `f51`=DELETE, `ux3`=@Path, `xa2`=@Header, `w40`=@Body.
- `GET homes` → homes → rooms → devices (identity/config only — **no** thermostat state here).
- Device identity fields: `macAddress`, `nodeId`, `name`, `uid{vendorId,productId,hwRevision}`,
  `serialNumber`, `roomId`.
- User CRUD: `POST users` (register), `PATCH users/me`, `DELETE users/me`,
  `PATCH users/change-password`, `POST users/verify-email`, `POST users/login-google`.
- Device/home/room/calendar/invite CRUD (not needed for climate control).

Thermostat **state and control go over gRPC**, not REST.

## gRPC service `services.app.AppService`
- `SendDevice(DeviceRequest) → DeviceResponse` (unary) — read state / send a command.
- `SubscribeEvents(SubscribeRequest) → stream Event` (server-streaming) — live state, **delta
  only** (pushes only the fields that changed; does not replay full state on subscribe).

### Wire notes (important)
- `mac_address` is **6 raw bytes** (e.g. `AA BB CC DD EE FF`), NOT the ASCII string.
- `SubscribeEvents` subscribes by **`home_id` as the raw 16-byte UUID** (not the 36-char string).
- `node_id` is a uint32, omitted when 0 (proto3 default).

### DeviceRequest (app class `pw4`)
```proto
message DeviceRequest {
  bytes  mac_address = 1;   // 6 raw bytes
  uint32 node_id     = 2;   // omitted when 0
  Command request    = 3;
}
```
### Command — oneof by device family (app class `yl0`)
```proto
message Command {
  oneof type {
    SystemCommand system = 1;  SharedCommand shared = 2;  AcCommand ac = 3;
    ButlerCommand butler = 4;  FancoilCommand fancoil = 5;
    ThermostatCommand thermostat = 6;  HeatpumpCommand heatpump = 7;
  }
}
message SharedCommand { oneof type { Empty get_state = 1; SetNodes set_nodes = 2; Empty set_operation_mode = 3; } }
message AcCommand    { oneof type { AcSetState set_state = 1; } }
```
- **Read** the AC: `Command{ shared{ get_state{} } }`.
- **Control** the AC: `Command{ ac{ set_state{...} } }`.

### AcSetState (app class `ig4` inner) — enum values CONFIRMED live
```proto
message AcSetState {
  bool  power                = 1;
  float temperature_setpoint = 2;
  int32 hvac_mode            = 3;   // 1=auto 2=heat 3=cool 4=dry 5=fan_only
  int32 fan_speed            = 4;   // 1=auto 2=low 3=medium 4=high 5=max
  bool  flap_swing           = 5;
  bool  erv                  = 6;   // some models
  bool  silent_mode          = 7;   // some models
}
```

### DeviceResponse (app class `hd1`) and the state payload
`SendDevice(get_state)` returns a deeply-nested, UI-oriented message (each setting carries its
value plus min/max/step or the list of allowed options). The integration navigates it by field
path — `resp.f2(device).f1.f1.f2(state).f2.f1` = the AC block — reading:

| what | where (in the AC block) | example |
|------|-------------------------|---------|
| power | `f2` (varint) | 1 |
| target/min/max/step | `f3` = `{f1,f2,f3,f4}` floats | 21.5 / 16.0 / 31.0 / 0.5 |
| hvac_mode | `f4.f1` (+ `f4` options list) | 3 (=cool) |
| fan_speed | `f5.f1` (+ options list) | 1 (=auto) |
| ambient temperature | `f7` (float) | 22.4 |

An error wrapper (`resp` has field 1 and no field 2, e.g. code `1` = `RESPONSE_TIMEOUT`) or a
gRPC `UNAVAILABLE`/`DEADLINE_EXCEEDED` means the unit isn't connected to the cloud right now.

> A separate flat `AcState` message (`up1`/`zp1`/`kp1`: alarms=1, power=2, setpoint=3,
> air_temperature=4, hvac_mode=5, fan_speed=6, flap_swing=7, operation_mode=8, humidity=9)
> also exists in the app, but the `get_state` response uses the nested layout above — that's
> what this integration parses. Heat-pump/fancoil families have their own message shapes.

## Status
Implemented and live-validated in this repo (**v0.4**): REST auth + inventory, gRPC state
polling and control, HA `climate` + ambient-temperature `sensor`. Messages are built/parsed by
hand (no generated protobuf shipped). The example device in earlier drafts has been removed.
