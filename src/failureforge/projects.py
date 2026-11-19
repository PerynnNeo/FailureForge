"""Staged hardware intake. Uploaded assets are evidence, never executable plugins."""
from __future__ import annotations

import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .contracts import utc_now
from .persistence import Conflict, Store, new_id

ASSET_LIMIT = 10 * 1024 * 1024
INSPECTION_LIMIT = 2 * 1024 * 1024
MAX_ASSETS = 40
AssetKind = Literal["cad", "robot_model", "controller", "bom", "scene", "measurements", "requirements"]
EXTENSIONS = {
    "cad": {".step", ".stp", ".stl", ".obj", ".iges", ".igs", ".glb", ".gltf", ".ply"},
    "robot_model": {".urdf", ".mjcf", ".xml", ".json"},
    "controller": {".py", ".json", ".yaml", ".yml", ".txt", ".zip", ".onnx", ".pt", ".pth"},
    "bom": {".csv", ".json", ".txt", ".xlsx"},
    "scene": {".usd", ".usda", ".usdc", ".usdz", ".xml", ".json", ".glb", ".gltf", ".zip"},
    "measurements": {".csv", ".json", ".txt"},
    "requirements": {".pdf", ".txt", ".md", ".json", ".png", ".jpg", ".jpeg", ".webp"},
}


class IntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Parameter(IntakeModel):
    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=300)
    unit: str = Field(default="", max_length=50)
    source: Literal["imported", "supplier", "estimated", "measured", "calibrated"]
    range_min: FiniteFloat | None = Field(default=None, strict=True)
    range_max: FiniteFloat | None = Field(default=None, strict=True)
    evidence: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def ordered_range(self):
        if (self.range_min is None) != (self.range_max is None):
            raise ValueError("Provide both range endpoints or leave both empty")
        if self.range_min is not None and self.range_min > self.range_max:
            raise ValueError("Range minimum must not exceed maximum")
        return self


class TestPlan(IntakeModel):
    name: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1500)
    success_criteria: str = Field(min_length=1, max_length=1500)
    variation: str = Field(min_length=1, max_length=1500)
    timeout_seconds: FiniteFloat | None = Field(default=None, gt=0, le=86400, strict=True)


class ProjectSpec(IntakeModel):
    name: str = Field(min_length=1, max_length=120)
    entry_stage: Literal["concept", "cad", "model", "simulation", "prototype"]
    analysis_type: Literal["robot_behavior", "structural", "thermal"]
    goal: str = Field(min_length=1, max_length=3000)
    success_criteria: str = Field(min_length=1, max_length=3000)
    robot_source: Literal["custom", "supported"] = "custom"
    robot_template: Literal["two_finger_hand_v1", "packaging_lift_v1", "leap_hand_v1", "franka_panda"] | None = None
    notes: str = Field(default="", max_length=6000)
    parameters: list[Parameter] = Field(default_factory=list, max_length=80)
    test_plans: list[TestPlan] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def consistent_intake(self):
        if self.robot_source == "supported" and self.robot_template is None:
            raise ValueError("Select a reference robot when using supported-robot preparation")
        if self.robot_source == "custom" and self.robot_template is not None:
            raise ValueError("A custom robot must not claim a reference robot template")
        for label, items in (("parameter", self.parameters), ("test plan", self.test_plans)):
            names = [item.name.casefold() for item in items]
            if len(names) != len(set(names)):
                raise ValueError(f"Each {label} must have a unique name")
        return self


class ProjectUpdate(ProjectSpec):
    expected_revision: int = Field(ge=1, strict=True)


