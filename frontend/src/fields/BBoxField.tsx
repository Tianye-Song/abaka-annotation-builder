import { useRef, useState } from "react";
import type { WidgetProps } from ".";
import { colorFor, listEditor } from "./shared";

interface Box { x: number; y: number; w: number; h: number; label: string }

/** Draw boxes on the item image. Coordinates are stored in natural image pixels. */
export function BBoxField({ field, value, onChange, item, readOnly }: WidgetProps) {
  const classes: string[] = field.classes;
  const boxes: Box[] = value ?? [];
  const [cls, setCls] = useState(classes[0]);
  const [size, setSize] = useState<{ w: number; h: number } | null>(
    item.meta.width ? { w: item.meta.width, h: item.meta.height } : null,
  );
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const color = colorFor(classes);
  const { update, remove } = listEditor(boxes, onChange);

  const toImage = (e: React.MouseEvent) => {
    const r = svg.current!.getBoundingClientRect();
    const s = size!.w / r.width;
    return {
      x: Math.max(0, Math.min(size!.w, (e.clientX - r.left) * s)),
      y: Math.max(0, Math.min(size!.h, (e.clientY - r.top) * s)),
    };
  };
  const finish = () => {
    if (!drag) return;
    const b = {
      x: Math.round(Math.min(drag.x0, drag.x1)),
      y: Math.round(Math.min(drag.y0, drag.y1)),
      w: Math.round(Math.abs(drag.x1 - drag.x0)),
      h: Math.round(Math.abs(drag.y1 - drag.y0)),
      label: cls,
    };
    setDrag(null);
    if (b.w >= 3 && b.h >= 3) onChange([...boxes, b]);
  };

  return (
    <div className="bbox">
      {!readOnly && (
        <div className="toolbar">
          <span className="muted">Draw class:</span>
          {classes.map((c) => (
            <button key={c} className={`chip ${c === cls ? "on" : ""}`} style={{ borderColor: color(c) }} onClick={() => setCls(c)}>
              <span className="swatch" style={{ background: color(c) }} /> {c}
            </button>
          ))}
        </div>
      )}
      <div className="stage">
        <img
          src={item.media_url!}
          alt={item.external_id}
          draggable={false}
          onLoad={(e) => !size && setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
        {size && (
          <svg
            ref={svg}
            viewBox={`0 0 ${size.w} ${size.h}`}
            className={readOnly ? "" : "drawable"}
            onMouseDown={(e) => { if (readOnly) return; const p = toImage(e); setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }); }}
            onMouseMove={(e) => { if (drag) { const p = toImage(e); setDrag({ ...drag, x1: p.x, y1: p.y }); } }}
            onMouseUp={finish}
            onMouseLeave={finish}
          >
            {boxes.map((b, i) => (
              <g key={i} opacity={hover === null || hover === i ? 1 : 0.35}>
                <rect x={b.x} y={b.y} width={b.w} height={b.h} fill={color(b.label)} fillOpacity={0.12} stroke={color(b.label)} strokeWidth={2.5} />
                <text x={b.x + 3} y={b.y - 4} fill={color(b.label)} fontSize={14} fontWeight={700}>{i + 1} {b.label}</text>
              </g>
            ))}
            {drag && (
              <rect
                x={Math.min(drag.x0, drag.x1)} y={Math.min(drag.y0, drag.y1)}
                width={Math.abs(drag.x1 - drag.x0)} height={Math.abs(drag.y1 - drag.y0)}
                fill="none" stroke={color(cls)} strokeDasharray="6 4" strokeWidth={2}
              />
            )}
          </svg>
        )}
      </div>
      <table className="mini">
        <tbody>
          {boxes.length === 0 && <tr><td className="muted">No boxes yet{readOnly ? "" : " — drag on the image to draw one"}.</td></tr>}
          {boxes.map((b, i) => (
            <tr key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <td><span className="swatch" style={{ background: color(b.label) }} /> #{i + 1}</td>
              <td>
                {readOnly ? b.label : (
                  <select value={b.label} onChange={(e) => update(i, { label: e.target.value })}>
                    {classes.map((c) => <option key={c}>{c}</option>)}
                  </select>
                )}
              </td>
              <td className="muted mono">{b.x},{b.y} · {b.w}×{b.h}px</td>
              <td>{!readOnly && <button className="link danger" onClick={() => remove(i)}>delete</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
