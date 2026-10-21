#!/usr/bin/env python3
"""
GridPulse Prototype Bootstrapper
Generates the complete directory structure, Docker configs, auto-provisioned
Grafana dashboards, RabbitMQ workers, and FastAPI web application.
"""
import os
from pathlib import Path

FILES = {
    "docker-compose.yml": """\
services:
  postgres:
    image: postgres:16-alpine
    container_name: grid_postgres
    environment:
      POSTGRES_USER: grid_admin
      POSTGRES_PASSWORD: grid_password
      POSTGRES_DB: smartgrid
    ports:
      - "5432:5432"
    volumes:
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U grid_admin -d smartgrid"]
      interval: 4s
      timeout: 4s
      retries: 10

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    container_name: grid_rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: grid_broker
      RABBITMQ_DEFAULT_PASS: broker_password
    ports:
      - "5672:5672"
      - "15672:15672"
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

  grafana:
    image: grafana/grafana:11.2.0
    container_name: grid_grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_SECURITY_ALLOW_EMBEDDING=true
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
      - GF_DASHBOARDS_MIN_REFRESH_INTERVAL=1s
      - GF_USERS_DEFAULT_THEME=dark
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      postgres:
        condition: service_healthy

  web_and_sim:
    build: ./app
    container_name: grid_control_plane
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://grid_admin:grid_password@postgres:5432/smartgrid
      RABBITMQ_HOST: rabbitmq
      RABBITMQ_USER: grid_broker
      RABBITMQ_PASS: broker_password
    depends_on:
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy

volumes:
  pgdata:
""",

    "db/init.sql": """\
CREATE TABLE households (
    house_id VARCHAR(32) PRIMARY KEY,
    district VARCHAR(64) NOT NULL,
    has_solar BOOLEAN DEFAULT TRUE,
    solar_capacity_kw NUMERIC(5,2) NOT NULL,
    battery_capacity_kwh NUMERIC(5,2) NOT NULL,
    has_ev_charger BOOLEAN DEFAULT FALSE,
    feeder_impedance_ohm NUMERIC(5,4) DEFAULT 0.1500
);

CREATE TABLE meter_telemetry (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    house_id VARCHAR(32) REFERENCES households(house_id),
    district VARCHAR(64) NOT NULL,
    consumption_kw NUMERIC(8,3) NOT NULL,
    production_kw NUMERIC(8,3) NOT NULL,
    battery_kw NUMERIC(8,3) NOT NULL,
    battery_soc NUMERIC(5,2) NOT NULL,
    ev_load_kw NUMERIC(8,3) NOT NULL,
    net_grid_kw NUMERIC(8,3) NOT NULL,
    reactive_kvar NUMERIC(8,3) NOT NULL,
    voltage_v NUMERIC(6,2) NOT NULL,
    frequency_hz NUMERIC(6,3) NOT NULL,
    tariff_eur_mwh NUMERIC(7,2) NOT NULL,
    active_scenario VARCHAR(64) NOT NULL
);

CREATE INDEX idx_telemetry_time ON meter_telemetry (recorded_at DESC);
CREATE INDEX idx_telemetry_district_time ON meter_telemetry (district, recorded_at DESC);

CREATE TABLE grid_events (
    id SERIAL PRIMARY KEY,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scenario_name VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    description TEXT NOT NULL
);

CREATE VIEW city_grid_summary AS
SELECT
    date_trunc('second', recorded_at) AS time_bucket,
    SUM(consumption_kw + ev_load_kw) AS total_demand_kw,
    SUM(production_kw) AS total_solar_kw,
    SUM(battery_kw) AS total_battery_flow_kw,
    SUM(net_grid_kw) AS city_net_import_kw,
    AVG(voltage_v) AS avg_voltage_v,
    MAX(voltage_v) AS max_voltage_v,
    MIN(voltage_v) AS min_voltage_v,
    AVG(frequency_hz) AS grid_frequency_hz,
    AVG(tariff_eur_mwh) AS spot_price_eur_mwh
FROM meter_telemetry
WHERE recorded_at >= NOW() - INTERVAL '15 minutes'
GROUP BY time_bucket
ORDER BY time_bucket DESC;
""",

    "grafana/provisioning/datasources/datasource.yml": """\
apiVersion: 1

datasources:
  - name: SmartGrid-Postgres
    type: postgres
    uid: smartgrid_pg
    url: postgres:5432
    user: grid_admin
    secureJsonData:
      password: grid_password
    jsonData:
      database: smartgrid
      sslmode: 'disable'
      postgresVersion: 1600
      timescaledb: false
    isDefault: true
    editable: true
""",

    "grafana/provisioning/dashboards/provider.yml": """\
apiVersion: 1

providers:
  - name: 'GridPulse Dashboards'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 5
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
""",

    "grafana/provisioning/dashboards/gridpulse_main.json": """\
{
  "uid": "gridpulse-dso",
  "title": "GridPulse City Telemetry",
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "2s",
  "time": {
    "from": "now-5m",
    "to": "now"
  },
  "panels": [
    {
      "id": 1,
      "title": "City Power Balance (Gross Load vs. Solar PV vs. Net Substation Flow)",
      "type": "timeseries",
      "gridPos": { "h": 9, "w": 12, "x": 0, "y": 0 },
      "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
      "fieldConfig": {
        "defaults": {
          "unit": "kwatt",
          "custom": { "fillOpacity": 15, "lineWidth": 2 }
        }
      },
      "targets": [
        {
          "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
          "editorMode": "code",
          "format": "time_series",
          "rawQuery": true,
          "rawSql": "SELECT time_bucket AS \\"time\\", total_demand_kw AS \\"Gross Demand (kW)\\", total_solar_kw AS \\"Solar Generation (kW)\\", city_net_import_kw AS \\"Net Substation Flow (kW)\\" FROM city_grid_summary WHERE $__timeFilter(time_bucket) ORDER BY 1;",
          "refId": "A"
        }
      ]
    },
    {
      "id": 2,
      "title": "Low-Voltage Feeder Envelope (Min / Mean / Max Voltage)",
      "type": "timeseries",
      "gridPos": { "h": 9, "w": 12, "x": 12, "y": 0 },
      "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
      "fieldConfig": {
        "defaults": {
          "unit": "volt",
          "custom": { "fillOpacity": 10, "lineWidth": 2 }
        }
      },
      "targets": [
        {
          "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
          "editorMode": "code",
          "format": "time_series",
          "rawQuery": true,
          "rawSql": "SELECT time_bucket AS \\"time\\", max_voltage_v AS \\"Max Feeder V\\", avg_voltage_v AS \\"City Mean V\\", min_voltage_v AS \\"Min Feeder V\\" FROM city_grid_summary WHERE $__timeFilter(time_bucket) ORDER BY 1;",
          "refId": "A"
        }
      ]
    },
    {
      "id": 3,
      "title": "Grid Frequency (Hz) & Storage Dispatch (kW)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 9 },
      "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
      "targets": [
        {
          "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
          "editorMode": "code",
          "format": "time_series",
          "rawQuery": true,
          "rawSql": "SELECT time_bucket AS \\"time\\", grid_frequency_hz AS \\"Frequency (Hz)\\" FROM city_grid_summary WHERE $__timeFilter(time_bucket) ORDER BY 1;",
          "refId": "A"
        }
      ]
    },
    {
      "id": 4,
      "title": "Dynamic Spot Tariff (EUR / MWh)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 9 },
      "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
      "fieldConfig": {
        "defaults": {
          "unit": "currencyEUR",
          "custom": { "fillOpacity": 20, "lineWidth": 2 }
        }
      },
      "targets": [
        {
          "datasource": { "type": "postgres", "uid": "smartgrid_pg" },
          "editorMode": "code",
          "format": "time_series",
          "rawQuery": true,
          "rawSql": "SELECT time_bucket AS \\"time\\", spot_price_eur_mwh AS \\"Spot Price (EUR/MWh)\\" FROM city_grid_summary WHERE $__timeFilter(time_bucket) ORDER BY 1;",
          "refId": "A"
        }
      ]
    }
  ]
}
""",

    "app/requirements.txt": """\
fastapi==0.115.0
uvicorn[standard]==0.30.6
jinja2==3.1.4
pika==1.3.2
psycopg2-binary==2.9.9
pydantic==2.9.2
""",

    "app/Dockerfile": """\
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",

    "app/simulator_and_worker.py": """\
import json
import math
import os
import random
import threading
import time
from datetime import datetime, timezone
import pika
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL", "postgresql://grid_admin:grid_password@localhost:5432/smartgrid")
RMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RMQ_USER = os.getenv("RABBITMQ_USER", "grid_broker")
RMQ_PASS = os.getenv("RABBITMQ_PASS", "broker_password")

SIM_STATE = {
    "scenario": "NORMAL_OPERATION",
    "solar_irradiance_factor": 1.0,
    "cloud_cover_pct": 15.0,
    "ev_surge_multiplier": 1.0,
    "demand_response_curtailment": False,
    "battery_mode": "AUTO_SELF_CONSUME",
    "simulated_hour": 13.0,
    "auto_advance_time": True
}

SCENARIO_PRESETS = {
    "NORMAL_OPERATION": {
        "solar_irradiance_factor": 1.0,
        "cloud_cover_pct": 15.0,
        "ev_surge_multiplier": 1.0,
        "demand_response_curtailment": False,
        "battery_mode": "AUTO_SELF_CONSUME",
        "simulated_hour": 13.5,
        "severity": "INFO",
        "description": "Balanced prosumer grid operation with moderate midday solar feed-in."
    },
    "SOLAR_PEAK_VOLTAGE_SWELL": {
        "solar_irradiance_factor": 1.45,
        "cloud_cover_pct": 0.0,
        "ev_surge_multiplier": 0.2,
        "demand_response_curtailment": False,
        "battery_mode": "AUTO_SELF_CONSUME",
        "simulated_hour": 12.5,
        "severity": "WARNING",
        "description": "Clear-sky solar spike causing reverse power flow into substations and local feeder over-voltage."
    },
    "EV_COMMUTER_SURGE": {
        "solar_irradiance_factor": 0.15,
        "cloud_cover_pct": 40.0,
        "ev_surge_multiplier": 4.5,
        "demand_response_curtailment": False,
        "battery_mode": "AUTO_SELF_CONSUME",
        "simulated_hour": 19.0,
        "severity": "CRITICAL",
        "description": "19:00 evening peak: simultaneous 11kW/22kW EV charging with fading solar, causing voltage sag."
    },
    "CLOUD_TRANSIENT_DROP": {
        "solar_irradiance_factor": 0.25,
        "cloud_cover_pct": 92.0,
        "ev_surge_multiplier": 1.2,
        "demand_response_curtailment": False,
        "battery_mode": "FORCE_DISCHARGE_TO_GRID",
        "simulated_hour": 14.0,
        "severity": "WARNING",
        "description": "Sudden storm front drops city PV output by 80%; home batteries automatically discharge to stabilize grid."
    },
    "SMART_GRID_DEMAND_RESPONSE": {
        "solar_irradiance_factor": 0.4,
        "cloud_cover_pct": 50.0,
        "ev_surge_multiplier": 3.0,
        "demand_response_curtailment": True,
        "battery_mode": "FORCE_DISCHARGE_TO_GRID",
        "simulated_hour": 18.5,
        "severity": "INFO",
        "description": "DSO activates Virtual Power Plant (VPP): throttles EV wallboxes by 70% and dispatches residential batteries."
    }
}

HOUSEHOLDS = []
BATTERY_SOC = {}

def seed_households():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    districts = [
        ("Solar Suburb", 12, 0.95, 12.0, 15.0, 0.22),
        ("Downtown Core", 10, 0.50, 6.0, 8.0, 0.10),
        ("Industrial Edge", 8, 0.85, 20.0, 25.0, 0.16)
    ]
    idx = 1
    for dist_name, count, solar_prob, avg_pv, avg_bat, impedance in districts:
        for _ in range(count):
            h_id = f"CH-ZRH-{idx:03d}"
            has_solar = random.random() < solar_prob
            pv_cap = round(random.uniform(avg_pv * 0.7, avg_pv * 1.4), 2) if has_solar else 0.0
            bat_cap = round(random.uniform(avg_bat * 0.6, avg_bat * 1.3), 2) if has_solar else 0.0
            has_ev = random.random() < 0.65
            imp = round(random.uniform(impedance * 0.8, impedance * 1.25), 4)

            cur.execute(\"\"\"
                INSERT INTO households (house_id, district, has_solar, solar_capacity_kw, battery_capacity_kwh, has_ev_charger, feeder_impedance_ohm)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (house_id) DO NOTHING;
            \"\"\", (h_id, dist_name, has_solar, pv_cap, bat_cap, has_ev, imp))

            HOUSEHOLDS.append({
                "house_id": h_id,
                "district": dist_name,
                "has_solar": has_solar,
                "solar_capacity_kw": pv_cap,
                "battery_capacity_kwh": bat_cap,
                "has_ev_charger": has_ev,
                "impedance": imp
            })
            BATTERY_SOC[h_id] = random.uniform(35.0, 75.0)
            idx += 1

    cur.execute("SELECT COUNT(*) FROM grid_events;")
    if cur.fetchone()[0] == 0:
        cur.execute(\"\"\"
            INSERT INTO grid_events (scenario_name, severity, description)
            VALUES ('SYSTEM_BOOT', 'INFO', 'GridPulse SCADA telemetry engine initialized with 30 prosumer smart meters.')
        \"\"\")
    conn.commit()
    cur.close()
    conn.close()

def simulate_and_publish():
    credentials = pika.PlainCredentials(RMQ_USER, RMQ_PASS)
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RMQ_HOST, credentials=credentials))
            channel = connection.channel()
            channel.exchange_declare(exchange="grid.telemetry", exchange_type="topic", durable=True)
            break
        except Exception:
            time.sleep(2)

    while True:
        if SIM_STATE["auto_advance_time"]:
            SIM_STATE["simulated_hour"] = (SIM_STATE["simulated_hour"] + 0.05) % 24.0

        hour = SIM_STATE["simulated_hour"]
        sun_angle = math.sin(math.pi * (hour - 6.0) / 14.0) if 6.0 <= hour <= 20.0 else 0.0
        cloud_attenuation = 1.0 - (SIM_STATE["cloud_cover_pct"] / 100.0) * 0.85
        solar_factor = max(0.0, sun_angle * cloud_attenuation * SIM_STATE["solar_irradiance_factor"])
        base_load_profile = 1.0 + 0.8 * math.exp(-((hour - 8.0) ** 2) / 3.0) + 1.4 * math.exp(-((hour - 19.5) ** 2) / 4.0)

        city_net_load = 0.0
        payloads = []

        for h in HOUSEHOLDS:
            h_id = h["house_id"]
            cons_kw = max(0.2, random.gauss(0.9 * base_load_profile, 0.25))

            ev_kw = 0.0
            if h["has_ev_charger"]:
                ev_prob = 0.12 * SIM_STATE["ev_surge_multiplier"] * (2.2 if 17.5 <= hour <= 22.0 else 0.4)
                if random.random() < min(0.95, ev_prob):
                    ev_kw = random.choice([7.4, 11.0, 22.0])
                    if SIM_STATE["demand_response_curtailment"]:
                        ev_kw *= 0.30

            prod_kw = round(h["solar_capacity_kw"] * solar_factor * random.uniform(0.92, 1.06), 3) if h["has_solar"] else 0.0

            soc = BATTERY_SOC[h_id]
            bat_kw = 0.0
            surplus = prod_kw - (cons_kw + ev_kw)

            if h["battery_capacity_kwh"] > 0:
                if SIM_STATE["battery_mode"] == "FORCE_DISCHARGE_TO_GRID" and soc > 10.0:
                    bat_kw = min(5.0, h["battery_capacity_kwh"] * 0.4)
                elif SIM_STATE["battery_mode"] == "FORCE_CHARGE" and soc < 95.0:
                    bat_kw = -min(5.0, h["battery_capacity_kwh"] * 0.4)
                else:
                    if surplus > 0.2 and soc < 98.0:
                        bat_kw = -min(surplus, 4.5)
                    elif surplus < -0.2 and soc > 12.0:
                        bat_kw = min(abs(surplus), 4.5)
                BATTERY_SOC[h_id] = max(5.0, min(100.0, soc - (bat_kw * 0.02)))

            net_kw = round((cons_kw + ev_kw) - prod_kw - bat_kw, 3)
            city_net_load += net_kw

            voltage_v = round(230.0 - (net_kw * h["impedance"] * 1.45) + random.uniform(-0.6, 0.6), 2)
            reactive_kvar = round(net_kw * random.uniform(0.15, 0.28), 3)
            payloads.append((h, cons_kw, prod_kw, bat_kw, BATTERY_SOC[h_id], ev_kw, net_kw, reactive_kvar, voltage_v))

        freq_hz = round(50.000 - (city_net_load * 0.00045) + random.uniform(-0.008, 0.008), 3)
        tariff_eur = round(85.0 + (city_net_load * 0.65), 2)

        timestamp = datetime.now(timezone.utc).isoformat()
        for h, cons_kw, prod_kw, bat_kw, soc, ev_kw, net_kw, q_kvar, v_volt in payloads:
            msg = {
                "recorded_at": timestamp,
                "house_id": h["house_id"],
                "district": h["district"],
                "consumption_kw": round(cons_kw, 3),
                "production_kw": round(prod_kw, 3),
                "battery_kw": round(bat_kw, 3),
                "battery_soc": round(soc, 2),
                "ev_load_kw": round(ev_kw, 3),
                "net_grid_kw": net_kw,
                "reactive_kvar": q_kvar,
                "voltage_v": v_volt,
                "frequency_hz": freq_hz,
                "tariff_eur_mwh": tariff_eur,
                "active_scenario": SIM_STATE["scenario"]
            }
            routing_key = f"district.{h['district'].replace(' ', '_').lower()}.house.{h['house_id']}"
            channel.basic_publish(exchange="grid.telemetry", routing_key=routing_key, body=json.dumps(msg))

        time.sleep(1.5)

def consume_and_persist():
    credentials = pika.PlainCredentials(RMQ_USER, RMQ_PASS)
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RMQ_HOST, credentials=credentials))
            channel = connection.channel()
            channel.exchange_declare(exchange="grid.telemetry", exchange_type="topic", durable=True)
            result = channel.queue_declare(queue="postgres_ingestion_queue", durable=True)
            channel.queue_bind(exchange="grid.telemetry", queue=result.method.queue, routing_key="district.*.house.*")
            break
        except Exception:
            time.sleep(2)

    db_conn = psycopg2.connect(DB_URL)
    buffer = []
    last_flush = time.time()

    def callback(ch, method, properties, body):
        nonlocal buffer, last_flush
        data = json.loads(body)
        buffer.append((
            data["recorded_at"], data["house_id"], data["district"],
            data["consumption_kw"], data["production_kw"], data["battery_kw"],
            data["battery_soc"], data["ev_load_kw"], data["net_grid_kw"],
            data["reactive_kvar"], data["voltage_v"], data["frequency_hz"],
            data["tariff_eur_mwh"], data["active_scenario"]
        ))
        ch.basic_ack(delivery_tag=method.delivery_tag)

        if len(buffer) >= 30 or (time.time() - last_flush) >= 1.5:
            with db_conn.cursor() as cur:
                execute_values(cur, \"\"\"
                    INSERT INTO meter_telemetry (
                        recorded_at, house_id, district, consumption_kw, production_kw,
                        battery_kw, battery_soc, ev_load_kw, net_grid_kw, reactive_kvar,
                        voltage_v, frequency_hz, tariff_eur_mwh, active_scenario
                    ) VALUES %s
                \"\"\", buffer)
                if random.random() < 0.05:
                    cur.execute("DELETE FROM meter_telemetry WHERE recorded_at < NOW() - INTERVAL '20 minutes';")
            db_conn.commit()
            buffer.clear()
            last_flush = time.time()

    channel.basic_qos(prefetch_count=100)
    channel.basic_consume(queue="postgres_ingestion_queue", on_message_callback=callback)
    channel.start_consuming()

def start_background_workers():
    seed_households()
    threading.Thread(target=simulate_and_publish, daemon=True).start()
    threading.Thread(target=consume_and_persist, daemon=True).start()
""",

    "app/main.py": """\
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from simulator_and_worker import SIM_STATE, SCENARIO_PRESETS, start_background_workers, DB_URL

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_background_workers()
    yield

app = FastAPI(title="GridPulse DSO Control Plane", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

class ScenarioTrigger(BaseModel):
    scenario_key: str

class CustomParameters(BaseModel):
    solar_irradiance_factor: float
    cloud_cover_pct: float
    ev_surge_multiplier: float
    demand_response_curtailment: bool
    battery_mode: str
    simulated_hour: float
    auto_advance_time: bool

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/status")
def get_grid_status():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("SELECT * FROM city_grid_summary LIMIT 1;")
    latest = cur.fetchone() or {}

    cur.execute(\"\"\"
        SELECT district,
               ROUND(SUM(consumption_kw + ev_load_kw)::numeric, 2) AS demand_kw,
               ROUND(SUM(production_kw)::numeric, 2) AS solar_kw,
               ROUND(SUM(net_grid_kw)::numeric, 2) AS net_kw,
               ROUND(AVG(voltage_v)::numeric, 1) AS avg_v,
               ROUND(AVG(battery_soc)::numeric, 1) AS avg_soc
        FROM meter_telemetry
        WHERE recorded_at >= NOW() - INTERVAL '4 seconds'
        GROUP BY district
        ORDER BY district;
    \"\"\")
    districts = cur.fetchall()

    cur.execute("SELECT * FROM grid_events ORDER BY triggered_at DESC LIMIT 6;")
    events = cur.fetchall()
    cur.close()
    conn.close()

    return {
        "sim_state": SIM_STATE,
        "metrics": latest,
        "districts": districts,
        "events": events,
        "presets": SCENARIO_PRESETS
    }

@app.post("/api/scenario")
def trigger_scenario(payload: ScenarioTrigger):
    preset = SCENARIO_PRESETS.get(payload.scenario_key)
    if not preset:
        return {"status": "error", "message": "Unknown scenario"}

    SIM_STATE["scenario"] = payload.scenario_key
    for k in ["solar_irradiance_factor", "cloud_cover_pct", "ev_surge_multiplier",
              "demand_response_curtailment", "battery_mode", "simulated_hour"]:
        SIM_STATE[k] = preset[k]

    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
        cur.execute(\"\"\"
            INSERT INTO grid_events (scenario_name, severity, description)
            VALUES (%s, %s, %s)
        \"\"\", (payload.scenario_key, preset["severity"], preset["description"]))
    conn.commit()
    conn.close()
    return {"status": "ok", "sim_state": SIM_STATE}

@app.post("/api/custom-params")
def update_custom_params(params: CustomParameters):
    SIM_STATE["scenario"] = "CUSTOM_SANDBOX"
    SIM_STATE.update(params.model_dump())
    return {"status": "ok", "sim_state": SIM_STATE}
""",

    "app/templates/index.html": """\
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <title>GridPulse | DSO Bidirectional Smart Grid Control Plane</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0b0f19; color: #e2e8f0; font-family: system-ui, -apple-system, sans-serif; }
    .card { background-color: #111827; border: 1px solid #1f2937; border-radius: 0.75rem; }
  </style>
</head>
<body class="min-h-screen p-6">
  <header class="flex flex-wrap justify-between items-center pb-5 mb-6 border-b border-gray-800">
    <div>
      <div class="flex items-center gap-3">
        <span class="h-3 w-3 rounded-full bg-emerald-400 animate-pulse"></span>
        <h1 class="text-2xl font-bold tracking-tight text-white">GridPulse DSO — Bidirectional Energy Control Center</h1>
      </div>
      <p class="text-sm text-gray-400 mt-1">Real-Time Prosumer Telemetry • RabbitMQ AMQP Ingestion • PostgreSQL & Grafana Analytics</p>
    </div>
    <div class="flex items-center gap-4 mt-3 sm:mt-0">
      <div class="px-4 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm">
        Simulated Time: <span id="sim-clock" class="font-mono font-bold text-amber-400">13:00</span>
      </div>
      <div class="px-4 py-2 rounded-lg bg-indigo-950/60 border border-indigo-700 text-sm">
        Active Scenario: <span id="active-scenario-badge" class="font-mono font-bold text-indigo-300">NORMAL_OPERATION</span>
      </div>
      <a href="http://localhost:15672" target="_blank" class="px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs font-medium text-gray-200 transition">
        RabbitMQ Broker ↗
      </a>
      <a href="http://localhost:3000/d/gridpulse-dso/gridpulse-city-telemetry" target="_blank" class="px-3 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-xs font-semibold text-white transition">
        Open Full Grafana ↗
      </a>
    </div>
  </header>

  <section class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
    <div class="card p-4">
      <p class="text-xs text-gray-400 uppercase">City Gross Demand</p>
      <p id="kpi-demand" class="text-2xl font-bold text-rose-400 mt-1">-- kW</p>
      <p class="text-xs text-gray-500 mt-1">Households + EV Chargers</p>
    </div>
    <div class="card p-4">
      <p class="text-xs text-gray-400 uppercase">Rooftop Solar Feed-In</p>
      <p id="kpi-solar" class="text-2xl font-bold text-amber-400 mt-1">-- kW</p>
      <p class="text-xs text-gray-500 mt-1">Distributed PV Generation</p>
    </div>
    <div class="card p-4">
      <p class="text-xs text-gray-400 uppercase">Net Substation Flow</p>
      <p id="kpi-net" class="text-2xl font-bold text-emerald-400 mt-1">-- kW</p>
      <p id="kpi-net-dir" class="text-xs text-gray-500 mt-1">Balancing City Grid</p>
    </div>
    <div class="card p-4">
      <p class="text-xs text-gray-400 uppercase">Feeder Voltage (Avg / Max)</p>
      <p id="kpi-voltage" class="text-2xl font-bold text-sky-400 mt-1">-- V</p>
      <p class="text-xs text-gray-500 mt-1">Nominal 230V ±10%</p>
    </div>
    <div class="card p-4">
      <p class="text-xs text-gray-400 uppercase">Grid Frequency</p>
      <p id="kpi-freq" class="text-2xl font-bold text-purple-400 mt-1">-- Hz</p>
      <p class="text-xs text-gray-500 mt-1">Target 50.000 Hz</p>
    </div>
    <div class="card p-4">
      <p class="text-xs text-gray-400 uppercase">Dynamic Spot Price</p>
      <p id="kpi-price" class="text-2xl font-bold text-teal-400 mt-1">-- €/MWh</p>
      <p class="text-xs text-gray-500 mt-1">Real-time Prosumer Tariff</p>
    </div>
  </section>

  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
    <div class="lg:col-span-4 space-y-6">
      <div class="card p-5">
        <h2 class="text-base font-semibold text-white mb-1">1. One-Click Scenario Generator</h2>
        <p class="text-xs text-gray-400 mb-4">Inject realistic city-wide grid conditions into the RabbitMQ telemetry stream.</p>
        <div class="space-y-2.5">
          <button onclick="setScenario('NORMAL_OPERATION')" class="w-full text-left p-3 rounded-lg bg-gray-800/80 hover:bg-gray-800 border border-gray-700 transition">
            <div class="font-semibold text-sm text-emerald-400">Normal Balanced Prosumer Day</div>
            <div class="text-xs text-gray-400">Moderate solar export, nominal 230V feeder voltage.</div>
          </button>
          <button onclick="setScenario('SOLAR_PEAK_VOLTAGE_SWELL')" class="w-full text-left p-3 rounded-lg bg-gray-800/80 hover:bg-gray-800 border border-amber-700/60 transition">
            <div class="font-semibold text-sm text-amber-400">Midday Solar Peak & Voltage Swell</div>
            <div class="text-xs text-gray-400">Massive PV injection drives negative net load, pushing feeder voltage above 246V.</div>
          </button>
          <button onclick="setScenario('EV_COMMUTER_SURGE')" class="w-full text-left p-3 rounded-lg bg-gray-800/80 hover:bg-gray-800 border border-rose-700/60 transition">
            <div class="font-semibold text-sm text-rose-400">Evening EV Commuter Overload</div>
            <div class="text-xs text-gray-400">Simultaneous 11–22kW EV charging at dusk causes voltage sag and frequency drop.</div>
          </button>
          <button onclick="setScenario('CLOUD_TRANSIENT_DROP')" class="w-full text-left p-3 rounded-lg bg-gray-800/80 hover:bg-gray-800 border border-sky-700/60 transition">
            <div class="font-semibold text-sm text-sky-400">Sudden Storm Cloud Front</div>
            <div class="text-xs text-gray-400">92% cloud cover collapses PV generation; residential batteries discharge to buffer grid.</div>
          </button>
          <button onclick="setScenario('SMART_GRID_DEMAND_RESPONSE')" class="w-full text-left p-3 rounded-lg bg-gray-800/80 hover:bg-gray-800 border border-indigo-600/60 transition">
            <div class="font-semibold text-sm text-indigo-400">Virtual Power Plant (VPP) Stabilization</div>
            <div class="text-xs text-gray-400">DSO curtails EV wallboxes to 30% and dispatches home batteries to shave peak load.</div>
          </button>
        </div>
      </div>

      <div class="card p-5">
        <h2 class="text-base font-semibold text-white mb-3">2. Live Physics Sandbox Overrides</h2>
        <div class="space-y-4 text-xs">
          <div>
            <div class="flex justify-between mb-1">
              <span>Cloud Cover (%)</span>
              <span id="val-cloud" class="font-mono text-amber-400">15%</span>
            </div>
            <input id="inp-cloud" type="range" min="0" max="100" value="15" class="w-full" onchange="pushCustomParams()">
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span>Solar Irradiance Multiplier</span>
              <span id="val-solar" class="font-mono text-amber-400">1.0x</span>
            </div>
            <input id="inp-solar" type="range" min="0" max="1.6" step="0.05" value="1.0" class="w-full" onchange="pushCustomParams()">
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span>EV Charging Surge Factor</span>
              <span id="val-ev" class="font-mono text-rose-400">1.0x</span>
            </div>
            <input id="inp-ev" type="range" min="0" max="5.0" step="0.2" value="1.0" class="w-full" onchange="pushCustomParams()">
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span>Simulated Hour of Day (0–24h)</span>
              <span id="val-hour" class="font-mono text-sky-400">13.0h</span>
            </div>
            <input id="inp-hour" type="range" min="0" max="23.9" step="0.25" value="13.0" class="w-full" onchange="pushCustomParams()">
          </div>
          <div class="flex items-center justify-between pt-2 border-t border-gray-800">
            <span>Battery Dispatch Policy</span>
            <select id="inp-bat" class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white" onchange="pushCustomParams()">
              <option value="AUTO_SELF_CONSUME">Auto Self-Consumption</option>
              <option value="FORCE_DISCHARGE_TO_GRID">VPP Force Export to Grid</option>
              <option value="FORCE_CHARGE">Force Grid Charging</option>
            </select>
          </div>
          <div class="flex items-center justify-between">
            <span>Demand Response (Throttle EVs)</span>
            <input id="inp-dr" type="checkbox" class="h-4 w-4" onchange="pushCustomParams()">
          </div>
          <div class="flex items-center justify-between">
            <span>Auto-Advance Time Clock</span>
            <input id="inp-autoclk" type="checkbox" checked class="h-4 w-4" onchange="pushCustomParams()">
          </div>
        </div>
      </div>
    </div>

    <div class="lg:col-span-8 space-y-6">
      <div class="card p-5">
        <h2 class="text-base font-semibold text-white mb-3">District Substation Telemetry (Live 1.5s RabbitMQ Feed)</h2>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm">
            <thead class="text-xs text-gray-400 uppercase border-b border-gray-800">
              <tr>
                <th class="py-2">City District</th>
                <th class="py-2">Gross Load (kW)</th>
                <th class="py-2">PV Generation (kW)</th>
                <th class="py-2">Net Feeder Flow (kW)</th>
                <th class="py-2">Avg Voltage (V)</th>
                <th class="py-2">Fleet Battery SoC</th>
              </tr>
            </thead>
            <tbody id="district-tbody" class="divide-y divide-gray-800 font-mono text-xs">
              <tr><td colspan="6" class="py-4 text-center text-gray-500">Waiting for RabbitMQ stream...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card p-5">
        <div class="flex justify-between items-center mb-3">
          <div>
            <h2 class="text-base font-semibold text-white">Embedded Grafana Observability Plane</h2>
            <p class="text-xs text-gray-400">Auto-provisioned PostgreSQL time-series dashboard refreshing every 2 seconds.</p>
          </div>
          <span class="text-xs font-mono text-emerald-400">UID: gridpulse-dso</span>
        </div>
        <iframe id="grafana-frame"
                src="http://localhost:3000/d/gridpulse-dso/gridpulse-city-telemetry?orgId=1&refresh=2s&kiosk"
                class="w-full h-[460px] rounded-lg border border-gray-800 bg-gray-950"></iframe>
      </div>

      <div class="card p-5">
        <h2 class="text-base font-semibold text-white mb-2">SCADA Scenario & Protection Log</h2>
        <div id="event-log" class="space-y-2 text-xs max-h-36 overflow-y-auto"></div>
      </div>
    </div>
  </div>

  <script>
    async function setScenario(key) {
      await fetch('/api/scenario', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scenario_key: key})
      });
      fetchStatus(true);
    }

    async function pushCustomParams() {
      const payload = {
        cloud_cover_pct: parseFloat(document.getElementById('inp-cloud').value),
        solar_irradiance_factor: parseFloat(document.getElementById('inp-solar').value),
        ev_surge_multiplier: parseFloat(document.getElementById('inp-ev').value),
        simulated_hour: parseFloat(document.getElementById('inp-hour').value),
        battery_mode: document.getElementById('inp-bat').value,
        demand_response_curtailment: document.getElementById('inp-dr').checked,
        auto_advance_time: document.getElementById('inp-autoclk').checked
      };
      await fetch('/api/custom-params', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      fetchStatus(false);
    }

    async function fetchStatus(syncSliders = false) {
      const res = await fetch('/api/status');
      const data = await res.json();
      const s = data.sim_state;
      const m = data.metrics || {};

      const hrs = Math.floor(s.simulated_hour);
      const mins = Math.floor((s.simulated_hour - hrs) * 60);
      document.getElementById('sim-clock').innerText = `${String(hrs).padStart(2,'0')}:${String(mins).padStart(2,'0')}`;
      document.getElementById('active-scenario-badge').innerText = s.scenario;

      document.getElementById('val-cloud').innerText = `${Math.round(s.cloud_cover_pct)}%`;
      document.getElementById('val-solar').innerText = `${s.solar_irradiance_factor.toFixed(2)}x`;
      document.getElementById('val-ev').innerText = `${s.ev_surge_multiplier.toFixed(1)}x`;
      document.getElementById('val-hour').innerText = `${s.simulated_hour.toFixed(1)}h`;

      if (syncSliders) {
        document.getElementById('inp-cloud').value = s.cloud_cover_pct;
        document.getElementById('inp-solar').value = s.solar_irradiance_factor;
        document.getElementById('inp-ev').value = s.ev_surge_multiplier;
        document.getElementById('inp-hour').value = s.simulated_hour;
        document.getElementById('inp-bat').value = s.battery_mode;
        document.getElementById('inp-dr').checked = s.demand_response_curtailment;
      }

      if (m.total_demand_kw !== undefined) {
        document.getElementById('kpi-demand').innerText = `${Number(m.total_demand_kw).toFixed(1)} kW`;
        document.getElementById('kpi-solar').innerText = `${Number(m.total_solar_kw).toFixed(1)} kW`;
        const net = Number(m.city_net_import_kw);
        document.getElementById('kpi-net').innerText = `${net.toFixed(1)} kW`;
        document.getElementById('kpi-net-dir').innerText = net < 0 ? "EXPORTING SURPLUS TO HV GRID" : "IMPORTING FROM HV GRID";
        document.getElementById('kpi-voltage').innerText = `${Number(m.avg_voltage_v).toFixed(1)}V / ${Number(m.max_voltage_v).toFixed(1)}V`;
        document.getElementById('kpi-freq').innerText = `${Number(m.grid_frequency_hz).toFixed(3)} Hz`;
        document.getElementById('kpi-price').innerText = `${Number(m.spot_price_eur_mwh).toFixed(1)} €/MWh`;
      }

      const tbody = document.getElementById('district-tbody');
      if (data.districts && data.districts.length > 0) {
        tbody.innerHTML = data.districts.map(d => {
          const netColor = d.net_kw < 0 ? 'text-emerald-400' : 'text-rose-400';
          const netLabel = d.net_kw < 0 ? `${d.net_kw} kW (Export)` : `+${d.net_kw} kW (Import)`;
          return `<tr class="hover:bg-gray-800/40">
            <td class="py-2.5 font-sans font-medium text-white">${d.district}</td>
            <td class="py-2.5 text-rose-300">${d.demand_kw} kW</td>
            <td class="py-2.5 text-amber-300">${d.solar_kw} kW</td>
            <td class="py-2.5 font-bold ${netColor}">${netLabel}</td>
            <td class="py-2.5 text-sky-300">${d.avg_v} V</td>
            <td class="py-2.5 text-teal-300">${d.avg_soc}%</td>
          </tr>`;
        }).join('');
      }

      const evLog = document.getElementById('event-log');
      if (data.events) {
        evLog.innerHTML = data.events.map(e => `
          <div class="p-2 rounded bg-gray-900 border border-gray-800 flex justify-between">
            <div><span class="font-mono font-bold text-indigo-400">[${e.scenario_name}]</span> ${e.description}</div>
            <span class="text-gray-500 font-mono ml-2">${new Date(e.triggered_at).toLocaleTimeString()}</span>
          </div>
        `).join('');
      }
    }

    fetchStatus(true);
    setInterval(() => fetchStatus(false), 1500);
  </script>
</body>
</html>
"""
}

def main():
    print("Scaffolding GridPulse DSO Prototype...")
    for rel_path, content in FILES.items():
        path = Path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [OK] Created {rel_path}")
    print("\nAll project files generated successfully.")

if __name__ == "__main__":
    main()