def project_catalog():
    return {
        "entry_stages": [
            {"id": "concept", "label": "Idea or requirements", "description": "Define the task, failure rules, assumptions, and files to prepare."},
            {"id": "cad", "label": "CAD assembly", "description": "Record geometry, materials, components, and missing physical properties."},
            {"id": "model", "label": "Robot model", "description": "Inspect a robot description and prepare its controller and environment."},
            {"id": "simulation", "label": "Existing simulation", "description": "Inventory a runnable experiment and plan repeatable test suites."},
            {"id": "prototype", "label": "Physical prototype", "description": "Attach measurements and record calibration evidence for comparison."},
        ],
        "analysis_types": [
            {"id": "robot_behavior", "label": "Robot task behavior", "description": "Test articulated motion or evaluate a reference packaging lift across operating conditions.", "execution_available": True},
            {"id": "structural", "label": "Structural analysis", "description": "Evaluate a rectangular cantilever with declared supports, dimensions and loads.", "execution_available": True},
            {"id": "thermal", "label": "Thermal analysis", "description": "Evaluate a uniform rod with fixed end temperatures and internal heating.", "execution_available": True},
        ],
        "robot_templates": [
            {"id": "two_finger_hand_v1", "label": "FailureForge two-finger hand", "description": "Bundled fixed-palm hand, version 1.0, MIT. The MuJoCo test measures contact-free joint tracking and fingertip separation.", "execution_available": True},
            {"id": "packaging_lift_v1", "label": "Packaging lift", "description": "A fixed vertical carriage and controller raise a secured tray and hold it under a downward packing-head load. Vary tray payload and applied force.", "execution_available": True},
            {"id": "leap_hand_v1", "label": "LEAP Hand v1", "description": "Reference for hand-manipulation preparation; upload your model and controller. No hand execution adapter is installed.", "execution_available": False},
            {"id": "franka_panda", "label": "Franka Panda", "description": "Reference for manipulation preparation; this does not connect a project to the separate fixed LIBERO benchmark.", "execution_available": False},
        ],
        "parameter_sources": ["imported", "supplier", "estimated", "measured", "calibrated"],
        "asset_kinds": list(EXTENSIONS),
        "allowed_extensions": {kind: sorted(values) for kind, values in EXTENSIONS.items()},
        "limits": {"asset_bytes": ASSET_LIMIT, "inspection_bytes": INSPECTION_LIMIT, "max_assets": MAX_ASSETS, "max_parameters": 80, "max_test_plans": 30},
        "capability_notice": "Use Analysis & runs for bounded model execution, calibration, suites and regression. Each adapter declares its inputs, assumptions and units. LEAP and Panda intake templates provide planning guidance.",
    }


