import React, { useEffect, useRef, useState } from "react";
import { usePusula } from "../PusulaProvider.jsx";
import DesignIcon from "../DesignIcon.jsx";
import { config } from "../../../config.js";

// The accepted types and size caps mirror the backend's own limits, so the
// client rejects early with a Turkish message instead of eating a 413. Both
// come from src/config.js; the server stays the authority.
const looksLikeVideo = (file) =>
  /^video\//.test(file.type || "") || /\.(mp4|mov|webm)$/i.test(file.name || "");

export default function MediaUpload() {
  const ui = usePusula();
  const input = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => () => previewUrl && URL.revokeObjectURL(previewUrl), [previewUrl]);

  const media = ui.media;
  const uploading = ui.mediaTask?.status === "loading";
  // A missing vision stack answers 503; the text path still works, so this must
  // read as a soft note rather than a blocker (see app.py lifespan warning).
  const uploadError = ui.mediaTask?.error?.message || "";

  const isImageMode = ui.format === "image";
  const isVideoMode = ui.format === "video";

  useEffect(() => {
    if (media) {
      if (ui.format === "thread") {
        reset();
      } else if (isImageMode && media.mediaKind === "video") {
        reset();
      } else if (isVideoMode && media.mediaKind === "photo") {
        reset();
      }
    }
  }, [ui.format]);

  function accept(file) {
    if (!file) return;
    const isVideo = looksLikeVideo(file);
    if (isImageMode && isVideo) {
      setLocalError("Görsel formatı seçildiğinde yalnızca fotoğraf (JPEG, PNG, WebP) yükleyebilirsiniz.");
      return;
    }
    if (isVideoMode && !isVideo) {
      setLocalError("Video formatı seçildiğinde yalnızca video (MP4, MOV, WebM) yükleyebilirsiniz.");
      return;
    }
    const limit = isVideo ? config.maxVideoMb : config.maxImageMb;
    if (file.size > limit * 1024 * 1024) {
      setLocalError(
        `Dosya çok büyük. En fazla ${limit} MB yükleyebilirsiniz.`,
      );
      return;
    }
    setLocalError("");
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(isVideo ? "" : URL.createObjectURL(file));
    ui.uploadMedia(file);
  }

  function reset() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl("");
    setLocalError("");
    ui.clearMedia();
  }

  if (ui.format === "thread") {
    return (
      <section className="p-space-lg rounded-xl bg-surface-container-low shadow-xl transition-all">
        <header className="flex justify-between pb-space-xs">
          <strong className="text-title-sm flex items-center gap-1.5">
            <DesignIcon name="notes" className="text-primary" /> 2. Medya Analizi
          </strong>
          <span className="text-code-sm text-secondary font-mono bg-secondary-container/10 px-2 py-0.5 rounded">
            Salt Metin
          </span>
        </header>
        <div className="p-space-md rounded-lg bg-surface-container-lowest/60 border border-outline-variant/20 flex items-center gap-space-sm mt-space-xs">
          <DesignIcon name="info" className="text-secondary text-[20px] shrink-0" />
          <p className="text-body-sm text-on-surface-variant leading-relaxed">
            <strong>Thread formatı</strong> yalnızca metin dizisi olarak işlenir. Bu formatta görsel veya video yüklemesi devre dışıdır.
          </p>
        </div>
      </section>
    );
  }

  if (media) {
    return (
      <section className="p-space-lg rounded-xl bg-surface-container-low shadow-xl">
        <header className="flex justify-between pb-space-md">
          <strong className="text-title-sm flex items-center gap-1.5">
            <DesignIcon
              name={media.mediaKind === "video" ? "videocam" : "image"}
              className="text-primary"
            />{" "}
            2. {media.mediaKind === "video" ? "Video" : "Görsel"} Analizi
          </strong>
          <button
            className="text-label-sm text-on-surface-variant hover:text-error transition-colors"
            onClick={reset}
          >
            Kaldır
          </button>
        </header>
        <div className="flex gap-space-md items-start">
          {previewUrl ? (
            <img
              src={previewUrl}
              alt=""
              className="w-20 h-20 rounded-lg object-cover shrink-0"
            />
          ) : (
            <span className="w-20 h-20 rounded-lg bg-surface-container-highest flex items-center justify-center shrink-0">
              <DesignIcon name="movie" className="text-on-surface-variant text-[28px]" />
            </span>
          )}
          <div className="flex flex-col gap-1 min-w-0">
            <span className="text-body-sm truncate font-medium">{media.filename}</span>
            <span className="text-code-sm text-on-surface-variant">
              {media.mediaKind === "video"
                ? `${media.framesAnalyzed} kare analiz edildi`
                : "Fotoğraf analiz edildi"}
            </span>
            {media.uncertain ? (
              <span className="text-code-sm text-on-surface-variant">
                Görselden kategori çıkarılamadı; öneri metne göre yapılacak.
              </span>
            ) : (
              <>
                <span className="text-code-sm text-tertiary">
                  Algılanan kategori: <strong>{media.canonicalCategory}</strong>{" "}
                  ({media.categoryConfidence.toFixed(2)})
                </span>
                {media.suggestedTags.length > 0 && (
                  <span className="text-code-sm text-primary">
                    {media.suggestedTags.map((tag) => `#${tag.replace(/^#/, "")}`).join(" ")}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      </section>
    );
  }

  const acceptedMime = isVideoMode
    ? "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm"
    : isImageMode
      ? "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
      : config.acceptedUploadTypes;

  const dropTitle = uploading
    ? isVideoMode
      ? "Video analiz ediliyor…"
      : "Görsel analiz ediliyor…"
    : isVideoMode
      ? "Video sürükleyin veya seçin"
      : isImageMode
        ? "Fotoğraf sürükleyin veya seçin"
        : "Fotoğraf veya video sürükleyin, ya da seçin";

  const dropSubtitle = isVideoMode
    ? `Video mp4/mov/webm ≤ ${config.maxVideoMb} MB (maks 60 sn)`
    : isImageMode
      ? `Görsel jpeg/png/webp ≤ ${config.maxImageMb} MB`
      : `Görsel jpeg/png/webp ≤ ${config.maxImageMb} MB · Video mp4/mov/webm ≤ ${config.maxVideoMb} MB`;

  return (
    <section className="p-space-lg rounded-xl bg-surface-container-low shadow-xl">
      <header className="flex justify-between pb-space-md">
        <strong className="text-title-sm flex items-center gap-1.5">
          <DesignIcon
            name={isVideoMode ? "videocam" : "image"}
            className="text-primary"
          />{" "}
          2. {isVideoMode ? "Video" : "Görsel"} Analizi
        </strong>
        <small className="text-on-surface-variant font-medium">İSTEĞE BAĞLI</small>
      </header>
      <div
        className={`pusula-dropzone${dragging ? " is-dragging" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          accept(event.dataTransfer?.files?.[0]);
        }}
      >
        <DesignIcon
          name={isVideoMode ? "video_library" : "upload"}
          className="text-primary text-[26px]"
        />
        <span className="text-body-sm font-semibold">{dropTitle}</span>
        <span className="text-code-sm text-on-surface-variant">{dropSubtitle}</span>
      </div>
      <input
        ref={input}
        type="file"
        accept={acceptedMime}
        className="hidden"
        onChange={(event) => {
          accept(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      {(localError || uploadError) && (
        <p className="text-code-sm text-error pt-space-sm font-medium">
          {localError || uploadError}
        </p>
      )}
      <p className="text-code-sm text-on-surface-variant pt-space-sm">
        {isVideoMode
          ? "Yüklediğiniz video karesel örnekleme ile taranır ve paylaşım penceresi optimize edilir."
          : "Yüklediğiniz görsel içeriğinizin türünü belirler ve paylaşım saati önerisini ona göre hesaplar."}
      </p>
    </section>
  );
}
