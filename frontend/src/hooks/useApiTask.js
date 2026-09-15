import { useCallback, useEffect, useRef, useState } from "react";
/** Latest request wins. Editing inputs or leaving the page aborts stale work. */
export function useApiTask() {
  const sequence = useRef(0);
  const controller = useRef(null);
  const [state, setState] = useState({
    status: "idle",
    data: null,
    error: null,
  });
  const cancel = useCallback(() => {
    sequence.current++;
    controller.current?.abort();
  }, []);
  const reset = useCallback(() => {
    cancel();
    setState({ status: "idle", data: null, error: null });
  }, [cancel]);
  useEffect(() => cancel, [cancel]);
  const run = useCallback(
    async (work) => {
      cancel();
      const current = sequence.current;
      controller.current = new AbortController();
      setState({ status: "loading", data: null, error: null });
      try {
        const data = await work(controller.current.signal);
        if (current !== sequence.current) return;
        setState({ status: "success", data, error: null });
        return data;
      } catch (error) {
        if (current !== sequence.current) return;
        if (error.name !== "AbortError")
          setState({ status: "error", data: null, error });
      }
    },
    [cancel],
  );
  return { ...state, run, reset, cancel };
}