def derive_readiness(project):
    """Only infer preparation completeness. User assertions never qualify execution."""
    assets, parameters, plans = project["assets"], project["parameters"], project["test_plans"]
    kinds = {asset["kind"] for asset in assets}
    behavior = project["analysis_type"] == "robot_behavior"
    model_present = "robot_model" in kinds if behavior else "cad" in kinds
    controller_present = "controller" in kinds if behavior else True
    checks = [
        {"id": "requirements", "label": "Task and success criteria", "status": "complete", "detail": "Requirements are recorded. Their engineering adequacy has not been independently reviewed."},
        {"id": "model", "label": "Robot description" if behavior else "Analysis geometry", "status": "review" if model_present else "missing", "detail": "Asset received; syntax inspection does not validate dynamics, material assignments, or model fidelity." if model_present else "Attach a robot model." if behavior else "Attach CAD geometry for the proposed analysis."},
        {"id": "properties", "label": "Physical properties and provenance", "status": "review" if parameters else "missing", "detail": "Recorded parameter values require engineering review, including units and applicability." if parameters else "Record the physical properties and assumptions relevant to the failure mechanism."},
        {"id": "test_plans", "label": "Reusable test definitions", "status": "complete" if plans else "missing", "detail": "Test descriptions are saved; no runnable test adapter has compiled or executed them." if plans else "Define a test objective, measurable success criteria, and conditions to vary."},
    ]
    if behavior:
        checks.insert(2, {"id": "controller", "label": "Controller or prescribed behavior", "status": "review" if controller_present else "missing", "detail": "Controller asset stored without importing or executing it. Its interface still needs integration." if controller_present else "Attach a controller or document prescribed commands in a controller asset."})
    else:
        checks.append({"id": "boundary_conditions", "label": "Loads and supports" if project["analysis_type"] == "structural" else "Heat sources and cooling", "status": "review", "detail": "Document conditions in parameters, requirements, and test plans. Their physical completeness cannot be checked without the analysis adapter."})
    if project["entry_stage"] == "prototype":
        evidence = "measurements" in kinds or any(p["source"] in {"measured", "calibrated"} and p["evidence"] for p in parameters)
        checks.append({"id": "measurements", "label": "Prototype measurements", "status": "review" if evidence else "missing", "detail": "Evidence supplied; no parameter fitting or independent calibration verification has run." if evidence else "Attach measured traces or cite evidence for measured parameters; a physical prototype alone does not calibrate a model."})
    undocumented = [p["name"] for p in parameters if p["source"] in {"measured", "calibrated"} and not p["evidence"]]
    if undocumented:
        checks.append({"id": "parameter_evidence", "label": "Measurement evidence", "status": "missing", "detail": "Add evidence for parameters marked measured or calibrated: " + ", ".join(undocumented[:8])})
    analysis = {"robot_behavior": "Custom robot behavior", "structural": "Structural", "thermal": "Thermal"}[project["analysis_type"]]
    checks.append({"id": "execution_adapter", "label": "Execution from intake alone", "status": "blocked", "detail": f"{analysis} intake is a planning record. Configure an explicit bounded adapter in Analysis & runs to validate inputs and execute a test."})
    if not model_present or not parameters or not controller_present:
        phase, action = "preparation", "Prepare the missing model, physical parameters, and behavior inputs listed below."
    elif not plans:
        phase, action = "test_design", "Define test cases and variations while the imported model awaits engineering validation."
    elif any(check["status"] == "missing" for check in checks):
        phase, action = "validation", "Complete the missing evidence, then review model assumptions and parameter provenance."
    else:
        phase, action = "qualification", "Intake metadata is assembled. Select a supported analysis and review its test inputs."
    phase_details = [
        ("concept", "Define", "Record the intended task and measurable success criteria."),
        ("preparation", "Prepare", "Collect assets and physical parameter assumptions."),
        ("validation", "Review the model", "Inspect syntax and arrange engineering review; physical model validation remains pending."),
        ("test_design", "Design tests", "Describe scenarios, expected behavior, and controlled variations."),
        ("qualification", "Qualify execution", "Connect an analysis adapter, validate the model, and qualify the execution host."),
        ("execution", "Run tests", "Execute an approved model and controller through a supported worker."),
        ("investigation", "Investigate", "Review genuine traces, comparisons, and reproducible failure cases."),
        ("regression", "Compare revisions", "Rerun saved cases against a versioned design or controller change."),
    ]
    statuses = {"concept": "complete", "preparation": "complete" if model_present and parameters and controller_present else "current", "validation": "current" if phase == "validation" else "future", "test_design": "complete" if plans else "current" if phase == "test_design" else "future", "qualification": "blocked", "execution": "blocked", "investigation": "future", "regression": "future"}
    reference_lift = behavior and project.get("robot_template") == "packaging_lift_v1"
    if reference_lift:
        fixture_checks = {
            "model": "The bundled single-axis reference carriage defines its mass, travel and actuator limit.",
            "controller": "The reference controller is fixed across all matrix conditions.",
            "properties": "The packaging-lift adapter supplies the reference design constants and task tolerances.",
            "test_plans": "The adapter defines the lift deadline and hold requirement. Choose the operating points in Analysis & runs.",
            "execution_adapter": "The packaging-lift simulation accepts payload mass and packing-head force.",
        }
        for check in checks:
            if check["id"] in fixture_checks:
                check.update(status="complete", detail=fixture_checks[check["id"]])
                if check["id"] == "execution_adapter":
                    check["label"] = "Reference simulation"
        phase, action = "execution", "Open Analysis & runs to test the payload and packing-head force or inspect a saved matrix."
        statuses.update(preparation="complete", test_design="complete", qualification="future", execution="current")
        phase_details = [(key, "Check numerical accuracy", "Inspect the integration check recorded for each simulated condition.")
                         if key == "qualification" else (key, title, detail) for key, title, detail in phase_details]
    return {"phase": phase, "execution_allowed": reference_lift, "analysis_url": f"/api/projects/{project['id']}/analysis", "checks": checks,
            "phases": [{"id": key, "label": label, "status": statuses[key], "detail": detail} for key, label, detail in phase_details],
            "next_action": action,
            "limitations": ["Readiness describes intake metadata, not a validated physical model or a simulation result.", "Measured and calibrated source labels are user-provided claims; attached evidence is not independently verified.", "Files are never executed, archives are never extracted, and model dependencies are not resolved by this intake service.", "Reference robot choices do not download models or install execution adapters."]}


