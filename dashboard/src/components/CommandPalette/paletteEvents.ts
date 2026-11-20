/**
 * Shell command palette events.
 *
 * The palette lives in `MainLayout`, but the affordance that opens it is inside
 * `Sidebar`. A DOM event keeps the two decoupled — neither has to pass a
 * callback through the layout tree.
 */

export const SHELL_PALETTE_EVENT = "octop:open-command-palette";
