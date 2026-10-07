import { readAutoDraftManifest } from "../documentManifest";
import { getWordCapabilities } from "./capabilityService";
import { runWordOperation, runWordOperationWithContext } from "./operationQueue";

export type BindingEvent = { type: "changed" | "deleted"; bindingId: string; text?: string };

interface ControlRegistration {
  controlId: number;
  bindingId: string;
  control: Word.ContentControl;
  changed: OfficeExtension.EventHandlerResult<any>;
  deleted: OfficeExtension.EventHandlerResult<any>;
}

interface MonitorState {
  documentId: string;
  allowedBindingIds: Set<string>;
  onEvent: (event: BindingEvent) => void;
  registrations: Map<number, ControlRegistration>;
  documentAdded?: OfficeExtension.EventHandlerResult<any>;
  disposed: boolean;
}

let activeMonitor: MonitorState | null = null;

function normalizedTag(tag: string): string {
  return (tag || "").trim().toLowerCase();
}

/** Deliberately supported pre-manifest AutoDraft tag form. Arbitrary UUID tags are NOT trusted. */
export function isLegacyAutoDraftBindingTag(tag: string): boolean {
  return /^autodraft:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    (tag || "").trim()
  );
}

function isAllowedTag(state: MonitorState, tag: string): boolean {
  const value = normalizedTag(tag);
  return !!value && (state.allowedBindingIds.has(value) || isLegacyAutoDraftBindingTag(value));
}

async function refreshManifestScope(state: MonitorState): Promise<boolean> {
  const manifest = await readAutoDraftManifest();
  if (!manifest || manifest.documentId !== state.documentId) return false;
  state.allowedBindingIds = new Set(
    manifest.bindings.map((binding) => normalizedTag(binding.bindingId)).filter(Boolean)
  );
  return true;
}

async function attachControl(
  context: Word.RequestContext,
  state: MonitorState,
  control: Word.ContentControl
): Promise<void> {
  if (state.disposed) return;
  control.load("id,tag,text");
  await context.sync();
  const controlId = Number((control as any).id);
  const bindingId = (control.tag || "").trim();
  if (
    !Number.isFinite(controlId) ||
    state.registrations.has(controlId) ||
    !isAllowedTag(state, bindingId)
  )
    return;

  control.track();
  const changed = control.onDataChanged.add(
    async (event: Word.ContentControlDataChangedEventArgs) => {
      if (state.disposed) return;
      try {
        if (!(await refreshManifestScope(state)) || !isAllowedTag(state, bindingId)) return;
        const changedId = event.ids?.[0] ?? controlId;
        // The callback parameter must be named `context` for the office-addins
        // lint rules to recognize `context.sync()` as a sync boundary.
        await runWordOperation(async (context) => {
          const found = context.document.contentControls.getByIdOrNullObject(changedId);
          found.load("isNullObject,tag,text");
          await context.sync();
          if (!found.isNullObject && normalizedTag(found.tag || "") === normalizedTag(bindingId)) {
            state.onEvent({ type: "changed", bindingId, text: found.text });
          }
        });
      } catch {
        // Reconciliation is authoritative if event delivery fails.
      }
    }
  );
  const deleted = control.onDeleted.add(async () => {
    if (state.disposed) return;
    try {
      if ((await refreshManifestScope(state)) && isAllowedTag(state, bindingId)) {
        state.onEvent({ type: "deleted", bindingId });
      }
    } catch {
      // Reconciliation on next startup remains authoritative.
    }
  });
  await context.sync();
  state.registrations.set(controlId, { controlId, bindingId, control, changed, deleted });
}

async function attachEligibleControls(state: MonitorState, ids?: number[]): Promise<void> {
  if (state.disposed) return;
  const current = await refreshManifestScope(state);
  if (!current) {
    await disposeState(state);
    return;
  }
  await runWordOperation(async (context) => {
    if (ids?.length) {
      for (const id of ids) {
        const control = context.document.contentControls.getByIdOrNullObject(id);
        control.load("isNullObject,id,tag,text");
        await context.sync();
        if (!control.isNullObject) await attachControl(context, state, control);
      }
      return;
    }
    const controls = context.document.contentControls;
    controls.load("items");
    await context.sync();

    for (const control of controls.items) control.load("id,tag,text");
    await context.sync();
    for (const control of controls.items) await attachControl(context, state, control);
  });
}

async function disposeState(state: MonitorState): Promise<void> {
  if (state.disposed) return;
  state.disposed = true;
  if (activeMonitor === state) activeMonitor = null;

  const byContext = new Map<
    Word.RequestContext,
    { results: OfficeExtension.EventHandlerResult<any>[]; controls: Word.ContentControl[] }
  >();

  const add = (
    result: OfficeExtension.EventHandlerResult<any> | undefined,
    control?: Word.ContentControl
  ) => {
    if (!result) return;
    const context = result.context as Word.RequestContext;
    const group = byContext.get(context) || { results: [], controls: [] };
    group.results.push(result);
    if (control && !group.controls.includes(control)) group.controls.push(control);
    byContext.set(context, group);
  };

  add(state.documentAdded);
  for (const registration of state.registrations.values()) {
    add(registration.changed, registration.control);
    add(registration.deleted);
  }

  for (const [context, group] of byContext) {
    try {
      await runWordOperationWithContext(context, async (ctx) => {
        for (const result of group.results) {
          try {
            result.remove();
          } catch {
            // Handler may already be removed.
          }
        }
        for (const control of group.controls) {
          try {
            control.untrack();
          } catch {
            // Control may already be untracked.
          }
        }
        await ctx.sync();
      });
    } catch {
      // Host shutdown/document close can invalidate the original context.
    }
  }
  state.registrations.clear();
}

/** Re-scan manifest-owned controls after a successful binding commit. */
export async function refreshBindingEventMonitoring(): Promise<void> {
  if (!activeMonitor || activeMonitor.disposed) return;
  await attachEligibleControls(activeMonitor);
}

/** Register document-scoped live handlers only for AutoDraft-owned controls. */
export async function startBindingEventMonitoring(
  onEvent: (event: BindingEvent) => void
): Promise<() => void> {
  const capabilities = getWordCapabilities();
  if (!capabilities.contentControlEvents) return () => {};
  const manifest = await readAutoDraftManifest();
  if (!manifest) return () => {};

  if (activeMonitor) {
    if (activeMonitor.documentId === manifest.documentId && !activeMonitor.disposed) {
      activeMonitor.onEvent = onEvent;
      await refreshBindingEventMonitoring();
      const state = activeMonitor;
      return () => {
        void disposeState(state);
      };
    }
    await disposeState(activeMonitor);
  }

  const state: MonitorState = {
    documentId: manifest.documentId,
    allowedBindingIds: new Set(
      manifest.bindings.map((binding) => normalizedTag(binding.bindingId)).filter(Boolean)
    ),
    onEvent,
    registrations: new Map(),
    disposed: false,
  };
  activeMonitor = state;

  try {
    await attachEligibleControls(state);
    if (capabilities.wordApi15 && !state.disposed) {
      await runWordOperation(async (context) => {
        state.documentAdded = context.document.onContentControlAdded.add(
          async (event: Word.ContentControlAddedEventArgs) => {
            if (state.disposed) return;
            try {
              await attachEligibleControls(
                state,
                (event.ids || []).map(Number).filter(Number.isFinite)
              );
            } catch {
              // BindingService also performs an explicit refresh after manifest commit.
            }
          }
        );
        await context.sync();
      });
    }
  } catch (error) {
    await disposeState(state);
    throw error;
  }

  return () => {
    void disposeState(state);
  };
}
