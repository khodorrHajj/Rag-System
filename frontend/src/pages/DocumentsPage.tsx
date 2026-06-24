import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

import { deleteDocument, listDocuments, uploadDocument } from "../api";
import { DocumentsPageSkeleton } from "../components/SkeletonScreens";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { StatusCard } from "../components/StatusCard";
import { usePolling } from "../hooks/usePolling";
import { readCachedValue, writeCachedValue } from "../lib/client-cache";
import { formatFileSize, formatTimestamp } from "../lib/format";
import {
  ALLOWED_UPLOAD_EXTENSIONS,
  MAX_UPLOAD_SIZE_MB_DISPLAY,
  validateUploadCandidate,
} from "../lib/upload";
import type { DocumentSummary } from "../types/api";

export function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>(
    () => readCachedValue<DocumentSummary[]>("documents", 5 * 60 * 1000) ?? [],
  );
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [documentsLoading, setDocumentsLoading] = useState(
    documents.length === 0,
  );
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(
    null,
  );
  const visibleDocuments = documents.filter((document) =>
    ALLOWED_UPLOAD_EXTENSIONS.includes(
      `.${document.file_type.toLowerCase()}` as (typeof ALLOWED_UPLOAD_EXTENSIONS)[number],
    ),
  );
  const activeDocuments = visibleDocuments.filter(
    (document) => document.status !== "deleted",
  ).length;
  const uploadLimit = 5;
  const uploadLimitReached = activeDocuments >= uploadLimit;
  const remainingUploadSlots = Math.max(uploadLimit - activeDocuments, 0);

  function getUploadStatusMessage(filename: string, status: string) {
    switch (status) {
      case "queued":
        return `Upload accepted. ${filename} is queued for indexing.`;
      case "uploaded":
        return `Upload accepted. ${filename} was stored successfully.`;
      case "processing":
        return `Upload accepted. ${filename} is already processing.`;
      default:
        return `Upload accepted. ${filename} is currently ${status}.`;
    }
  }

  async function loadDocuments(options?: { background?: boolean }) {
    const background = options?.background ?? false;

    if (!background) {
      setDocumentsLoading(true);
    }
    setDocumentsError(null);

    try {
      const response = await listDocuments();
      setDocuments(response);
      writeCachedValue("documents", response);
    } catch (loadingError) {
      setDocumentsError(
        loadingError instanceof Error
          ? loadingError.message
          : "Could not load your documents right now.",
      );
    } finally {
      if (!background) {
        setDocumentsLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadDocuments();
  }, []);

  const pendingDocuments = visibleDocuments.filter((document) =>
    ["uploaded", "queued", "processing", "parsed", "chunked"].includes(
      document.status,
    ),
  ).length;

  usePolling(
    () => loadDocuments({ background: true }),
    pendingDocuments > 0 ? 5000 : 15000,
    { enabled: !documentsLoading },
  );

  function handleFileSelection(event: ChangeEvent<HTMLInputElement>) {
    const nextFiles = Array.from(event.target.files ?? []);
    setUploadError(null);
    setUploadMessage(null);

    if (!nextFiles.length) {
      setSelectedFiles([]);
      return;
    }

    if (nextFiles.length > remainingUploadSlots) {
      setUploadError(
        `You can add up to ${remainingUploadSlots} more file${remainingUploadSlots === 1 ? "" : "s"}.`,
      );
      setSelectedFiles([]);
      return;
    }

    for (const nextFile of nextFiles) {
      const validationMessage = validateUploadCandidate(nextFile);
      if (validationMessage) {
        setUploadError(`${nextFile.name}: ${validationMessage}`);
        setSelectedFiles([]);
        return;
      }
    }

    setSelectedFiles(nextFiles);
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUploadError(null);
    setUploadMessage(null);

    if (!selectedFiles.length) {
      setUploadError("Choose one or more .pdf files first.");
      return;
    }

    if (uploadLimitReached) {
      setUploadError("5 file limit reached. Delete a file to add another.");
      return;
    }

    if (selectedFiles.length > remainingUploadSlots) {
      setUploadError(
        `You can add up to ${remainingUploadSlots} more file${remainingUploadSlots === 1 ? "" : "s"}.`,
      );
      return;
    }

    setUploading(true);
    try {
      const successfulUploads: string[] = [];
      const failedUploads: string[] = [];

      for (const selectedFile of selectedFiles) {
        const validationMessage = validateUploadCandidate(selectedFile);
        if (validationMessage) {
          failedUploads.push(`${selectedFile.name}: ${validationMessage}`);
          continue;
        }

        try {
          const response = await uploadDocument(selectedFile);
          successfulUploads.push(
            getUploadStatusMessage(selectedFile.name, response.status),
          );
        } catch (uploadFailure) {
          failedUploads.push(
            `${selectedFile.name}: ${
              uploadFailure instanceof Error
                ? uploadFailure.message
                : "Upload failed. Please try again."
            }`,
          );
        }
      }

      if (successfulUploads.length) {
        setUploadMessage(
          successfulUploads.length === 1
            ? successfulUploads[0]
            : `${successfulUploads.length} files queued for indexing.`,
        );
      }

      if (failedUploads.length) {
        setUploadError(failedUploads.join(" "));
      }

      setSelectedFiles([]);
      setFileInputKey((currentValue) => currentValue + 1);
      await loadDocuments({ background: true });
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string, filename: string) {
    const confirmed = window.confirm(
      `Delete ${filename}? This will delete the document.`,
    );
    if (!confirmed) {
      return;
    }

    setDeletingDocumentId(documentId);
    setDocumentsError(null);
    setUploadMessage(null);

    try {
      const response = await deleteDocument(documentId);
      setUploadMessage(`Document marked ${response.status}.`);
      await loadDocuments({ background: true });
    } catch (deleteError) {
      setDocumentsError(
        deleteError instanceof Error
          ? deleteError.message
          : "Delete failed. Please try again.",
      );
    } finally {
      setDeletingDocumentId(null);
    }
  }

  const indexedDocuments = visibleDocuments.filter(
    (document) => document.status === "indexed",
  ).length;
  const failedDocuments = visibleDocuments.filter(
    (document) => document.status === "failed",
  ).length;

  if (documentsLoading) {
    return <DocumentsPageSkeleton />;
  }

  return (
    <div className="page-stack page-stack--documents">
      <PageHeader
        eyebrow="Documents"
        title="Documents"
        description="Upload PDFs, track indexing progress, and manage the files your workspace can search."
      />

      <section className="status-grid status-grid--compact">
        <StatusCard
          title="Indexed"
          tone="success"
          value={String(indexedDocuments)}
        />
        <StatusCard
          title="Failed"
          tone={failedDocuments > 0 ? "warning" : "default"}
          value={String(failedDocuments)}
        />
        <StatusCard
          title="Pending"
          tone="default"
          value={String(
            visibleDocuments.length - indexedDocuments - failedDocuments,
          )}
        />
        <StatusCard
          title="Files used"
          tone={uploadLimitReached ? "warning" : "default"}
          value={`${activeDocuments}/${uploadLimit}`}
        />
      </section>

      <section className="panel panel--documents-upload">
        <div className="panel__header">
          <div>
            <p className="panel__eyebrow">Add file</p>
            <h2>Add and index</h2>
          </div>
        </div>

        <form className="upload-form" onSubmit={handleUpload}>
          <div className="documents-upload__summary">
            <p className="panel__description">
              Add up to <strong>{uploadLimit}</strong> PDFs. Each file can be up to{" "}
              <strong>{MAX_UPLOAD_SIZE_MB_DISPLAY} MB</strong>.
            </p>
            <span className="documents-upload__pill">
              {uploadLimitReached
                ? "Library full"
                : `${remainingUploadSlots} slot${remainingUploadSlots === 1 ? "" : "s"} left`}
            </span>
          </div>

          <label className="field upload-dropzone">
            <div className="upload-dropzone__content">
              <span className="upload-dropzone__button">Choose PDF files</span>
              <strong>Drop PDFs here or browse from your device.</strong>
              <p className="upload-dropzone__hint">
                PDF only. Multiple files are queued together for indexing.
              </p>
            </div>
            <input
              key={fileInputKey}
              accept=".pdf,application/pdf"
              disabled={uploadLimitReached}
              multiple
              onChange={handleFileSelection}
              type="file"
            />
          </label>

          {selectedFiles.length ? (
            <div className="document-chip-row">
              {selectedFiles.map((selectedFile) => (
                <span
                  key={`${selectedFile.name}-${selectedFile.size}-${selectedFile.lastModified}`}
                  className="document-chip"
                >
                  {selectedFile.name} ({formatFileSize(selectedFile.size)})
                </span>
              ))}
            </div>
          ) : null}

          {uploadError ? (
            <div className="alert alert--error">{uploadError}</div>
          ) : null}
          {uploadMessage ? (
            <div className="alert alert--success">{uploadMessage}</div>
          ) : null}

          <div className="button-row upload-form__actions">
            <p className="inline-detail inline-detail--muted">
              {selectedFiles.length
                ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} ready`
                : `Allowed types: ${ALLOWED_UPLOAD_EXTENSIONS.join(", ")}`}
            </p>
            <button
              className="button button--primary button--upload-submit"
              disabled={uploading || uploadLimitReached}
              type="submit"
            >
              {uploading
                ? "Queueing..."
                : selectedFiles.length > 1
                  ? "Add and index files"
                  : "Add and index"}
            </button>
          </div>
        </form>
      </section>

      <section className="panel panel--documents-library">
        <div className="panel__header">
          <div>
            <p className="panel__eyebrow">Library</p>
            <h2>Manage documents</h2>
          </div>
          <span className="documents-library__meta">
            {visibleDocuments.length} file{visibleDocuments.length === 1 ? "" : "s"}
          </span>
        </div>

        {documentsError ? (
          <div className="alert alert--error">{documentsError}</div>
        ) : null}

        {visibleDocuments.length ? (
          <div className="document-list">
            {visibleDocuments.map((document) => (
              <article key={document.document_id} className="document-card">
                <div className="document-card__topline">
                  <div>
                    <p className="document-card__title">
                      {document.original_filename}
                    </p>
                    <p className="document-card__meta">
                      {document.file_type.toUpperCase()} |{" "}
                      {formatFileSize(document.file_size_bytes)}
                    </p>
                  </div>
                  <StatusBadge status={document.status} />
                </div>

                <dl className="document-card__details">
                  <div>
                    <dt>Created</dt>
                    <dd>{formatTimestamp(document.created_at)}</dd>
                  </div>
                  <div>
                    <dt>Updated</dt>
                    <dd>{formatTimestamp(document.updated_at)}</dd>
                  </div>
                  <div>
                    <dt>Pipeline note</dt>
                    <dd>
                      {document.status === "failed"
                        ? "Failed"
                        : document.status === "indexed"
                          ? "Ready"
                          : "In progress"}
                    </dd>
                  </div>
                </dl>

                <div className="button-row">
                  <button
                    className="button button--danger"
                    disabled={deletingDocumentId === document.document_id}
                    onClick={() =>
                      void handleDelete(
                        document.document_id,
                        document.original_filename,
                      )
                    }
                    type="button"
                  >
                    {deletingDocumentId === document.document_id
                      ? "Deleting..."
                      : "Delete"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No documents"
            description="Add a file to start indexing."
          />
        )}
      </section>
    </div>
  );
}
