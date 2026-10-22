# ⚡ GridPulse — Bidirectional Smart Grid & DSO Telemetry Prototype

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.13-FF6600?logo=rabbitmq&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-11.2-F46800?logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker_Compose-v2-2496ED?logo=docker&logoColor=white)

**GridPulse** is a full-stack Distribution System Operator (DSO) control plane and real-time telemetry simulator. It models a bidirectional city electricity grid where prosumer households both consume power from the municipal grid and inject rooftop solar (PV) and home battery energy back into neighborhood feeders.

Smart meter telemetry is generated at 1.5-second intervals, streamed across a **RabbitMQ** topic exchange, persisted into **PostgreSQL**, and visualized through an auto-provisioned **Grafana** observability suite embedded directly inside a **FastAPI** web portal.

---

## 📋 Table of Contents
1. [Key Features](#-key-features)
2. [System Architecture](#-system-architecture)
3. [Prerequisites (Required Software)](#-prerequisites-required-software)
4. [Quick Start](#-quick-start)
5. [Service Endpoints & Credentials](#-service-endpoints--credentials)
6. [Interactive Scenarios & Physics Sandbox](#-interactive-scenarios--physics-sandbox)
7. [Telemetry Data Model](#-telemetry-data-model)
8. [Repository Structure](#-repository-structure)
9. [Lifecycle & Maintenance Commands](#-lifecycle--maintenance-commands)
10. [Troubleshooting](#-troubleshooting)

---

## 🚀 Key Features

* **Bidirectional Prosumer Simulation**: Simulates 30 smart-metered households distributed across 3 city districts (`Solar Suburb`, `Downtown Core`, `Industrial Edge`) with heterogeneous rooftop PV arrays, home battery storage (BESS), and 11–22 kW EV wallboxes.
* **Realistic Grid Physics**: Models feeder impedance and voltage rise ($\Delta V \approx I \cdot R$) during heavy midday solar export, voltage sag during evening EV charging surges, grid frequency drift around 50.000 Hz, and dynamic spot market tariffs (€/MWh).
* **AMQP Message Broker Pipeline**: Publishes JSON smart meter payloads to a RabbitMQ topic exchange (`grid.telemetry`) using hierarchical routing keys (`district.<name>.house.<id>`).
* **Zero-Config Grafana Provisioning**: Automatically provisions the PostgreSQL data source and a 4-panel time-series dashboard (`gridpulse-dso`) on container startup—no manual SQL setup required.
* **Live Scenario & VPP Control Center**: Trigger pre-configured grid emergencies with one click or override cloud cover, solar irradiance, EV surge multipliers, and Virtual Power Plant (VPP) demand-response curtailment in real time.

---

## 🏗 System Architecture

```text
+-------------------------------------------------------------------------+
|                   Prosumer Smart Meters (30 Households)                 |
|        Generates 1.5s Telemetry: P, Q, V, f, Battery SoC, EV Load       |
+------------------------------------+------------------------------------+
                                     | AMQP 0-9-1 (JSON Payloads)
                                     v
+-------------------------------------------------------------------------+
|                         RabbitMQ Broker (Port 5672)                     |
|     Topic Exchange: "grid.telemetry" | Routing: "district.*.house.*"    |
+------------------------------------+------------------------------------+
                                     | Batch Consumer (Prefetch: 100)
                                     v
+-------------------------------------------------------------------------+
|                       PostgreSQL 16 Database (Port 5432)                |
|   Tables: households, meter_telemetry, grid_events | View: city_summary |
+------------------+-----------------------------------+------------------+
                   |                                   |
                   v                                   v
+------------------------------------+   +--------------------------------+
|   Grafana 11.2 Engine (Port 3000)  |   |  FastAPI Web Portal (Port 8000)|
|  Auto-Provisioned Dashboards & SQL |-->|  SCADA KPIs, Scenario Injector |
|      Embedded via Kiosk Iframe     |   |  & Live Physics Sliders        |
+------------------------------------+   +--------------------------------+
```

---

## 🛠 Prerequisites (Required Software)

Because the entire runtime stack (PostgreSQL, RabbitMQ, Grafana, and the Python web server) is containerized, you **do not** need to install PostgreSQL, RabbitMQ, or Grafana directly on your host machine.

Ensure the following software is installed on your system before building:

### 1. Required Host Software
| Software | Minimum Version | Purpose | Installation Check |
| :--- | :--- | :--- | :--- |
| **Docker Engine / Desktop** | `24.0+` | Runs PostgreSQL, RabbitMQ, Grafana, and the FastAPI container | `docker --version` |
| **Docker Compose** | `v2.20+` | Orchestrates multi-container networking, volumes, and health checks | `docker compose version` |
| **Python** | `3.8+` | Runs the zero-dependency `bootstrap.py` scaffolder on the host | `python --version` or `python3 --version` |
| **Modern Web Browser** | Chrome / Edge / Firefox | Renders the SCADA web portal and embedded Grafana iframes | — |

* **Windows Users**: Install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) (with the WSL 2 backend enabled) and **PowerShell 5.1+ / 7+**.

### 2. Required Free TCP Ports
Ensure no local services (such as a local Postgres instance or another web server) are occupying these ports on `localhost`:
* `8000` — GridPulse FastAPI Web Control Plane
* `3000` — Grafana Web UI & Embedded Iframes
* `5432` — PostgreSQL Database
* `5672` — RabbitMQ AMQP Broker
* `15672` — RabbitMQ Management Web Console

---

## ⚡ Quick Start

### Option A: Automated Launch (Windows PowerShell)
```powershell
# 1. Generate project files, build containers, and launch the browser automatically
.\manage.ps1 up
```


### Option B: Manual Build (Using Docker Compose Directly)
If you prefer running commands manually without the wrapper scripts:
```bash
# 1. Generate the directory structure and configuration files
python bootstrap.py

# 2. Build and start all services in detached mode
docker compose up --build -d
```

Once started, open **`http://localhost:8000`** in your browser.

---

## 🔐 Service Endpoints & Credentials

| Service | URL | Username | Password | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **GridPulse Control Website** | [http://localhost:8000](http://localhost:8000) | *None* | *None* | Main customer presentation portal |
| **Grafana Dashboard** | [http://localhost:3000](http://localhost:3000) | `admin` | `admin` | Anonymous Viewer enabled for iframe embedding |
| **RabbitMQ Management UI** | [http://localhost:15672](http://localhost:15672) | `grid_broker` | `broker_password` | Inspect live message rates & queues |
| **PostgreSQL Database** | `localhost:5432` | `grid_admin` | `grid_password` | Database name: `smartgrid` |

---

## 🎛 Interactive Scenarios & Physics Sandbox

During a live demonstration, you can trigger five pre-engineered grid scenarios from the left-hand panel of the web interface:

1. **Normal Balanced Prosumer Day (`NORMAL_OPERATION`)**
   * *Time*: 13:30 | *Cloud Cover*: 15% | *Battery Policy*: Auto Self-Consumption
   * *Behavior*: Moderate solar generation offsets afternoon household load; feeder voltages remain stable near 230 V.
2. **Midday Solar Peak & Voltage Swell (`SOLAR_PEAK_VOLTAGE_SWELL`)**
   * *Time*: 12:30 | *Cloud Cover*: 0% | *Solar Factor*: 1.45x
   * *Behavior*: Clear-sky rooftop PV generation exceeds local demand, reversing power flow back into the substation (negative Net Flow) and pushing local feeder voltages above 246 V.
3. **Evening EV Commuter Overload (`EV_COMMUTER_SURGE`)**
   * *Time*: 19:00 | *EV Surge*: 4.5x
   * *Behavior*: Commuters plug in 11 kW and 22 kW EV chargers simultaneously as solar drops to zero. Feeder voltages sag below 218 V, frequency dips below 49.90 Hz, and spot prices spike.
4. **Sudden Storm Cloud Front (`CLOUD_TRANSIENT_DROP`)**
   * *Time*: 14:00 | *Cloud Cover*: 92% | *Battery Policy*: Force Discharge to Grid
   * *Behavior*: A fast-moving storm front cuts city solar output by 80%; residential batteries automatically discharge to cushion the transient drop.
5. **Virtual Power Plant Stabilization (`SMART_GRID_DEMAND_RESPONSE`)**
   * *Time*: 18:30 | *Demand Response*: Active | *Battery Policy*: Force Discharge to Grid
   * *Behavior*: The DSO throttles active EV wallboxes to 30% capacity and dispatches residential batteries across all districts to shave the evening peak and restore 230 V / 50 Hz stability.

---

## 📊 Telemetry Data Model

Every 1.5 seconds, each household smart meter (`CH-ZRH-001` through `CH-ZRH-030`) publishes a JSON payload to RabbitMQ that is persisted in the `meter_telemetry` PostgreSQL table:

* `consumption_kw`: Base household load (appliances, HVAC, heat pumps).
* `production_kw`: Rooftop solar inverter output based on time-of-day sun angle and cloud attenuation.
* `battery_kw` & `battery_soc`: Home battery power flow (`+` discharging, `-` charging) and State of Charge (`5%`–`100%`).
* `ev_load_kw`: Active electric vehicle charging load (`0`, `7.4`, `11.0`, or `22.0` kW; throttled during Demand Response).
* `net_grid_kw`: Net household exchange (`+` importing from city grid, `-` exporting surplus solar/battery to city grid).
* `reactive_kvar`: Reactive power ($Q$) for inverter power-factor analysis.
* `voltage_v`: Local point-of-common-coupling (PCC) voltage based on feeder impedance ($\Omega$) and net current flow.
* `frequency_hz`: City-wide synchronous grid frequency (nominal `50.000 Hz`).
* `tariff_eur_mwh`: Real-time dynamic spot market electricity price (€/MWh).

---

## 📂 Repository Structure

```text
gridpulse-prototype/
├── README.md                 # Project documentation & setup guide
├── bootstrap.py              # Zero-dependency project file generator
├── manage.ps1                # Windows PowerShell build & lifecycle script
├── docker-compose.yml        # Multi-container orchestration definition
├── db/
│   └── init.sql              # PostgreSQL schema, indexes, and aggregation views
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   └── datasource.yml        # Auto-connects Grafana to PostgreSQL
│       └── dashboards/
│           ├── provider.yml          # Dashboard loader config
│           └── gridpulse_main.json   # Pre-built 4-panel DSO telemetry dashboard
└── app/
    ├── Dockerfile                    # Python 3.12 container definition
    ├── requirements.txt              # Python dependencies (FastAPI, Pika, Psycopg2)
    ├── simulator_and_worker.py       # 30-house physics simulator & RabbitMQ worker
    ├── main.py                       # FastAPI REST endpoints & web server
    └── templates/
        └── index.html                # Dark-mode SCADA control center UI
```

---

## 🔄 Lifecycle & Maintenance Commands

Use `manage.ps1` (Windows) to manage the environment:

| Action | PowerShell | Description |
| :--- | :--- | :--- | :--- |
| **Start** | `.\manage.ps1 up` | Generates missing files, builds containers, and starts the stack |
| **Stop** | `.\manage.ps1 down` | Stops and removes running containers (preserves database volume) |
| **Clean Reset** | `.\manage.ps1 reset` | Wipes database volumes, regenerates files from `bootstrap.py`, and rebuilds |
| **View Logs** | `.\manage.ps1 logs` | Streams live logs from the Python simulator and FastAPI backend |
| **Status** | `.\manage.ps1 status` | Shows container health and port mappings |

---

## 🔧 Troubleshooting

* **Embedded Grafana iframe shows a login screen or refuses to connect**:
  * Ensure port `3000` is accessible on `localhost` and that your browser is not blocking third-party cookies/iframes on local loopback addresses. The `docker-compose.yml` sets `GF_SECURITY_ALLOW_EMBEDDING=true` and `GF_AUTH_ANONYMOUS_ENABLED=true` automatically.
* **Port Conflict (`Bind for 0.0.0.0:5432 failed: port is already allocated`)**:
  * You likely have a local PostgreSQL service running on your host machine. Either stop the local PostgreSQL service (`Stop-Service postgresql*` on Windows ) or change the host port mapping in `docker-compose.yml` from `"5432:5432"` to `"5433:5432"`.
* **Resetting after modifying `bootstrap.py`**:
  * If you edit code inside `bootstrap.py`, run `.\manage.ps1 reset` so the Postgres volume is recreated cleanly alongside the updated source files.
