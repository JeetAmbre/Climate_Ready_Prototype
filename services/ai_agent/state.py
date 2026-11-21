"""Agent State and Pydantic Schema definitions for ClimateReady LangGraph framework."""
from typing import TypedDict, Optional, Any, List, Dict, Literal
from pydantic import BaseModel, Field


# ---------------- Pydantic Output Schemas (Structured Output) ----------------

class ExpectedImpactSchema(BaseModel):
    surface_temp_reduction_c: Optional[str] = Field(default="", description="Surface cooling in °C, e.g. '8-15'")
    indoor_or_ambient_temp_reduction_c: Optional[str] = Field(default="", description="Ambient/indoor air drop in °C, e.g. '2-3.5'")
    runoff_reduction_pct: Optional[str] = Field(default="", description="Peak runoff reduction percentage, e.g. '35-50'")
    summary: str = Field(default="", description="Quantified impact summary statement")


class InterventionItemSchema(BaseModel):
    id: int = Field(description="Numerical ID 1 to 10")
    n: int = Field(description="Display number 1 to 5 per hazard")
    hazard: Literal["uhi", "waterlogging"] = Field(description="Target hazard ('uhi' or 'waterlogging')")
    hazard_label: str = Field(description="'Urban Heat Island' or 'Waterlogging'")
    level: str = Field(default="High", description="'Very High', 'High', or 'Moderate'")
    priority: str = Field(default="HIGH PRIORITY", description="'VERY HIGH PRIORITY' or 'HIGH PRIORITY'")
    place: str = Field(description="Verified hotspot location name")
    lat: float = Field(description="Center pin GPS latitude")
    lng: float = Field(description="Center pin GPS longitude")
    polygon: List[List[float]] = Field(default_factory=list, description="Contiguous boundary coordinates [[lat, lng], ...]")
    area_sqm: float = Field(default=50000.0, description="Area in square metres")
    area_km2: float = Field(default=0.05, description="Area in square kilometres")
    polygon_area_sqm: Optional[float] = Field(default=50000.0, description="Gross polygon geodesic area in sq.m")
    building_area_sqm: Optional[float] = Field(default=0.0, description="Open Buildings footprint inside polygon in sq.m")
    road_area_sqm: Optional[float] = Field(default=0.0, description="Road / corridor built surface inside polygon in sq.m")
    open_area_sqm: Optional[float] = Field(default=0.0, description="Bare and grass open surface inside polygon in sq.m")
    target_surface_type: Literal["Buildings", "Roads", "Open Area"] = Field(default="Buildings", description="Physical surface targeted: 'Buildings', 'Roads', or 'Open Area'")
    allocated_intervention_area_sqm: float = Field(default=5000.0, description="Capped realistic pilot/ward implementation area in sq.m (never 100% of polygon)")
    estimated_intervention_area_sqm: float = Field(default=5000.0, description="Realistic practical/treatable intervention area in sq.m (feasible fraction of polygon area)")
    risk_score: float = Field(default=4.0, description="Local risk severity score")
    site_context_summary: str = Field(description="Site context summary inferred from the zone's physical indicator signature")
    observed_typology: Optional[str] = Field(default="", description="Observed ground typology or site context")
    indicator: str = Field(default="High Hazard Vulnerability", description="Dominant biophysical driving indicator")
    indicator_signature: Dict[str, Any] = Field(default_factory=dict, description="Zonal sub-indicator values")
    action: str = Field(description="Simplified user-friendly intervention name: practical, scientifically credible Nature-based or engineering resilience action")
    short_description: str = Field(default="", description="Crisp 1-2 sentence plain English explanation of what will be implemented and why")
    why: str = Field(default="", description="Scientific rationale anchored in the indicator profile")
    addresses: str = Field(default="", description="'Urban Heat Island Vulnerability' or 'Urban Waterlogging & Monsoon Runoff'")
    implementation_cost_per_sqm: float = Field(description="Numeric implementation cost in INR per sq.m")
    implementation_cost_unit: str = Field(default="INR/sq.m", description="Standardized cost unit")
    annual_maintenance_cost_per_sqm: float = Field(description="Numeric annual maintenance cost in INR/year per sq.m")
    annual_maintenance_cost_unit: str = Field(default="INR/year/sq.m", description="Standardized maintenance unit")
    lifespan_years: int = Field(description="Intervention lifespan in years")
    technical_complexity: Literal["Low", "Medium", "High"] = Field(description="Technical implementation complexity")
    expected_impact: ExpectedImpactSchema = Field(description="Quantified expected cooling or runoff reduction metrics")
    sustainability: str = Field(description="Environmental and long-term sustainability rating and notes")
    source_citation: str = Field(description="Exact authoritative source citation (NDMA, NIUA, CPWD, UNEP, WRI India)")
    source_citations: List[str] = Field(default_factory=list, description="List of source citations for backwards compatibility")


class InterventionsListSchema(BaseModel):
    interventions: List[InterventionItemSchema] = Field(description="List of prioritized resilience interventions")


# ---------------- TypedDict State for LangGraph Workflow ----------------

class HotspotZoneProfile(TypedDict, total=False):
    id: int
    n: int
    hazard: str
    hazard_label: str
    lat: float
    lng: float
    polygon: List[List[float]]
    area_sqm: float
    area_km2: float
    polygon_area_sqm: float
    building_area_sqm: float
    road_area_sqm: float
    open_area_sqm: float
    risk_score: float
    level: str
    priority: str
    place: str
    dominant_indicator_label: str
    indicator_signature: Dict[str, Any]
    site_context_summary: str


class InterventionRecommendation(TypedDict, total=False):
    id: int
    n: int
    hazard: str
    hazard_label: str
    level: str
    priority: str
    place: str
    lat: float
    lng: float
    polygon: List[List[float]]
    area_sqm: float
    area_km2: float
    polygon_area_sqm: float
    building_area_sqm: float
    road_area_sqm: float
    open_area_sqm: float
    target_surface_type: str
    allocated_intervention_area_sqm: float
    estimated_intervention_area_sqm: float
    risk_score: float
    site_context_summary: str
    observed_typology: str
    indicator: str
    indicator_signature: Dict[str, Any]
    action: str
    short_description: str
    why: str
    addresses: str
    implementation_cost_per_sqm: float
    implementation_cost_unit: str
    annual_maintenance_cost_per_sqm: float
    annual_maintenance_cost_unit: str
    lifespan_years: int
    technical_complexity: str
    expected_impact: Dict[str, Any]
    sustainability: str
    source_citation: str
    source_citations: List[str]


class AgentState(TypedDict, total=False):
    """Shared state for ClimateReady LangGraph agent workflows."""
    assessment_id: str
    location_info: Dict[str, Any]
    risk_profile_data: Dict[str, Any]
    target_risk: str
    hotspots: List[HotspotZoneProfile]
    recommendations: List[InterventionRecommendation]
    messages: List[Any]
    current_step: str
    error: Optional[str]
