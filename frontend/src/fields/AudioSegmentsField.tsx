import { useEffect, useRef, useState } from "react";
import type { WidgetProps } from ".";
import { colorFor, listEditor } from "./shared";

interface Segment { start: number; end: number; speaker: string; text?: string }

const fmt = (t: number) => t.toFixed(2);

/** Player + timeline. Mark start/end while listening; each segment gets a speaker and transcript. */
export function AudioSegmentsField({ field, value, onChange, item, readOnly }: WidgetProps) {
  const speakers: string[] = field.speakers;
  const transcribe: boolean = field.transcribe ?? true;
  const segs: Segment[] = value ?? [];
  const audio = useRef<HTMLAudioElement>(null);
  const stopAt = useRef<number | null>(null);
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState<number>(item.meta.duration ?? 0);
  const [speaker, setSpeaker] = useState(speakers[0]);
  const [pendingStart, setPendingStart] = useState<number | null>(null);
  const color = colorFor(speakers);
  const { update, remove } = listEditor(segs, onChange);

  useEffect(() => {
    const a = audio.current!;
    const tick = () => {
      setT(a.currentTime);
      if (stopAt.current !== null && a.currentTime >= stopAt.current) { a.pause(); stopAt.current = null; }
    };
    a.addEventListener("timeupdate", tick);
    return () => a.removeEventListener("timeupdate", tick);
  }, []);

  const now = () => Math.round((audio.current?.currentTime ?? 0) * 100) / 100;
  const sorted = (xs: Segment[]) => [...xs].sort((a, b) => a.start - b.start);
  const add = (start: number, end: number) =>
    onChange(sorted([...segs, { start, end, speaker, ...(transcribe ? { text: "" } : {}) }]));
  const play = (s: Segment) => {
    const a = audio.current!;
    a.currentTime = s.start;
    stopAt.current = s.end;
    a.play();
  };
  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    audio.current!.currentTime = ((e.clientX - r.left) / r.width) * duration;
  };

  return (
    <div className="audio-seg">
      <audio ref={audio} src={item.media_url!} controls preload="auto"
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)} />
      <div className="timeline" onClick={seek} title="click to seek">
        {duration > 0 && segs.map((s, i) => (
          <div key={i} className="seg" style={{
            left: `${(s.start / duration) * 100}%`, width: `${((s.end - s.start) / duration) * 100}%`, background: color(s.speaker),
          }}>{s.speaker}</div>
        ))}
        {pendingStart !== null && duration > 0 && (
          <div className="seg pending" style={{ left: `${(pendingStart / duration) * 100}%`, width: `${(Math.max(0, t - pendingStart) / duration) * 100}%` }} />
        )}
        {duration > 0 && <div className="playhead" style={{ left: `${(t / duration) * 100}%` }} />}
      </div>
      <div className="muted small">{fmt(t)}s / {fmt(duration)}s</div>

      {!readOnly && (
        <div className="toolbar">
          <span className="muted">Speaker:</span>
          {speakers.map((s) => (
            <button key={s} className={`chip ${s === speaker ? "on" : ""}`} onClick={() => setSpeaker(s)}>
              <span className="swatch" style={{ background: color(s) }} /> {s}
            </button>
          ))}
          {pendingStart === null ? (
            <button onClick={() => setPendingStart(now())}>⏺ Mark start</button>
          ) : (
            <>
              <button className="primary" onClick={() => { const end = now(); if (end > pendingStart) add(pendingStart, end); setPendingStart(null); }}>
                ⏹ Mark end ({fmt(pendingStart)}s → {fmt(t)}s)
              </button>
              <button className="link" onClick={() => setPendingStart(null)}>cancel</button>
            </>
          )}
        </div>
      )}

      <table className="mini segs">
        <thead><tr><th /><th>start</th><th>end</th><th>speaker</th>{transcribe && <th>transcript</th>}<th /></tr></thead>
        <tbody>
          {segs.length === 0 && <tr><td colSpan={6} className="muted">No segments yet.</td></tr>}
          {segs.map((s, i) => (
            <tr key={i}>
              <td><button className="icon" title="play segment" onClick={() => play(s)}>▶</button></td>
              <td>{readOnly ? fmt(s.start) : <input type="number" step={0.05} min={0} value={s.start} onChange={(e) => update(i, { start: +e.target.value })} />}</td>
              <td>{readOnly ? fmt(s.end) : <input type="number" step={0.05} min={0} value={s.end} onChange={(e) => update(i, { end: +e.target.value })} />}</td>
              <td>
                {readOnly ? <b style={{ color: color(s.speaker) }}>{s.speaker}</b> : (
                  <select value={s.speaker} onChange={(e) => update(i, { speaker: e.target.value })}>
                    {speakers.map((x) => <option key={x}>{x}</option>)}
                  </select>
                )}
              </td>
              {transcribe && (
                <td className="grow">
                  {readOnly ? s.text : <input type="text" value={s.text ?? ""} placeholder="what was said" onChange={(e) => update(i, { text: e.target.value })} />}
                </td>
              )}
              <td>{!readOnly && <button className="link danger" onClick={() => remove(i)}>×</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
