export type AxisField = {field: string; unit: string; label: string};
export type AxisChoice = AxisField & {value: number};
export type CrossedDesign = {
  expected_revision: number; adapter: string; label: string; inputs: Record<string, unknown>;
  bindings?: Record<string, string>; axes: {field: string; values: number[]}[];
};

export function axisChoices(fields: AxisField[], draft: Record<string, string>, bindings: Record<string, string>): AxisChoice[] {
  return fields.flatMap(item => {
    if (item.field === 'targets.*') {
      try {
        const targets: unknown = JSON.parse(draft.targets);
        if (!targets || typeof targets !== 'object' || Array.isArray(targets)) return [];
        return Object.entries(targets).flatMap(([name, value]) => typeof value === 'number' && Number.isFinite(value) ?
          [{field: `targets.${name}`, unit: item.unit, label: `Target · ${name}`, value}] : []);
      } catch { return []; }
    }
    if (bindings[item.field] || !draft[item.field]?.trim()) return [];
    const value = Number(draft[item.field]);
    return Number.isFinite(value) ? [{...item, value}] : [];
  });
}

export function gridLevels(text: string, choice: AxisChoice, maximum: number) {
  const tokens = text.trim().split(/[\s,]+/).filter(Boolean);
  const levels = tokens.map(Number);
  if (levels.length < 2 || levels.length > maximum || tokens.some((token, i) =>
    !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(token) || !Number.isFinite(levels[i])
    || (i > 0 && levels[i] <= levels[i - 1]))) {
    throw new Error(`Enter 2–${maximum} increasing numeric levels for ${choice.label}.`);
  }
  if (!levels.includes(choice.value)) throw new Error(`Include the reference value ${choice.value} for ${choice.label}.`);
  return levels;
}
