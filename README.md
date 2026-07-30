# Innova FÄRNA — Home Assistant integration

Local-account (cloud) Home Assistant integration for the **new Innova platform**
(FÄRNA fan-coils and the latest Innova 2.0 "senza unità esterna" units that report
as *AirLeaf/AC* over Innova's v2 cloud).

These newer units **dropped the local REST API** that
[`danielrivard/homeassistant-innova`](https://github.com/danielrivard/homeassistant-innova)
uses — they expose **no local server at all** (every TCP port closed) and talk only to
Innova's cloud over **gRPC** (`v2.grpc.innova.solutiontech.tech`). This integration speaks
that protocol, so it works where the local integration returns *"cannot connect"*.

> Addresses danielrivard/homeassistant-innova **issue #278**.

## Features

- `climate` entity: power, target temperature, HVAC mode, fan speed
- `sensor` entities: ambient temperature and humidity reported by the unit
- Pure cloud, no extra hardware, no need to open/modify the unit

## Requirements

- A working **Innova app account** (email + password). If you signed up with Google,
  set a password first via the app's *Forgot password* flow (or the
  `send-reset-password` endpoint — see `docs/`).

## Installation (HACS)

1. HACS → **Custom repositories** → add `https://github.com/buenaonda/innova-farna-ha`
   as category **Integration**.
2. Install **Innova FÄRNA**, restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *Innova FÄRNA* → sign in.

## How it works

| Layer | Endpoint | Purpose |
|-------|----------|---------|
| Auth  | `POST https://v2.api.innova.solutiontech.tech/app/users/login` | email/password → JWT |
| Inventory | `GET .../app/homes` | homes → rooms → devices |
| State/Control | gRPC `services.app.AppService` @ `v2.grpc…:443` | `SendDevice` (get/set state), `SubscribeEvents` (live push) |

The full reverse-engineered protocol is documented in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Status

**v0.1 — early / experimental.** Protocol validated end-to-end (auth + gRPC transport +
message framing). The `hvac_mode` / `fan_speed` enum **numeric values** are best-effort and
being confirmed against live devices — if a mode/fan looks wrong, please open an issue with
the raw `GetState` output.

## Credits

Reverse-engineered and built by [@buenaonda](https://github.com/buenaonda) with Claude Code.
Not affiliated with or endorsed by Innova / Solution Tech. Use at your own risk.

## License

MIT
