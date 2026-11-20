/**
 * Light-weight PDF loading skeleton.
 *
 * Lives outside ``PdfDocumentPreview`` on purpose: the real viewer imports
 * pdf.js + react-pdf (≈800 KB), and the chat/KB preview entry points only need
 * the skeleton until the user actually opens a PDF. Keeping the two apart lets
 * the heavy viewer load on demand without pulling it into the first screen.
 */

import styles from "./PdfDocumentPreview.module.less";

/** Thin top progress bar: real percent while downloading, sliding
 *  (indeterminate) while pdf.js parses. */
export function PdfLoadingBar({ percent }: { percent?: number | null }) {
  const clamped =
    percent != null && Number.isFinite(percent)
      ? Math.max(2, Math.min(100, Math.round(percent)))
      : null;
  return (
    <div className={styles.pdfLoadingBar} aria-hidden>
      <div
        className={
          clamped != null
            ? styles.pdfLoadingBarFill
            : styles.pdfLoadingBarIndeterminate
        }
        style={clamped != null ? { width: clamped + "%" } : undefined}
      />
    </div>
  );
}

/** Clean paper placeholder (no fake text lines) shared by skeletons. */
function SkelPage() {
  return <div className={styles.skelPage} aria-hidden />;
}

/** Full viewer skeleton + real download percent, shown while the blob loads. */
export default function PdfViewerSkeleton({
  percent,
}: {
  percent?: number | null;
}) {
  return (
    <div className={styles.pdfPreview} aria-busy="true">
      <div className={styles.pdfToolbar}>
        <PdfLoadingBar percent={percent} />
      </div>
      <div className={styles.pdfScroll}>
        <SkelPage />
        <SkelPage />
      </div>
    </div>
  );
}
