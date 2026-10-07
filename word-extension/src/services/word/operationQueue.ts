/** Serialize Word mutations so React features never compete with overlapping Word.run calls. */
class WordOperationQueue {
  private tail: Promise<unknown> = Promise.resolve();

  run<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.tail.then(operation, operation);
    this.tail = next.then(
      () => undefined,
      () => undefined
    );
    return next;
  }
}

export const wordOperationQueue = new WordOperationQueue();

const WORD_API_UNAVAILABLE_MESSAGE =
  "Word API is not available. This add-in must be run within Microsoft Word.";

function assertWordApiAvailable(): void {
  if (typeof Word === "undefined" || Word === null || typeof Word.run !== "function") {
    throw new Error(WORD_API_UNAVAILABLE_MESSAGE);
  }
}

export function runWordOperation<T>(
  callback: (context: Word.RequestContext) => Promise<T>
): Promise<T> {
  return wordOperationQueue.run(async () => {
    // Surface a clear, actionable error instead of a raw ReferenceError when the
    // add-in is opened outside Word or before Office.js has finished loading.
    assertWordApiAvailable();
    return Word.run(callback);
  });
}

/** Run work against an existing RequestContext while preserving global serialization.
 * Event-handler removal must use the same context that created the handler.
 */
export function runWordOperationWithContext<T>(
  context: Word.RequestContext,
  callback: (context: Word.RequestContext) => Promise<T>
): Promise<T> {
  return wordOperationQueue.run(() => callback(context));
}
