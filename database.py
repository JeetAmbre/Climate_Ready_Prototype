"""Database models and database connection for ClimateReady.

Supports Google Cloud SQL (PostgreSQL) when DATABASE_URL or CLOUD_SQL_* env vars are provided,
with an automatic fallback to local SQLite (data/climateready.db) for offline development.
"""
import os
import re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables (.env) are loaded before establishing DB connection
load_dotenv(Path(__file__).resolve().parent / ".env")

from sqlalchemy import create_engine, Column, String, Float, Text, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session, relationship
from sqlalchemy.engine import make_url

Base = declarative_base()


def get_fallback_sqlite():
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "climateready.db"
    return f"sqlite:///{db_path}"


def get_database_url():
    # 0. Google Cloud Run Unix socket connection (K_SERVICE detected)
    is_cloud_run = bool(os.getenv("K_SERVICE"))
    instance_connection_name = os.getenv("INSTANCE_CONNECTION_NAME") or os.getenv("CLOUD_SQL_INSTANCE")
    if is_cloud_run and instance_connection_name:
        user = os.getenv("CLOUD_SQL_USER", "postgres")
        password = os.getenv("CLOUD_SQL_PASSWORD", "")
        db_name = os.getenv("CLOUD_SQL_DATABASE", "climateready")
        socket_dir = os.getenv("DB_SOCKET_DIR", "/cloudsql")
        print(f"[database] Connecting via Cloud Run Unix socket to {instance_connection_name}")
        return f"postgresql+psycopg2://{user}:{password}@/{db_name}?host={socket_dir}/{instance_connection_name}"

    # 1. Direct DATABASE_URL or CLOUD_SQL_DATABASE_URL
    raw_url = (os.getenv("CLOUD_SQL_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if raw_url:
        # Check if user put just the GCP Instance Connection Name (e.g. project:region:instance)
        # instead of a full URI postgresql://...
        if re.match(r"^[^:/@]+:[^:/@]+:[^:/@]+$", raw_url):
            print(f"[database] Note: DATABASE_URL '{raw_url}' looks like a Google Cloud SQL Instance Connection Name.")
            user = os.getenv("CLOUD_SQL_USER") or "postgres"
            password = os.getenv("CLOUD_SQL_PASSWORD") or ""
            host = os.getenv("CLOUD_SQL_HOST") or "127.0.0.1"
            port = os.getenv("CLOUD_SQL_PORT") or "5432"
            db_name = os.getenv("CLOUD_SQL_DATABASE") or "climateready"
            
            if password:
                raw_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"
            else:
                print("[database] No CLOUD_SQL_PASSWORD provided for Cloud SQL instance. Falling back to local SQLite.")
                return get_fallback_sqlite()

        if raw_url.startswith("postgres://"):
            raw_url = raw_url.replace("postgres://", "postgresql://", 1)

        # Validate that SQLAlchemy can parse it
        try:
            make_url(raw_url)
            return raw_url
        except Exception as exc:
            print(f"[database] Warning: Could not parse DATABASE_URL ({exc}). Falling back to local SQLite.")
            return get_fallback_sqlite()

    # 2. Separate Cloud SQL connection params
    user = os.getenv("CLOUD_SQL_USER")
    password = os.getenv("CLOUD_SQL_PASSWORD")
    host = os.getenv("CLOUD_SQL_HOST", "localhost")
    port = os.getenv("CLOUD_SQL_PORT", "5432")
    db_name = os.getenv("CLOUD_SQL_DATABASE", "climateready")
    
    if user and password:
        return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    # 3. Default local fallback SQLite
    return get_fallback_sqlite()


DATABASE_URL = get_database_url()
is_sqlite = DATABASE_URL.startswith("sqlite")

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=True
    )
except Exception as e:
    print(f"[database] Failed to initialize engine with {DATABASE_URL}: {e}. Reverting to SQLite.")
    DATABASE_URL = get_fallback_sqlite()
    is_sqlite = True
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )

SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


