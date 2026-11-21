/** Shape every HappyClaw error response carries: `{ error: { code, message, details } }`. */
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  static fromResponse(status: number, body: unknown): ApiError {
    if (isEnvelope(body)) {
      return new ApiError(
        status,
        body.error.code,
        body.error.message,
        body.error.details,
      );
    }
    return new ApiError(
      status,
      `HTTP_${status}`,
      typeof body === "string" && body.trim()
        ? body
        : `Request failed with status ${status}`,
    );
  }
}

function isEnvelope(body: unknown): body is ApiErrorEnvelope {
  return (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as ApiErrorEnvelope).error === "object" &&
    (body as ApiErrorEnvelope).error !== null &&
    typeof (body as ApiErrorEnvelope).error.message === "string"
  );
}

/** True when a failure means "the backend is not there", not "the request was bad". */
export function isTransportFailure(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 0 || error.status >= 500;
  return error instanceof TypeError;
}
