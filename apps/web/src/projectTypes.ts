export type EntryStage = 'concept' | 'cad' | 'model' | 'simulation' | 'prototype';
export type AnalysisType = 'robot_behavior' | 'structural' | 'thermal';
export type ParameterSource = 'imported' | 'supplier' | 'estimated' | 'measured' | 'calibrated';
export type AssetKind = 'cad' | 'robot_model' | 'controller' | 'bom' | 'scene' | 'measurements' | 'requirements';

export interface ProjectParameter {
  name: string; value: string; unit: string; source: ParameterSource;
  range_min?: number | null; range_max?: number | null; evidence: string;
}
export interface ProjectTestPlan {
  name: string; objective: string; success_criteria: string; variation: string;
  timeout_seconds?: number | null;
}
export interface OperatingFactor {
  name: string; field: string; unit: string; conditions: string; required_values: number[];
}
export interface ProjectInput {
  name: string; entry_stage: EntryStage; analysis_type: AnalysisType; goal: string;
  success_criteria: string; robot_source: 'custom' | 'supported'; robot_template?: string | null;
  notes: string; parameters: ProjectParameter[]; test_plans: ProjectTestPlan[]; operating_factors: OperatingFactor[];
}
export interface ProjectAsset {
  id: string; filename: string; kind: AssetKind; size_bytes: number; sha256: string; download_url: string;
  created_at: string | number; inspection: { status: string; format: string; summary: string; warnings: string[]; details: Record<string, unknown> };
}
export interface ProjectReadiness {
  phase: string; execution_allowed: boolean;
  checks: { id: string; label: string; status: string; detail: string }[];
  next_action: string; limitations: string[];
  phases: { id: string; label: string; status: string; detail: string }[];
}
export interface ProjectCatalog {
  allowed_extensions: Record<AssetKind, string[]>;
  robot_templates: { id: string; label: string; description: string; execution_available: boolean }[];
  limits: { asset_bytes: number; max_assets: number; max_parameters: number; max_test_plans: number };
  capability_notice: string;
}
export interface Project extends ProjectInput {
  id: string; revision: number; created_at: string | number; updated_at: string | number;
  assets: ProjectAsset[]; readiness: ProjectReadiness;
}

export const stageOptions: { value: EntryStage; title: string; short: string; description: string }[] = [
  { value: 'concept', title: 'I have an idea', short: 'Concept', description: 'Define the job, risks, and information you need. No model required.' },
  { value: 'cad', title: 'I have a CAD design', short: 'CAD design', description: 'Organize geometry, parts, materials, and missing physical properties.' },
  { value: 'model', title: 'I have a robot model', short: 'Robot model', description: 'Bring a robot description and prepare its controller and test environment.' },
  { value: 'simulation', title: 'I have a simulation', short: 'Existing simulation', description: 'Record your experiment, variations, and the evidence each test should produce.' },
  { value: 'prototype', title: 'I have a physical prototype', short: 'Physical prototype', description: 'Connect measurements to a digital model and plan calibration and regression tests.' },
];
export const analysisOptions: { value: AnalysisType; title: string; description: string; boundary: string }[] = [
  { value: 'robot_behavior', title: 'Robot behavior', description: 'Does the robot complete its task when conditions change?', boundary: 'Use the project’s Analysis tab to run supported motion studies and calibration with explicit model inputs. The LIBERO policy benchmark is available in Campaigns.' },
  { value: 'structural', title: 'Strength & deformation', description: 'Could a part bend, yield, or break under specified loads?', boundary: 'Model a fixed-base beam with specified geometry, elastic modulus, and loads. Review predicted deflection and compare revisions in the Analysis tab.' },
  { value: 'thermal', title: 'Heat & cooling', description: 'Could a component exceed its temperature limit?', boundary: 'Model a steady-state rod with a fixed left temperature. Set the right surface temperature or specify the surrounding fluid temperature and end-face heat transfer coefficient.' },
];
export const assetKinds: { value: AssetKind; title: string; hint: string }[] = [
  { value: 'requirements', title: 'Requirements / sketches / references', hint: 'The intended task, acceptance criteria, concept sketches, or reference images. Images are stored without reconstructing geometry.' },
  { value: 'cad', title: 'CAD geometry', hint: 'Attach CAD geometry. The CAD inventory analysis accepts supported STL inputs.' },
  { value: 'robot_model', title: 'Robot description', hint: 'URDF / MJCF descriptions can receive basic text inspection. Referenced assets must also be supplied.' },
  { value: 'controller', title: 'Controller / simulation package', hint: 'Attach a JSON controller configuration for the reference hand. Other scripts and packages are stored as source material.' },
  { value: 'bom', title: 'Bill of materials', hint: 'Part names, selected components, and supplier references.' },
  { value: 'scene', title: 'Environment / object', hint: 'Test objects, workspace geometry, and scene configuration.' },
  { value: 'measurements', title: 'Physical measurements', hint: 'Measurements, calibration notes, or recorded hardware behavior.' },
];
export const emptyProject = (): ProjectInput => ({ name: '', entry_stage: 'concept', analysis_type: 'robot_behavior', goal: '', success_criteria: '', robot_source: 'custom', robot_template: null, notes: '', parameters: [], test_plans: [], operating_factors: [] });
export function projectInput(project: Project): ProjectInput {
  const { name, entry_stage, analysis_type, goal, success_criteria, robot_source, robot_template, notes, parameters, test_plans } = project;
  return { name, entry_stage, analysis_type, goal, success_criteria, robot_source, robot_template, notes, parameters, test_plans, operating_factors: project.operating_factors ?? [] };
}