class User(Base):
    __tablename__ = "users"
    
    id = Column(String(64), primary_key=True)       # Google sub ID or email
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=True)
    picture = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    projects = relationship("ProjectModel", back_populates="owner", cascade="all, delete-orphan")


class ProjectModel(Base):
    __tablename__ = "projects"
    
    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=True)
    name = Column(String(255), nullable=False)
    level = Column(String(32), default="district")
    location_id = Column(String(64), nullable=False)
    location_name = Column(String(255), nullable=False)
    risk_focus = Column(String(32), default="both")
    estimated_budget_inr = Column(Float, nullable=True)
    status = Column(String(32), default="Active Planning")
    assessment_data = Column(Text, nullable=True)    # JSON cache of assessment results
    interventions_data = Column(Text, nullable=True) # JSON cache of prioritized recommendations
    is_demo = Column(Boolean, default=False, nullable=False)
    demo_badge_label = Column(String(255), default="Demo Assessment · Simulated Project for Evaluation", nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    owner = relationship("User", back_populates="projects")
    interventions = relationship("InterventionModel", back_populates="project", cascade="all, delete-orphan")
    decision_plans = relationship("DecisionPlanModel", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "level": self.level,
            "location_id": self.location_id,
            "location_name": self.location_name,
            "risk_focus": self.risk_focus,
            "estimated_budget_inr": self.estimated_budget_inr,
            "status": self.status,
            "is_demo": bool(self.is_demo),
            "demo_badge_label": self.demo_badge_label or "Demo Assessment · Simulated Project for Evaluation",
            "has_assessment": bool(self.assessment_data),
            "has_interventions": bool(self.interventions_data),
            "has_locked_plan": bool(len(self.decision_plans) > 0) if hasattr(self, "decision_plans") and self.decision_plans else False,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else "",
        }


class InterventionModel(Base):
    __tablename__ = "interventions"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    n = Column(Integer, default=1)
    hazard = Column(String(32), nullable=False)
    hazard_label = Column(String(64), nullable=False)
    level = Column(String(32), default="High")
    priority = Column(String(64), default="HIGH PRIORITY")
    action = Column(String(255), nullable=False)
    observed_typology = Column(String(255), nullable=True)
    polygon_geojson = Column(Text, nullable=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    place = Column(String(255), nullable=True)
    risk_score = Column(Float, nullable=True)
    area_sqm = Column(Float, nullable=True)
    area_km2 = Column(Float, nullable=True)
    polygon_area_sqm = Column(Float, nullable=True)
    estimated_intervention_area_sqm = Column(Float, nullable=True)
    building_area_sqm = Column(Float, nullable=True, default=0.0)
    road_area_sqm = Column(Float, nullable=True, default=0.0)
    open_area_sqm = Column(Float, nullable=True, default=0.0)
    target_surface_type = Column(String(64), nullable=True, default="Buildings")
    allocated_intervention_area_sqm = Column(Float, nullable=True, default=0.0)
    proportion_pct = Column(Float, nullable=True, default=100.0)
    effective_intervention_area_sqm = Column(Float, nullable=True)
    short_description = Column(Text, nullable=True)
    population_impacted = Column(Integer, nullable=True)
    implementation_cost_per_sqm = Column(Float, nullable=True)
    implementation_cost_unit = Column(String(32), default="INR/sq.m")
    annual_maintenance_cost_per_sqm = Column(Float, nullable=True)
    annual_maintenance_cost_unit = Column(String(32), default="INR/year/sq.m")
    lifespan_years = Column(Integer, nullable=True)
    technical_complexity = Column(String(32), default="Medium")
    expected_impact_json = Column(Text, nullable=True)
    sustainability = Column(Text, nullable=True)
    source_citation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("ProjectModel", back_populates="interventions")

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "n": self.n,
            "hazard": self.hazard,
            "hazard_label": self.hazard_label,
            "level": self.level,
            "priority": self.priority,
            "action": self.action,
            "observed_typology": self.observed_typology,
            "polygon": json.loads(self.polygon_geojson) if self.polygon_geojson else [],
            "lat": self.lat,
            "lng": self.lng,
            "place": self.place,
            "risk_score": self.risk_score,
            "area_sqm": self.area_sqm,
            "area_km2": self.area_km2,
            "polygon_area_sqm": self.polygon_area_sqm or self.area_sqm,
            "estimated_intervention_area_sqm": self.estimated_intervention_area_sqm or (round((self.polygon_area_sqm or self.area_sqm or 50000.0) * 0.30, 1)),
            "building_area_sqm": self.building_area_sqm or 0.0,
            "road_area_sqm": self.road_area_sqm or 0.0,
            "open_area_sqm": self.open_area_sqm or 0.0,
            "target_surface_type": self.target_surface_type or "Buildings",
            "allocated_intervention_area_sqm": self.allocated_intervention_area_sqm or self.estimated_intervention_area_sqm or (round((self.polygon_area_sqm or self.area_sqm or 50000.0) * 0.20, 1)),
            "proportion_pct": self.proportion_pct if self.proportion_pct is not None else 100.0,
            "effective_intervention_area_sqm": self.effective_intervention_area_sqm or (round((self.allocated_intervention_area_sqm or self.estimated_intervention_area_sqm or (round((self.polygon_area_sqm or self.area_sqm or 50000.0) * 0.20, 1))) * ((self.proportion_pct if self.proportion_pct is not None else 100.0) / 100.0), 1)),
            "short_description": self.short_description or "",
            "population_impacted": self.population_impacted or 0,
            "implementation_cost_per_sqm": self.implementation_cost_per_sqm,
            "implementation_cost_unit": self.implementation_cost_unit,
            "annual_maintenance_cost_per_sqm": self.annual_maintenance_cost_per_sqm,
            "annual_maintenance_cost_unit": self.annual_maintenance_cost_unit,
            "lifespan_years": self.lifespan_years,
            "technical_complexity": self.technical_complexity,
            "expected_impact": json.loads(self.expected_impact_json) if self.expected_impact_json else {},
            "sustainability": self.sustainability,
            "source_citation": self.source_citation,
            "source_citations": [self.source_citation] if self.source_citation else [],
        }


class DecisionPlanModel(Base):
    __tablename__ = "decision_plans"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    stakeholder_type = Column(String(64), default="municipal_dpr")  # "corporate_csr", "municipal_dpr", "real_estate"
    allocated_budget_inr = Column(Float, nullable=False)
    coverage_pct = Column(Float, default=30.0)
    optimization_goal = Column(String(64), default="people_protected")
    selected_recommendation_ids = Column(Text, nullable=False)  # JSON list of chosen intervention IDs
    total_capex_inr = Column(Float, nullable=False)
    total_annual_opex_inr = Column(Float, nullable=False)
    total_population_protected = Column(Integer, nullable=False)
    total_treatable_area_sqm = Column(Float, nullable=False)
    plan_proportions_json = Column(Text, nullable=True)  # JSON dict of { rec_id: proportion_pct }
    effective_areas_json = Column(Text, nullable=True)   # JSON dict of { rec_id: effective_sqm }
    impact_summary_json = Column(Text, nullable=True)    # JSON dict of post-intervention impact calculation
    ai_decision_brief = Column(Text, nullable=True)  # JSON or Markdown structured brief
    status = Column(String(32), default="Locked")
    locked_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("ProjectModel", back_populates="decision_plans")

    def to_dict(self):
        import json
        brief_data = self.ai_decision_brief
        if brief_data and isinstance(brief_data, str) and brief_data.strip().startswith("{"):
            try:
                brief_data = json.loads(brief_data)
            except Exception:
                pass

        proportions = {}
        if self.plan_proportions_json:
            try:
                proportions = json.loads(self.plan_proportions_json)
            except Exception:
                pass

        effective_areas = {}
        if self.effective_areas_json:
            try:
                effective_areas = json.loads(self.effective_areas_json)
            except Exception:
                pass

        impact_summary = None
        if self.impact_summary_json:
            try:
                impact_summary = json.loads(self.impact_summary_json)
            except Exception:
                pass

        return {
            "id": self.id,
            "project_id": self.project_id,
            "stakeholder_type": self.stakeholder_type,
            "allocated_budget_inr": self.allocated_budget_inr,
            "coverage_pct": self.coverage_pct,
            "optimization_goal": self.optimization_goal,
            "selected_recommendation_ids": json.loads(self.selected_recommendation_ids) if self.selected_recommendation_ids else [],
            "plan_proportions": proportions,
            "effective_areas": effective_areas,
            "impact_summary": impact_summary,
            "total_capex_inr": self.total_capex_inr,
            "total_annual_opex_inr": self.total_annual_opex_inr,
            "total_population_protected": self.total_population_protected,
            "total_treatable_area_sqm": self.total_treatable_area_sqm,
            "ai_decision_brief": brief_data,
            "status": self.status,
            "locked_at": self.locked_at.strftime("%Y-%m-%d %H:%M") if self.locked_at else "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
        }


def init_db():
    Base.metadata.create_all(bind=engine)
    # Safe non-destructive column addition for existing databases (PostgreSQL and SQLite)
    try:
        from sqlalchemy import inspect, text
        insp = inspect(engine)
        if insp.has_table("interventions"):
            existing_cols = {c["name"] for c in insp.get_columns("interventions")}
            columns_to_add = [
                ("polygon_area_sqm", "FLOAT"),
                ("population_impacted", "INTEGER"),
                ("estimated_intervention_area_sqm", "FLOAT"),
                ("short_description", "TEXT"),
                ("building_area_sqm", "FLOAT"),
                ("road_area_sqm", "FLOAT"),
                ("open_area_sqm", "FLOAT"),
                ("target_surface_type", "VARCHAR(64)"),
                ("allocated_intervention_area_sqm", "FLOAT"),
                ("proportion_pct", "FLOAT DEFAULT 100.0"),
                ("effective_intervention_area_sqm", "FLOAT"),
            ]
            for col, col_type in columns_to_add:
                if col not in existing_cols:
                    try:
                        with engine.connect() as conn:
                            try:
                                conn.execute(text(f"ALTER TABLE interventions ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                                conn.commit()
                            except Exception:
                                conn.rollback()
                                conn.execute(text(f"ALTER TABLE interventions ADD COLUMN {col} {col_type}"))
                                conn.commit()
                    except Exception as e:
                        print(f"[init_db] Note adding column {col} to interventions: {e}")

        if insp.has_table("projects"):
            existing_proj_cols = {c["name"] for c in insp.get_columns("projects")}
            proj_cols_to_add = [
                ("is_demo", "BOOLEAN DEFAULT FALSE"),
                ("demo_badge_label", "VARCHAR(255) DEFAULT 'Demo Assessment · Simulated Project for Evaluation'"),
            ]
            for col, col_type in proj_cols_to_add:
                if col not in existing_proj_cols:
                    try:
                        with engine.connect() as conn:
                            try:
                                conn.execute(text(f"ALTER TABLE projects ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                                conn.commit()
                            except Exception:
                                conn.rollback()
                                conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col} {col_type}"))
                                conn.commit()
                    except Exception as e:
                        print(f"[init_db] Note adding column {col} to projects: {e}")

        if insp.has_table("decision_plans"):
            existing_dp_cols = {c["name"] for c in insp.get_columns("decision_plans")}
            dp_columns_to_add = [
                ("plan_proportions_json", "TEXT"),
                ("effective_areas_json", "TEXT"),
                ("impact_summary_json", "TEXT"),
            ]
            for col, col_type in dp_columns_to_add:
                if col not in existing_dp_cols:
                    try:
                        with engine.connect() as conn:
                            try:
                                conn.execute(text(f"ALTER TABLE decision_plans ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                                conn.commit()
                            except Exception:
                                conn.rollback()
                                conn.execute(text(f"ALTER TABLE decision_plans ADD COLUMN {col} {col_type}"))
                                conn.commit()
                    except Exception as e:
                        print(f"[init_db] Note adding column {col} to decision_plans: {e}")
    except Exception as exc:
        print(f"[init_db] Note during schema inspection: {exc}")
