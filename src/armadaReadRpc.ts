// Read-only RPC watchdog for the Armada frontend.
//
// Scope: this only guards a small allowlist of *read* methods so the UI does
// not hang forever when the backend is absent or stuck. It never wraps writes,
// never retries, and cannot cancel anything server-side: when the budget
// expires the frontend simply stops waiting, and any backend job that is still
// running keeps running. Late results are ignored and late errors are
// swallowed so they never surface as unhandled rejections.

export type ArmadaRpc = <T>(method: string, ...args: unknown[]) => Promise<T>;

export const ARMADA_READ_METHODS: readonly string[] = Object.freeze([
  "library",
  "armada_source_status",
  "armada_status",
  "armada_model_status",
  "helix2_library",
  "helix2_status",
]);

export const DEFAULT_ARMADA_READ_TIMEOUT_MS = 30000;
export const MAX_ARMADA_READ_TIMEOUT_MS = 120000;

export const ARMADA_READ_TIMEOUT_MESSAGE =
  "HelixSR did not respond. Refresh games and status; if it repeats, reopen the plugin after Decky restarts.";

const READ_METHODS: ReadonlySet<string> = new Set(ARMADA_READ_METHODS);

export function createArmadaReadRpc(
  rpc: ArmadaRpc,
  timeoutMs: number = DEFAULT_ARMADA_READ_TIMEOUT_MS,
): ArmadaRpc {
  if (typeof rpc !== "function") {
    throw new TypeError("Armada read RPC requires an rpc function.");
  }
  if (
    typeof timeoutMs !== "number" ||
    !Number.isInteger(timeoutMs) ||
    timeoutMs <= 0 ||
    timeoutMs > MAX_ARMADA_READ_TIMEOUT_MS
  ) {
    throw new RangeError(
      `Armada read RPC timeout must be an integer between 1 and ${MAX_ARMADA_READ_TIMEOUT_MS} ms.`,
    );
  }

  return function armadaReadRpc<T>(method: string, ...args: unknown[]): Promise<T> {
    if (typeof method !== "string" || !READ_METHODS.has(method)) {
      // Rejected before dispatch: nothing reaches the backend.
      return Promise.reject(new Error("Armada read RPC only allows read methods."));
    }

    return new Promise<T>((resolve, reject) => {
      let settled = false;
      const timer: ReturnType<typeof setTimeout> = setTimeout(() => {
        if (settled) return;
        settled = true;
        // Stop waiting only; the backend call is not cancelled.
        reject(new Error(ARMADA_READ_TIMEOUT_MESSAGE));
      }, timeoutMs);

      let pending: Promise<T>;
      try {
        pending = rpc<T>(method, ...args);
      } catch (error) {
        settled = true;
        clearTimeout(timer);
        reject(error);
        return;
      }

      // Both handlers are always attached, so a late rejection is handled.
      Promise.resolve(pending).then(
        (value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(value);
        },
        (error: unknown) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          reject(error);
        },
      );
    });
  };
}
