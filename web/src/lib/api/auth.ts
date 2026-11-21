/**
 * Compatibility auth for the two non-local deployments HappyClaw still ships:
 * a desktop shell and a phone-hosted dashboard. The single-user local build
 * needs none of this, so every lookup degrades to "no header".
 */

const AUTH_TOKEN_KEY = "auth_token";
/**
 * The server slides the JWT forward with this response header. The literal name
 * is the server's wire contract, so it keeps its historical spelling until the
 * backend renames it — changing only this side would silently stop renewal.
 */
export const ACCESS_TOKEN_RESPONSE_HEADER = "X-Octop-Access-Token";

export function getAuthToken(): string | null {
  try {
    return (
      window.sessionStorage.getItem(AUTH_TOKEN_KEY) ??
      window.localStorage.getItem(AUTH_TOKEN_KEY)
    );
  } catch {
    return null;
  }
}

export function setAuthToken(token: string, remember = true): void {
  try {
    if (remember) window.localStorage.setItem(AUTH_TOKEN_KEY, token);
    else window.sessionStorage.setItem(AUTH_TOKEN_KEY, token);
  } catch {
    /* storage unavailable: the token stays in memory for this module only */
  }
}

export function applyAuthHeader(request: Request): void {
  const token = getAuthToken();
  if (token) request.headers.set("Authorization", `Bearer ${token}`);
}

export function persistRenewedToken(response: Response): void {
  const renewed = response.headers.get(ACCESS_TOKEN_RESPONSE_HEADER);
  if (!renewed) return;
  const remembered = window.localStorage.getItem(AUTH_TOKEN_KEY) !== null;
  setAuthToken(renewed, remembered);
}
