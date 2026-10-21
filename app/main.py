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

    cur.execute("""
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
    """)
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
        cur.execute("""
            INSERT INTO grid_events (scenario_name, severity, description)
            VALUES (%s, %s, %s)
        """, (payload.scenario_key, preset["severity"], preset["description"]))
    conn.commit()
    conn.close()
    return {"status": "ok", "sim_state": SIM_STATE}

@app.post("/api/custom-params")
def update_custom_params(params: CustomParameters):
    SIM_STATE["scenario"] = "CUSTOM_SANDBOX"
    SIM_STATE.update(params.model_dump())
    return {"status": "ok", "sim_state": SIM_STATE}
