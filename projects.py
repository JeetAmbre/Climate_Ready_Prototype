"""Project management backed by SQLAlchemy / Google Cloud SQL / SQLite fallback."""
import uuid
import json
from datetime import datetime
from database import SessionLocal, ProjectModel, InterventionModel, DecisionPlanModel, init_db

init_db()

class ProjectStore:
    def __init__(self):
        init_db()

    def list_projects(self, user_id=None):
        if not user_id:
            return []
        db = SessionLocal()
        try:
            projects = db.query(ProjectModel).filter(
                ProjectModel.user_id == user_id
            ).order_by(ProjectModel.created_at.desc()).all()
            return [p.to_dict() for p in projects]
        finally:
            db.close()

    def get_project(self, project_id):
        db = SessionLocal()
        try:
            p = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if not p:
                return None
            d = p.to_dict()
            d["assessment_data"] = json.loads(p.assessment_data) if p.assessment_data else None
            d["interventions_data"] = json.loads(p.interventions_data) if p.interventions_data else None
            return d
        finally:
            db.close()

    def create_project(self, name, level, location_id, location_name, risk_focus="both", estimated_budget_inr=None, user_id=None):
        if not user_id:
            raise ValueError("Authentication is required to create a project.")
        db = SessionLocal()
        try:
            pid = "proj_" + uuid.uuid4().hex[:10]
            project = ProjectModel(
                id=pid,
                user_id=user_id,
                name=name.strip() or f"{location_name} Resilience Assessment",
                level=level if level in ("district", "subdistrict") else "district",
                location_id=location_id,
                location_name=location_name,
                risk_focus="both",
                estimated_budget_inr=None,
                status="Active Planning",
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            return project.to_dict()
        finally:
            db.close()

    def save_project_assessment(self, project_id, assessment_dict):
        db = SessionLocal()
        try:
            p = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if p:
                p.assessment_data = json.dumps(assessment_dict)
                p.updated_at = datetime.utcnow()
                db.commit()
                return True
            return False
        finally:
            db.close()

    def save_project_interventions(self, project_id, interventions_list):
        db = SessionLocal()
        try:
            p = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if not p:
                return False
            p.interventions_data = json.dumps(interventions_list)
            p.updated_at = datetime.utcnow()
            
            # Also synchronize individual records in the interventions table
            try:
                db.query(InterventionModel).filter(InterventionModel.project_id == project_id).delete()
                for idx, r in enumerate(interventions_list):
                    rec_id = f"rec_{project_id}_{r.get('id', idx+1)}"
                    citation = r.get("source_citation") or (r.get("source_citations", [""])[0] if r.get("source_citations") else "")
                    poly_json = json.dumps(r.get("polygon", [])) if r.get("polygon") else None
                    impact_json = json.dumps(r.get("expected_impact", {})) if r.get("expected_impact") else None
                    
                    im = InterventionModel(
                        id=rec_id,
                        project_id=project_id,
                        n=r.get("n", idx + 1),
                        hazard=r.get("hazard", "uhi"),
                        hazard_label=r.get("hazard_label", "Urban Heat Island"),
                        level=r.get("level", "High"),
                        priority=r.get("priority", "HIGH PRIORITY"),
                        action=r.get("action", "Resilience Action"),
                        observed_typology=r.get("observed_typology"),
                        polygon_geojson=poly_json,
                        lat=float(r.get("lat", 0.0)),
                        lng=float(r.get("lng", 0.0)),
                        place=r.get("place"),
                        risk_score=float(r.get("risk_score", 4.0)),
                        area_sqm=float(r.get("area_sqm", 50000.0)),
                        area_km2=float(r.get("area_km2", 0.05)),
                        polygon_area_sqm=float(r.get("polygon_area_sqm") or r.get("area_sqm") or 50000.0),
                        estimated_intervention_area_sqm=float(r.get("estimated_intervention_area_sqm") or round(float(r.get("polygon_area_sqm") or r.get("area_sqm") or 50000.0) * 0.30, 1)),
                        building_area_sqm=float(r.get("building_area_sqm") or 0.0),
                        road_area_sqm=float(r.get("road_area_sqm") or 0.0),
                        open_area_sqm=float(r.get("open_area_sqm") or 0.0),
                        target_surface_type=str(r.get("target_surface_type") or "Buildings"),
                        allocated_intervention_area_sqm=float(r.get("allocated_intervention_area_sqm") or r.get("estimated_intervention_area_sqm") or round(float(r.get("polygon_area_sqm") or r.get("area_sqm") or 50000.0) * 0.20, 1)),
                        short_description=r.get("short_description") or r.get("why") or "",
                        population_impacted=int(r.get("population_impacted") or 0),
                        implementation_cost_per_sqm=float(r.get("implementation_cost_per_sqm", 1000.0)),
                        implementation_cost_unit=r.get("implementation_cost_unit", "INR/sq.m"),
                        annual_maintenance_cost_per_sqm=float(r.get("annual_maintenance_cost_per_sqm", 80.0)),
                        annual_maintenance_cost_unit=r.get("annual_maintenance_cost_unit", "INR/year/sq.m"),
                        lifespan_years=int(r.get("lifespan_years", 20)),
                        technical_complexity=r.get("technical_complexity", "Medium"),
                        expected_impact_json=impact_json,
                        sustainability=r.get("sustainability", "Sustainable implementation"),
                        source_citation=citation,
                    )
                    db.add(im)
                db.commit()
            except Exception as sub_e:
                db.rollback()
                print(f"[projects] Note on relational intervention insertion: {sub_e}")
                # Ensure JSON cache is at least persisted even if relational table had schema friction
                try:
                    p = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
                    if p:
                        p.interventions_data = json.dumps(interventions_list)
                        p.updated_at = datetime.utcnow()
                        db.commit()
                except Exception as fallback_e:
                    print(f"[projects] Note on JSON fallback commit: {fallback_e}")
            return True
        except Exception as exc:
            db.rollback()
            print(f"[projects] Error saving project interventions: {exc}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            db.close()

    def save_decision_plan(self, project_id: str, plan_dict: dict):
        """Persist finalized, locked adaptation plan into Cloud SQL."""
        db = SessionLocal()
        try:
            p = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if not p:
                return None

            plan_id = f"plan_{project_id}_{uuid.uuid4().hex[:8]}"
            brief_content = plan_dict.get("ai_decision_brief")
            if isinstance(brief_content, dict):
                brief_content = json.dumps(brief_content)

            proportions_dict = plan_dict.get("proportions") or plan_dict.get("plan_proportions") or {}
            proportions_json = json.dumps(proportions_dict) if isinstance(proportions_dict, dict) else None

            effective_areas_dict = plan_dict.get("effective_areas") or {}
            effective_areas_json = json.dumps(effective_areas_dict) if isinstance(effective_areas_dict, dict) else None

            dp = DecisionPlanModel(
                id=plan_id,
                project_id=project_id,
                stakeholder_type=plan_dict.get("stakeholder_type", "municipal_dpr"),
                allocated_budget_inr=float(plan_dict.get("allocated_budget_inr", 0.0)),
                coverage_pct=float(plan_dict.get("coverage_pct", 30.0)),
                optimization_goal=plan_dict.get("optimization_goal", "people_protected"),
                selected_recommendation_ids=json.dumps(plan_dict.get("selected_recommendation_ids", [])),
                plan_proportions_json=proportions_json,
                effective_areas_json=effective_areas_json,
                total_capex_inr=float(plan_dict.get("total_capex_inr", 0.0)),
                total_annual_opex_inr=float(plan_dict.get("total_annual_opex_inr", 0.0)),
                total_population_protected=int(plan_dict.get("total_population_protected", 0)),
                total_treatable_area_sqm=float(plan_dict.get("total_treatable_area_sqm", 0.0)),
                ai_decision_brief=brief_content,
                status="Locked",
                locked_at=datetime.utcnow(),
            )
            db.add(dp)

            # Update InterventionModel rows with chosen proportion and effective area
            if isinstance(proportions_dict, dict):
                for item_id, pct in proportions_dict.items():
                    item = db.query(InterventionModel).filter(InterventionModel.id == item_id).first()
                    if item:
                        item.proportion_pct = float(pct)
                        if isinstance(effective_areas_dict, dict) and item_id in effective_areas_dict:
                            item.effective_intervention_area_sqm = float(effective_areas_dict[item_id])

            # Update project status to reflect locked adaptation plan
            p.status = "Plan Locked / Tracking Ready"
            p.updated_at = datetime.utcnow()

            db.commit()
            db.refresh(dp)
            return dp.to_dict()
        except Exception as exc:
            db.rollback()
            print(f"[projects] Error saving decision plan: {exc}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            db.close()

    def save_plan_impact_summary(self, project_id: str, impact_summary: dict):
        """Save post-intervention impact calculation summary to active locked plan."""
        db = SessionLocal()
        try:
            dp = (
                db.query(DecisionPlanModel)
                .filter(DecisionPlanModel.project_id == project_id)
                .order_by(DecisionPlanModel.locked_at.desc())
                .first()
            )
            if not dp:
                return None
            dp.impact_summary_json = json.dumps(impact_summary)
            db.commit()
            db.refresh(dp)
            return dp.to_dict()
        except Exception as exc:
            db.rollback()
            print(f"[projects] Error updating impact summary: {exc}")
            return None
        finally:
            db.close()

    def get_locked_plan(self, project_id: str):
        """Fetch the active locked adaptation plan for a project."""
        db = SessionLocal()
        try:
            dp = (
                db.query(DecisionPlanModel)
                .filter(DecisionPlanModel.project_id == project_id)
                .order_by(DecisionPlanModel.locked_at.desc())
                .first()
            )
            return dp.to_dict() if dp else None
        finally:
            db.close()

    def delete_project(self, project_id):
        db = SessionLocal()
        try:
            p = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if p:
                db.delete(p)
                db.commit()
                return True
            return False
        finally:
            db.close()


project_store = ProjectStore()

