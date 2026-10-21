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
