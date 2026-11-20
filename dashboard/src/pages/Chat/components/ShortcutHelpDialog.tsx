import ShortcutSheet from "../../../layouts/ShortcutSheet";

interface ShortcutHelpDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Chat-page alias for the shell cheatsheet.
 *
 * Both entry points — Ctrl/Cmd + / inside a conversation and `?` anywhere —
 * must show the same list, so this re-exports the shell sheet instead of
 * keeping a second copy of the rows.
 */
export default function ShortcutHelpDialog({
  open,
  onClose,
}: ShortcutHelpDialogProps) {
  return <ShortcutSheet open={open} onClose={onClose} includeComposer />;
}
