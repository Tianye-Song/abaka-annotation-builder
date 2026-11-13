import type { WidgetProps } from ".";

export function ChoiceField({ field, value, onChange, readOnly }: WidgetProps) {
  const choices: string[] = field.choices;
  if (field.multiple) {
    const set = new Set<string>(value ?? []);
    const toggle = (c: string) => {
      const next = new Set(set);
      next.has(c) ? next.delete(c) : next.add(c);
      onChange(choices.filter((x) => next.has(x)));
    };
    return (
      <div className="choices">
        {choices.map((c) => (
          <label key={c} className={`chip ${set.has(c) ? "on" : ""}`}>
            <input type="checkbox" disabled={readOnly} checked={set.has(c)} onChange={() => toggle(c)} /> {c}
          </label>
        ))}
      </div>
    );
  }
  return (
    <div className="choices">
      {choices.map((c) => (
        <label key={c} className={`chip ${value === c ? "on" : ""}`}>
          <input type="radio" disabled={readOnly} checked={value === c} onChange={() => onChange(c)} /> {c}
        </label>
      ))}
      {!readOnly && value != null && !field.required && (
        <button className="link" onClick={() => onChange(null)}>clear</button>
      )}
    </div>
  );
}

export function TextField({ field, value, onChange, readOnly }: WidgetProps) {
  const props = {
    value: value ?? "",
    readOnly,
    placeholder: field.placeholder ?? "",
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
  };
  return field.multiline ? <textarea rows={4} {...props} /> : <input type="text" {...props} />;
}

export function RatingField({ field, value, onChange, readOnly }: WidgetProps) {
  const min = field.min ?? 1, max = field.max ?? 5;
  const labels: Record<string, string> = field.labels ?? {};
  const range = Array.from({ length: max - min + 1 }, (_, i) => min + i);
  return (
    <div className="rating">
      {range.map((n) => (
        <button
          key={n}
          type="button"
          disabled={readOnly && value !== n}
          className={value === n ? "on" : ""}
          onClick={() => !readOnly && onChange(n)}
          title={labels[n] ?? ""}
        >
          {n}
          {labels[n] && <small>{labels[n]}</small>}
        </button>
      ))}
    </div>
  );
}
