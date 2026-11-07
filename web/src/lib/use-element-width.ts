import { useLayoutEffect, useRef, useState } from "react";

/** An element's width in px, measured before paint and kept current as the layout changes (`fixed` skips measuring). */
export function useElementWidth<T extends HTMLElement>(fixed?: number) {
  const ref = useRef<T>(null);
  const [measured, setMeasured] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (fixed !== undefined || !el) return;
    setMeasured(Math.round(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setMeasured(Math.round(entry.contentRect.width));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fixed]);
  return [ref, fixed ?? measured] as const;
}
