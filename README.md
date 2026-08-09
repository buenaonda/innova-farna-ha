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
- `sensor` entity: ambient temperature reported by the unit
- Pure cloud, no extra hardware, no need to open/modify the unit

## Equipos nuevos

Si agregas un aire acondicionado a tu cuenta Innova, **aparece solo** en Home
Assistant: la integración vuelve a consultar la lista de equipos de la cuenta
cada 10 minutos y crea las entidades de los que encuentre, sin reiniciar ni
recargar nada.

Hasta la v0.4.0 no era así — la lista se leía una única vez al configurar la
integración, y un equipo agregado después no aparecía nunca hasta recargarla a
mano.

El estado de cada equipo se sigue consultando cada 15 segundos; solo el
*descubrimiento* usa el intervalo largo, porque la lista de equipos de una
cuenta cambia cuando alguien compra uno, no a cada rato.

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

**v0.4 — working.** Live-validated end-to-end on a real FÄRNA unit: reads ambient temperature, setpoint, mode and fan via cloud polling, and controls power/temperature/mode/fan. HVAC-mode and fan-speed mappings are confirmed against the app. No generated protobuf code is shipped — messages are encoded/decoded directly, so the only dependency is `grpcio`.

## Credits

Reverse-engineered and built by [@buenaonda](https://github.com/buenaonda).
Not affiliated with or endorsed by Innova / Solution Tech. Use at your own risk.

## License

MIT
