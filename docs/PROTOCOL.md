# Innova FÄRNA / v2 cloud protocol — reverse-engineering spec

Reverse-engineered from the Android app `tech.solutiontech.innova` v3.0.0 (jadx decompile).
Goal: a local-cloud Home Assistant integration (HACS) for the new Innova platform that has
NO local REST API (unlike the classic Innova 2.0 / AirLeaf). Answers HA issue
danielrivard/homeassistant-innova#278.

## Endpoints
- REST API base: `https://v2.api.innova.solutiontech.tech/app/`
- gRPC:          `v2.grpc.innova.solutiontech.tech:443` (TLS, HTTP/2; cert-pinning is client-side only — a normal client connects fine; server reflection disabled)
- Firebase (Crashlytics/Analytics only, NOT user auth): the app ships a Firebase config (apiKey/appId, project `innova-e5b57`). These are the vendor app's own public client identifiers embedded in the APK — **redacted here** and unused by this integration (auth is the REST login below, not Firebase).

## Auth (REST) — get a Bearer token
- `POST users/login`  body `{"email","password"}` → `{"token","user"}`.  token = JWT.
- Passwordless alt (Google-only accounts): `GET users/send-reset-password/{email}` sends a 6-digit code, then
  `POST users/reset-password` body `{"email","verificationCode"}` → `{"token","user"}` (returns a token directly).
- All other REST calls AND gRPC calls send header/metadata: `Authorization: Bearer <token>`.

## REST API surface (interface defpackage/c.java; annotations de-obfuscated: zu3=POST s42=GET yu3=PATCH f51=DELETE av3=PATCH ux3=@Path xa2=@Header w40=@Body)
- `GET  homes` → list of homes → rooms → devices (identity/config only, NO thermostat state)
- `POST users` (register), `PUT users/me`, `DELETE users/me`, `PUT users/change-password`, `POST users/verify-email`, `POST users/login-google`
- `POST devices` (add), `POST devices/{mac}` (register nodes; body {nodes:[{deviceUid,id,name,roomId}]}), `PUT devices/{mac}/{nodeId}` (update device config), `DELETE devices/{mac}/{nodeId}`
- homes/rooms/calendars/invites/members CRUD
- device identity (GET homes) fields: macAddress, nodeId, name, uid{vendorId,productId,hwRevision}, serialNumber, roomId

## Live state + commands = gRPC service `services.app.AppService`
Two methods:
- `SendDevice(DeviceRequest) → DeviceResponse`  (unary)   — send a command / GET state to one device
- `SubscribeEvents(...) → stream Event`          (server-streaming) — live state push

### DeviceRequest (class pw4)
```
message DeviceRequest {
  string mac_address = 1;   // "E4:B3:23:8E:64:84"
  int32  node_id     = 2;   // 0
  DeviceCommand request = 3;
}
```
### DeviceCommand (oneof; classes ig4/kg4/ng4/mg4) — the AC uses SetState
```
message DeviceCommand {
  oneof type { SetState set_state = 1; /* also GetState, SetNodes, SetOperationMode seen */ }
}
message SetState {          // AC variant (ig4 inner)
  Power  power               = 1;   // on/off enum
  float  temperature_setpoint= 2;
  HvacMode hvac_mode         = 3;   // cooling/heating/auto/dry/fan — enum values TBD (live)
  FanSpeed fan_speed         = 4;   // auto/low/med/high — enum values TBD (live)
  FlapSwing flap_swing       = 5;
  Erv    erv                 = 6;   // (some models)
  SilentMode silent_mode     = 7;   // (some models)
}
```
### DeviceResponse (class hd1)
```
message DeviceResponse {
  Error  error   = 1;
  Device device  = 2;   // oneof by type: shared=1, ac=2, fancoil=3, butler=4, thermostat=5, heatpump=6
  Service service= 3;
}
```
### AC State (class up1/zp1/kp1) — what the AC reports (device.ac)
```
message AcState {
  Alarms alarms             = 1;
  Power  power              = 2;
  float  temperature_setpoint = 3;
  float  air_temperature    = 4;   // <-- real room temperature (feedback!)
  HvacMode hvac_mode        = 5;
  FanSpeed fan_speed        = 6;
  FlapSwing flap_swing      = 7;
  OperationMode operation_mode = 8;
  float  air_humidity       = 9;   // (kp1 variant: 10)
}
```
(Heat-pump variants vp1/lg4 add dhw, zone1/zone2, water_temperature, cooling/heating setpoints, load_priority — not needed for the studio AC.)

## Studio device (Daniel)
- home "Aurelio", room "Studio", tz America/Santiago
- device "Studio": macAddress `E4:B3:23:8E:64:84`, nodeId `0`, serial `IN25155363`

## TODO to finish the integration
1. Reconstruct full `.proto` (messages above + enum VALUES for hvac_mode/fan_speed/power/flap — nail via live GetState/iteration).
2. Python gRPC client: TLS channel to v2.grpc..:443, metadata `authorization: Bearer <token>`, call SendDevice{mac,node,GetState} to read + SendDevice{mac,node,SetState{...}} to control; SubscribeEvents for push.
3. Wrap as HA custom_component `innova_farna`: config_flow (email/password → token, refresh), coordinator (SubscribeEvents or GetState polling), climate.py (map hvac_mode/fan/setpoint/power), sensor for air_temperature/humidity.
4. Publish GitHub repo + hacs.json; contribute to issue #278.
