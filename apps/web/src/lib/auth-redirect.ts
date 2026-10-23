import { ApiError } from "./api/errors";

/**
 * Decide what a 401 means. Wrong credentials on the login or password form are a form
 * error, not an expired session; everything else sends the person back to sign in.
 */
export function isSessionExpired(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401 && err.code !== "invalid_credentials";
}

/** Build /login?next=... for the current location, never looping back to /login. */
export function loginUrl(pathname: string, search = "", reason?: "expired"): string {
  const params = new URLSearchParams();
  const target = `${pathname}${search}`;
  if (pathname && pathname !== "/login" && pathname !== "/") params.set("next", target);
  if (reason) params.set("reason", reason);
  const qs = params.toString();
  return qs ? `/login?${qs}` : "/login";
}

/** Only accept same-origin relative paths as a post-login destination. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/login")) return "/";
  return next;
}
