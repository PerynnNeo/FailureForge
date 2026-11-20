export type ThermalChange = {
  ambient_value?: number; ambient_unit?: 'K' | '°C'; end_film_w_m2k?: number;
  fan_rpm?: number; fan_calibration?: string;
};

export function ThermalScenarioFields({ value, onChange }: {
  value: ThermalChange; onChange: (change: ThermalChange) => void;
}) {
  function number(key: 'ambient_value' | 'end_film_w_m2k' | 'fan_rpm', input: HTMLInputElement) {
    onChange({ ...value, [key]: Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : undefined });
  }
  return <fieldset className="scenario-import-fields"><legend>Thermal boundary changes</legend>
    <p>Describe an absolute or relative change, such as “the enclosure reaches 330 K” or “the enclosure warms by 10 °C”, or enter the values below. Each changed boundary gets its own comparison.</p>
    <div className="form-grid">
      <label className="project-field"><span>New ambient temperature</span>
        <input type="number" step="any" value={value.ambient_value ?? ''} onChange={e => number('ambient_value', e.currentTarget)}/>
      </label>
      <label className="project-field"><span>Ambient temperature unit</span>
        <select value={value.ambient_unit ?? 'K'} onChange={e => onChange({ ...value, ambient_unit: e.target.value as 'K' | '°C' })}>
          <option>K</option><option>°C</option>
        </select>
      </label>
      <label className="project-field"><span>New end-face film coefficient (W/(m²·K))</span>
        <input type="number" min="0" max="10000000" step="any" value={value.end_film_w_m2k ?? ''}
          onChange={e => number('end_film_w_m2k', e.currentTarget)}/>
      </label>
    </div>
    <details open={value.fan_rpm !== undefined || value.fan_calibration ? true : undefined}>
      <summary>Changing fan speed?</summary>
      <p>Enter the speed and the source that relates it to the coefficient above for this end face and installation.</p>
      <label className="project-field"><span>Fan speed (RPM)</span>
        <input type="number" min="0" step="any" value={value.fan_rpm ?? ''} onChange={e => number('fan_rpm', e.currentTarget)}/>
      </label>
      <label className="project-field"><span>Fan calibration source or relationship</span>
        <input maxLength={400} value={value.fan_calibration ?? ''} onChange={e => onChange({ ...value, fan_calibration: e.target.value || undefined })}/>
      </label>
    </details>
    <small>The steady-state rod model holds the left temperature fixed and insulates its sides. The reference supplies the acceptance limit, if specified.</small>
  </fieldset>;
}
