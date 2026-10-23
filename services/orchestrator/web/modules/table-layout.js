/** Fit a paginated table to its allocated space, preserving its footer. */
export function fitTableRows(viewport, onFit) {
  let frame;
  const schedule = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const table = viewport.querySelector("table");
      if (!table || !viewport.clientHeight) return;
      const rows = [...(table.tBodies[0]?.rows || [])];
      if (!rows.length) return;
      const rowHeight = Math.max(
        ...rows.map((row) => row.getBoundingClientRect().height),
      );
      if (!rowHeight) return;
      const available =
        viewport.clientHeight - table.tHead.getBoundingClientRect().height - 2;
      onFit(Math.max(1, Math.floor(available / rowHeight)));
    });
  };
  if (window.ResizeObserver) {
    new ResizeObserver(schedule).observe(viewport);
  } else {
    window.addEventListener("resize", schedule);
  }
  return schedule;
}