def inspect_asset(path: Path, filename: str, kind: str):
    extension = Path(filename).suffix.lower()
    result = {"status": "stored", "format": extension.lstrip("."), "summary": "Stored as an opaque attachment. Its contents have not been validated or executed.", "warnings": [], "details": {}}
    if extension not in {".json", ".urdf", ".mjcf", ".xml"}:
        if extension in {".zip", ".usdz", ".xlsx"}:
            result["warnings"].append("Archive contents are not extracted or inspected.")
        return result
    if path.stat().st_size > INSPECTION_LIMIT:
        raise HTTPException(413, "XML and JSON inspection is limited to 2 MiB; no file was accepted")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise HTTPException(422, "XML and JSON assets must use UTF-8 encoding") from exc
    if "\x00" in text:
        raise HTTPException(422, "Null bytes are not accepted in structured assets")
    if extension == ".json":
        def invalid_constant(value):
            raise ValueError("Non-finite JSON number")
        try:
            data = json.loads(text, parse_constant=invalid_constant)
            pending, count = [(data, 0)], 0
            while pending:
                node, depth = pending.pop()
                count += 1
                if count > 20000 or depth > 64:
                    raise ValueError("JSON structure exceeds inspection bounds")
                if isinstance(node, dict):
                    pending.extend((value, depth + 1) for value in node.values())
                elif isinstance(node, list):
                    pending.extend((value, depth + 1) for value in node)
                elif isinstance(node, float):
                    import math
                    if not math.isfinite(node):
                        raise ValueError("Non-finite JSON number")
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, "Invalid or excessively complex JSON asset") from exc
        return {**result, "status": "inspected", "summary": "JSON syntax checked within bounds. No domain schema, physics, or controller validation was performed.", "details": {"top_level_type": type(data).__name__, "nodes": count}}
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise HTTPException(422, "XML document types and entities are not accepted")
    try:
        depth, count = 0, 0
        root = None
        for event, element in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                count += 1
                if depth > 64 or count > 20000:
                    raise ValueError("XML structure exceeds inspection bounds")
            else:
                depth -= 1
        if root is None:
            raise ValueError("Missing root element")
    except (ET.ParseError, ValueError, RecursionError) as exc:
        raise HTTPException(422, "Invalid or excessively complex XML asset") from exc
    if kind == "robot_model" and root.tag not in {"robot", "mujoco"}:
        raise HTTPException(422, "Robot XML must have a URDF robot or MJCF mujoco root")
    references = sorted({element.attrib[key] for element in root.iter() for key in ("filename", "file") if element.attrib.get(key)})
    warnings = ["Syntax inspection only; joint semantics, collisions, units, and dynamics are not validated."]
    if references:
        warnings.append("Referenced resources are not loaded or resolved; supply a complete bundle to a future model adapter.")
    details = {"root": root.tag, "elements": count, "unresolved_references": references[:200], "reference_count": len(references)}
    if root.tag == "robot":
        links = root.findall("link")
        missing = [link.attrib.get("name", "(unnamed)") for link in links if link.find("inertial/mass") is None or link.find("inertial/inertia") is None]
        details.update({"links": len(links), "joints": len(root.findall("joint")), "missing_explicit_inertia": len(missing), "links_without_explicit_inertia": missing[:200]})
        if missing:
            warnings.append("One or more links omit explicit mass or inertia. Engineering review is required; fixed or massless links may be intentional.")
    elif root.tag == "mujoco":
        bodies = list(root.iter("body"))
        missing = [body.attrib.get("name", "(unnamed)") for body in bodies if body.find("inertial") is None]
        details.update({"bodies": len(bodies), "joints": len(list(root.iter("joint"))) + len(list(root.iter("freejoint"))), "missing_explicit_inertia": len(missing)})
        if missing:
            warnings.append("Some MJCF bodies omit explicit inertia; the simulator may derive it from geometry. This inspection does not compile or verify derived values.")
    return {**result, "status": "inspected", "summary": "Bounded XML syntax and inventory inspection completed. This is not a simulator load or model validation.", "warnings": warnings, "details": details}


