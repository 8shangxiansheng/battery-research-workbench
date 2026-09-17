/**
 * BRW-025R-WF §7/§11 — Draft guard.
 *
 * Blocks navigation when there are unsaved draft changes.
 * Shows Save / Discard / Stay dialog. No silent loss, no auto-commit.
 *
 * Uses react-router v7's useBlocker hook.
 */
import { useState, useCallback } from "react";
import { useBlocker } from "react-router-dom";

export interface DraftGuardState {
  /** Whether there are unsaved changes. */
  isDirty: boolean;
  /** Set the dirty flag. Call with true when draft differs from committed. */
  setDirty: (dirty: boolean) => void;
  /** Whether the blocker is currently active (navigation was attempted while dirty). */
  blocked: boolean;
  /** Save handler — should persist draft, then call proceed(). */
  save: () => void;
  /** Discard handler — should reset draft to committed, then call proceed(). */
  discard: () => void;
  /** Stay handler — cancel navigation, remain on page. */
  stay: () => void;
}

/**
 * Draft guard hook. Call setDirty(true) when draft state diverges from committed.
 * The blocker activates automatically when isDirty is true and navigation is attempted.
 *
 * @param onSave Called when user chooses Save. Should persist draft before returning.
 * @param onDiscard Called when user chooses Discard. Should reset draft before returning.
 */
export function useDraftGuard(
  onSave?: () => void | Promise<void>,
  onDiscard?: () => void,
): DraftGuardState {
  const [isDirty, setDirty] = useState(false);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && currentLocation.pathname !== nextLocation.pathname,
  );

  const save = useCallback(async () => {
    if (onSave) await onSave();
    setDirty(false);
    blocker.proceed?.();
  }, [onSave, blocker]);

  const discard = useCallback(() => {
    if (onDiscard) onDiscard();
    setDirty(false);
    blocker.proceed?.();
  }, [onDiscard, blocker]);

  const stay = useCallback(() => {
    blocker.reset?.();
  }, [blocker]);

  return {
    isDirty,
    setDirty,
    blocked: blocker.state === "blocked",
    save,
    discard,
    stay,
  };
}
