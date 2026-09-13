import React from "react";
export default function RequestState({
  task,
  retry,
  empty = "Henüz bir sonuç yok.",
  children,
}) {
  if (task.status === "loading")
    return (
      <div className="request-state" role="status" aria-live="polite">
        <span className="request-spinner" />
        Sonuç hazırlanıyor…
      </div>
    );
  if (task.status === "error")
    return (
      <div className="request-state request-error" role="alert">
        <p>{task.error.message}</p>
        {retry && (
          <button className="pusula-primary" onClick={retry}>
            Tekrar Dene
          </button>
        )}
      </div>
    );
  if (!task.data) return <div className="request-state">{empty}</div>;
  return children;
}
