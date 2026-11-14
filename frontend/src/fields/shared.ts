// Helpers shared by the list-editing widgets (boxes, segments).

export const PALETTE = ["#e4572e", "#2e86de", "#17a673", "#f2a541", "#8e44ad", "#d63384", "#20c997"];

/** A stable color per option (class, speaker), by its position in the definition's list. */
export const colorFor = (options: string[]) => (option: string) => PALETTE[options.indexOf(option) % PALETTE.length];

/** Edit/delete one entry of a list value and hand the new list to onChange. */
export function listEditor<T>(list: T[], onChange: (v: T[]) => void) {
  return {
    update: (i: number, patch: Partial<T>) => onChange(list.map((x, j) => (j === i ? { ...x, ...patch } : x))),
    remove: (i: number) => onChange(list.filter((_, j) => j !== i)),
  };
}