class ProjectStore:
    def __init__(self, store: Store, root: Path):
        self.store = store
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with store.connection(True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, spec TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_assets (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    filename TEXT NOT NULL, kind TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, inspection TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS project_assets_project ON project_assets(project_id);
                CREATE TABLE IF NOT EXISTS project_revisions (
                    project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL,
                    saved_at TEXT NOT NULL, reason TEXT NOT NULL, snapshot TEXT NOT NULL,
                    PRIMARY KEY(project_id,revision));
            """)
        # Preserve the current state of older installations. Earlier drafts cannot be reconstructed.
        with store.connection(True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_runs'").fetchone():
                db.execute("""INSERT OR IGNORE INTO project_revisions(project_id,revision,saved_at,reason,snapshot)
                              SELECT project_id,project_revision,json_extract(snapshot,'$.updated_at'),
                                     'Retained execution snapshot',snapshot FROM project_runs""")
            for row in db.execute("""SELECT p.id FROM projects p WHERE NOT EXISTS
                   (SELECT 1 FROM project_revisions r WHERE r.project_id=p.id AND r.revision=p.revision)""").fetchall():
                self._remember(db, row["id"], "Imported current revision")

    def _remember(self, db, identifier, reason):
        project = self._get(db, identifier)
        snapshot = {k: v for k, v in project.items() if k != "readiness"}
        db.execute("INSERT INTO project_revisions VALUES(?,?,?,?,?)",
                   (identifier, project["revision"], project["updated_at"], reason, json.dumps(snapshot, allow_nan=False)))
        return project

    @staticmethod
    def asset_data(row):
        asset = dict(row)
        asset["inspection"] = json.loads(asset["inspection"])
        asset["download_url"] = f"/api/projects/{asset['project_id']}/assets/{asset['id']}"
        return asset

    def _get(self, db, identifier):
        row = Store._required(db, "projects", identifier)
        project = {**json.loads(row.pop("spec")), **row}
        project["assets"] = [self.asset_data(asset) for asset in db.execute("SELECT * FROM project_assets WHERE project_id=? ORDER BY created_at,id", (identifier,))]
        project["readiness"] = derive_readiness(project)
        return project

    def get(self, identifier):
        with self.store.connection() as db:
            return self._get(db, identifier)

    def list(self):
        with self.store.connection() as db:
            identifiers = [row["id"] for row in db.execute("SELECT id FROM projects ORDER BY updated_at DESC,id DESC LIMIT 200")]
            return [self._get(db, identifier) for identifier in identifiers]

    def create(self, spec: ProjectSpec, key=None):
        identifier, now = new_id("project"), utc_now()
        with self.store.connection(True) as db:
            if key:
                previous = self.store._idempotent(db, "project-create", key, spec.model_dump())
                if previous:
                    return previous
            db.execute("INSERT INTO projects VALUES(?,1,?,?,?)", (identifier, spec.model_dump_json(), now, now))
            project = self._remember(db, identifier, "Project created")
            if key:
                self.store._remember(db, "project-create", key, spec.model_dump(), project)
            return project

    def update(self, identifier: str, spec: ProjectUpdate):
        with self.store.connection(True) as db:
            return self.update_in_transaction(db, identifier, spec, "Project inputs revised")

    def update_in_transaction(self, db, identifier, spec: ProjectUpdate, reason):
        data = spec.model_dump(exclude={"expected_revision"})
        changed = db.execute("UPDATE projects SET revision=revision+1,spec=?,updated_at=? WHERE id=? AND revision=?",
                             (json.dumps(data, allow_nan=False), utc_now(), identifier, spec.expected_revision))
        if not changed.rowcount:
            Store._required(db, "projects", identifier)
            raise Conflict("Project changed since it was opened. Reload before saving to avoid losing another update.")
        return self._remember(db, identifier, reason)

    def add_asset(self, identifier, asset_id, filename, kind, size, digest, inspection):
        with self.store.connection(True) as db:
            Store._required(db, "projects", identifier)
            count = db.execute("SELECT COUNT(*) FROM project_assets WHERE project_id=?", (identifier,)).fetchone()[0]
            if count >= MAX_ASSETS:
                raise HTTPException(409, "This project already has the maximum of 40 assets")
            db.execute("INSERT INTO project_assets VALUES(?,?,?,?,?,?,?,?)", (asset_id, identifier, filename, kind, size, digest, json.dumps(inspection, allow_nan=False), utc_now()))
            db.execute("UPDATE projects SET revision=revision+1,updated_at=? WHERE id=?", (utc_now(), identifier))
            return self._remember(db, identifier, f"Attached {filename}")

    def asset_path(self, asset_id):
        if not re.fullmatch(r"asset_[0-9a-f]{32}", asset_id):
            raise KeyError(asset_id)
        return self.root / (asset_id + ".blob")

    def asset(self, identifier, asset_id):
        with self.store.connection() as db:
            row = Store._required(db, "project_assets", asset_id)
            if row["project_id"] != identifier:
                raise KeyError(asset_id)
        path = self.asset_path(asset_id)
        if not path.is_file():
            raise HTTPException(409, "Stored asset is missing; no substitute is available")
        if path.stat().st_size != row["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise HTTPException(409, "Stored asset failed its integrity check")
        return row, path


def project_router(store: Store, root: Path):
    projects = ProjectStore(store, root)
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("/catalog")
    def get_catalog():
        return project_catalog()

    @router.get("")
    def list_projects():
        return {"items": projects.list()}

    @router.post("", status_code=201)
    def create_project(spec: ProjectSpec, idempotency_key: str | None = Header(default=None, min_length=8, max_length=200)):
        return projects.create(spec, idempotency_key)

    @router.get("/{identifier}")
    def get_project(identifier: str):
        return projects.get(identifier)

    @router.post("/{identifier}")
    def update_project(identifier: str, spec: ProjectUpdate):
        return projects.update(identifier, spec)

    @router.get("/{identifier}/export")
    def export_project(identifier: str):
        project = projects.get(identifier)
        report = {"schema_version": "failureforge.project-intake.v1", "exported_at": utc_now(), "report_type": "preparation_report", "contains_simulation_results": False, "project": project}
        return Response(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{project["id"]}-intake.json"'})

    @router.get("/{identifier}/revisions")
    def revision_history(identifier: str):
        with store.connection() as db:
            Store._required(db, "projects", identifier)
            rows = db.execute("SELECT revision,saved_at,reason FROM project_revisions WHERE project_id=? ORDER BY revision DESC", (identifier,))
            return {"items": [dict(row) for row in rows]}

    @router.get("/{identifier}/revisions/{revision}")
    def revision_snapshot(identifier: str, revision: int):
        with store.connection() as db:
            row = db.execute("SELECT snapshot FROM project_revisions WHERE project_id=? AND revision=?", (identifier, revision)).fetchone()
            if row is None:
                raise KeyError(revision)
            return json.loads(row["snapshot"])

    @router.post("/{identifier}/assets", status_code=201, openapi_extra={
        "requestBody": {"required": True, "content": {"application/octet-stream": {
            "schema": {"type": "string", "format": "binary"}}}},
    })
    async def upload_asset(identifier: str, request: Request, filename: str, kind: AssetKind):
        project = projects.get(identifier)
        if len(project["assets"]) >= MAX_ASSETS:
            raise HTTPException(409, "This project already has the maximum of 40 assets")
        if (not filename or len(filename) > 160 or filename != filename.strip() or
                any(ord(character) < 32 for character in filename) or any(character in filename for character in '/\\:*?"<>|') or
                filename in {".", ".."} or filename.endswith((".", " ")) or
                filename.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
            raise HTTPException(422, "Supply a filename without paths, control characters, or reserved names")
        if Path(filename).suffix.lower() not in EXTENSIONS[kind]:
            raise HTTPException(422, "This file extension is not accepted for the selected asset kind")
        asset_id, size, digest = new_id("asset"), 0, hashlib.sha256()
        path = projects.asset_path(asset_id)
        accepted = False
        try:
            with path.open("xb") as target:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > ASSET_LIMIT:
                        raise HTTPException(413, "Asset exceeds the 10 MiB upload limit")
                    digest.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise HTTPException(422, "Empty assets are not accepted")
            inspection = inspect_asset(path, filename, kind)
            result = projects.add_asset(identifier, asset_id, filename, kind, size, digest.hexdigest(), inspection)
            accepted = True
            return result
        finally:
            if not accepted:
                path.unlink(missing_ok=True)

    @router.get("/{identifier}/assets/{asset_id}")
    def download_asset(identifier: str, asset_id: str):
        record, path = projects.asset(identifier, asset_id)
        return FileResponse(path, media_type="application/octet-stream", filename=record["filename"], headers={"Content-Security-Policy": "default-src 'none'; sandbox"})

    return router, projects
