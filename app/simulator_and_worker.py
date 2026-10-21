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

            cur.execute("""
                INSERT INTO households (house_id, district, has_solar, solar_capacity_kw, battery_capacity_kwh, has_ev_charger, feeder_impedance_ohm)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (house_id) DO NOTHING;
            """, (h_id, dist_name, has_solar, pv_cap, bat_cap, has_ev, imp))

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
        cur.execute("""
            INSERT INTO grid_events (scenario_name, severity, description)
            VALUES ('SYSTEM_BOOT', 'INFO', 'GridPulse SCADA telemetry engine initialized with 30 prosumer smart meters.')
        """)
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
                execute_values(cur, """
                    INSERT INTO meter_telemetry (
                        recorded_at, house_id, district, consumption_kw, production_kw,
                        battery_kw, battery_soc, ev_load_kw, net_grid_kw, reactive_kvar,
                        voltage_v, frequency_hz, tariff_eur_mwh, active_scenario
                    ) VALUES %s
                """, buffer)
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
