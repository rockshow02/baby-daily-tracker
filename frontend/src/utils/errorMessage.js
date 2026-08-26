export function toUserFacingErrorMessage(value, fallback = "Terjadi kendala. Coba lagi.") {
  const candidate = value instanceof Error ? value.message : value;

  if (typeof candidate === "string" && candidate.trim()) return candidate.trim();

  if (candidate && typeof candidate === "object") {
    for (const key of ["message", "error", "detail"]) {
      const nested = candidate[key];
      if (typeof nested === "string" && nested.trim()) return nested.trim();
    }
  }

  return fallback;
}
