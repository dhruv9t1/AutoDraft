# Word add-in hardening: issues 47-54

This pass closes the Word host capability/event/reconciliation gaps identified after v1.3 hardening.

- Capability detection uses the independent `CustomXmlParts` Common API requirement set and `CompressedFile` for compressed `getFileAsync`, plus WordApi 1.5 for content-control-added events.
- Binding event monitoring is document-scoped using the embedded AutoDraft `documentId`; it subscribes only to manifest-owned binding IDs or the deliberately supported `autodraft:<uuid>` legacy namespace. Arbitrary tagged/UUID controls are ignored.
- `document.onContentControlAdded` dynamically attaches handlers, and binding commits explicitly refresh registrations after manifest evidence is persisted.
- Reconciliation verifies both start and end paragraph/control membership for cross-paragraph bindings and exact terminal offsets/text fragments. Host API gaps are reported as `degraded`/`unverified`, never silently healthy.
- Manifest schema v3 records both normalized expected text and an exact raw-text SHA-256. Reconciliation checks both so case/spacing/punctuation drift cannot hide behind normalization.

Real Word Windows/Mac host execution remains a release gate; static/unit checks cannot replace Office host evidence.
