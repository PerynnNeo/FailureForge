export type Inputs = Record<string, unknown>;
export type InputSchema = {
  title?: string; description?: string; type?: string; $ref?: string;
  properties?: Record<string, InputSchema>; required?: string[]; $defs?: Record<string, InputSchema>;
  anyOf?: InputSchema[]; enum?: unknown[]; const?: unknown; default?: unknown;
  minimum?: number; maximum?: number; exclusiveMinimum?: number; exclusiveMaximum?: number;
};
export type Adapter = {
  id: string; label: string; description: string; example: Inputs; schema: InputSchema;
  binding_units?: Record<string, string>; binding_accepted_units?: Record<string, string[]>;
  phase_fields?: Record<string, string>;
};
export type InputField = { name: string; schema: InputSchema; type: string; required: boolean };
export type RunInput = { label: string; adapter: string; inputs: Inputs; bindings?: Record<string, string> };
export type RunSummary = {
  id: string; label: string; adapter: string; project_revision: number;
  created_at: string | number; status: string; error?: string | null; suite_id?: string; attempt?: number;
  reference_example?: number;
};
export type RunDetail = RunSummary & {
  inputs: Inputs; result?: Inputs | null; snapshot?: Inputs; definition?: RunInput; binding_evidence?: Inputs;
  runtime?: Inputs | null; evidence_hash?: string | null; assessment_error?: string | null;
  recheck_of?: string | null; calibration_run_id?: string | null;
};

const units: Record<string, string> = { _w_m2k: 'W/(m²·K)', _w_mk: 'W/(m·K)', _w_m3: 'W/m³', _n_per_m: 'N/m', _per_s: '1/s', _m2: 'm²', _kg: 'kg', _pa: 'Pa', _k: 'K', _n: 'N', _m: 'm', _rad: 'rad', _ms: 'ms', _s: 's' };
export function fieldCaption(field: InputField) {
  const suffix = Object.keys(units).find(key => field.name.endsWith(key));
  if (!suffix) return field.schema.title ?? field.name.replaceAll('_', ' ');
  const name = field.name.slice(0, -suffix.length).replaceAll('_', ' ');
  return `${name[0].toUpperCase()}${name.slice(1)} (${units[suffix]})`;
}

export function inputFields(adapter: Adapter): InputField[] {
  const root = adapter.schema;
  const properties = root.properties ?? {};
  const names = new Set([...Object.keys(adapter.example), ...Object.keys(properties)]);
  return [...names].map(name => {
    const declared = properties[name] ?? {};
    const definition = declared.$ref?.split('/').at(-1);
    const schema = definition && root.$defs?.[definition] || declared;
    const example = adapter.example[name];
    const type = schema.type ?? schema.anyOf?.find(choice => choice.type && choice.type !== 'null')?.type
      ?? (Array.isArray(example) ? 'array' : example == null ? 'string' : typeof example);
    return { name, schema, type, required: (root.required ?? []).includes(name) };
  });
}

export function fieldText(value: unknown): string {
  if (value == null) return '';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

export const referenceHandChoice = 'builtin:two_finger_hand_v1';

export function rodBoundaryFields(draft: Record<string, string>, bindings: Record<string, string>) {
  const fluidFields = ['right_ambient_temperature_k', 'right_film_coefficient_w_m2k'];
  const fluid = draft.rightBoundaryChoice !== undefined ? draft.rightBoundaryChoice === 'fluid'
    : fluidFields.some(name => Boolean(draft[name]?.trim() || bindings[name]));
  return {
    fluid,
    required: fluid ? fluidFields : ['right_temperature_k'],
    hidden: fluid ? ['right_temperature_k'] : fluidFields,
  };
}

/** A saved motion test with no asset ID was authored for the built-in hand. */
export function motionModelChoice(inputs: Inputs | undefined, referenceProject: boolean) {
  if (typeof inputs?.model_asset_id === 'string' && inputs.model_asset_id) return inputs.model_asset_id;
  return inputs || referenceProject ? referenceHandChoice : '';
}

export function runInputs(adapterId: string, fields: InputField[], draft: Record<string, string>): Inputs {
  if (adapterId !== 'robot_motion') return parseFields(fields, draft);
  if (!draft.model_asset_id) throw new Error('Choose an attached URDF or explicitly select the built-in two-finger reference hand.');
  return parseFields(fields, draft.model_asset_id === referenceHandChoice ? { ...draft, model_asset_id: '' } : draft);
}

export function parseFields(fields: InputField[], draft: Record<string, string>): Inputs {
  const inputs: Inputs = {};
  for (const { name, type, required } of fields) {
    const value = draft[name] ?? '';
    if (!value.trim()) {
      if (required) throw new Error(`Enter a value for ${name}.`);
      continue;
    }
    if (type === 'string') { inputs[name] = value; continue; }
    if (type === 'number' || type === 'integer') {
      const numeric = Number(value);
      if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim()) ||
        !Number.isFinite(numeric) || (type === 'integer' && !Number.isInteger(numeric))) {
        throw new Error(`Enter a valid ${type} for ${name}.`);
      }
      inputs[name] = numeric;
      continue;
    }
    try {
      const parsed: unknown = JSON.parse(value);
      const valid = type === 'array' ? Array.isArray(parsed)
        : type === 'object' ? parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
        : type === 'boolean' ? typeof parsed === 'boolean' : true;
      if (!valid) throw new Error();
      inputs[name] = parsed;
    } catch {
      throw new Error(`Enter a valid ${type} for ${name}.`);
    }
  }
  return inputs;
}
