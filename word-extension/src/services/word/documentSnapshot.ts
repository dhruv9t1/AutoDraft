import { runWordOperation, wordOperationQueue } from "./operationQueue";
import { getWordCapabilities } from "./capabilityService";

function bytesToBase64(bytes: Uint8Array): string {
  const chunk = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      Array.prototype.slice.call(bytes.subarray(i, i + chunk))
    );
  }
  return btoa(binary);
}

function sliceBytes(data: unknown): Uint8Array {
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (Array.isArray(data)) return new Uint8Array(data as number[]);
  throw new Error("Word returned an unsupported DOCX slice format.");
}

/** Capture the complete .docx OPC package where the Word host supports it. */
export async function captureCompressedDocument(): Promise<string | null> {
  if (!getWordCapabilities().compressedDocumentCapture) return null;
  return wordOperationQueue.run(
    () =>
      new Promise<string>((resolve, reject) => {
        const doc = Office.context.document as any;
        doc.getFileAsync(Office.FileType.Compressed, { sliceSize: 1024 * 1024 }, (result: any) => {
          if (result.status !== Office.AsyncResultStatus.Succeeded) {
            reject(
              new Error(result.error?.message || "Could not capture the complete Word document.")
            );
            return;
          }
          const file = result.value;
          const chunks: Uint8Array[] = [];
          let total = 0;
          const read = (index: number) => {
            if (index >= file.sliceCount) {
              const all = new Uint8Array(total);
              let at = 0;
              for (const part of chunks) {
                all.set(part, at);
                at += part.length;
              }
              file.closeAsync(() => resolve(bytesToBase64(all)));
              return;
            }
            file.getSliceAsync(index, (sliceResult: any) => {
              if (sliceResult.status !== Office.AsyncResultStatus.Succeeded) {
                file.closeAsync(() =>
                  reject(
                    new Error(sliceResult.error?.message || `Could not read DOCX slice ${index}.`)
                  )
                );
                return;
              }
              try {
                const bytes = sliceBytes(sliceResult.value.data);
                chunks.push(bytes);
                total += bytes.length;
                read(index + 1);
              } catch (error) {
                file.closeAsync(() => reject(error));
              }
            });
          };
          read(0);
        });
      })
  );
}

/** Open a stored full DOCX in a new Word document. */
export async function openDocumentFromBase64(base64: string): Promise<void> {
  if (!base64?.trim()) throw new Error("Stored document content is empty.");
  await runWordOperation(async (context) => {
    const application = context.application as any;
    const created = application.createDocument(base64);
    await context.sync();
    created.open();
    await context.sync();
  });
}
