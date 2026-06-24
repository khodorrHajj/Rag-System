export const MAX_UPLOAD_SIZE_MB_DISPLAY = 20;
export const ALLOWED_UPLOAD_EXTENSIONS = [".pdf"] as const;
export const LEGACY_DOC_MESSAGE =
  "Legacy .doc files are not supported. Please upload a PDF file.";

export function getFileExtension(filename: string): string {
  const normalized = filename.trim().toLowerCase();
  const lastDotIndex = normalized.lastIndexOf(".");
  if (lastDotIndex < 0) {
    return "";
  }

  return normalized.slice(lastDotIndex);
}

export function validateUploadCandidate(file: File): string | null {
  const extension = getFileExtension(file.name);
  if (extension === ".doc") {
    return LEGACY_DOC_MESSAGE;
  }

  if (!ALLOWED_UPLOAD_EXTENSIONS.includes(extension as (typeof ALLOWED_UPLOAD_EXTENSIONS)[number])) {
    return "Only .pdf files are supported.";
  }

  const maxFileSizeBytes = MAX_UPLOAD_SIZE_MB_DISPLAY * 1024 * 1024;
  if (file.size > maxFileSizeBytes) {
    return `Uploaded file exceeds the maximum allowed size of ${MAX_UPLOAD_SIZE_MB_DISPLAY} MB.`;
  }

  return null;
}
