/**
 * Shared error-detail formatting for API responses.
 * Handles Pydantic validation detail arrays, object errors, and plain strings.
 */
export function formatApiErrorDetail(detail, fallback) {
  if (!detail) {
    return fallback ?? null;
  }

  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const formatted = detail
      .map((item) => {
        if (typeof item === 'string' && item.trim()) {
          return item;
        }

        if (item && typeof item === 'object') {
          const path = Array.isArray(item.loc)
            ? item.loc.filter((segment) => segment !== 'body').join('.')
            : '';
          const message =
            typeof item.msg === 'string'
              ? item.msg
              : typeof item.message === 'string'
                ? item.message
                : '';

          if (path && message) {
            return `${path}: ${message}`;
          }
          if (message) {
            return message;
          }
        }

        return null;
      })
      .filter(Boolean)
      .join('; ');

    if (formatted) {
      return formatted;
    }
  }

  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message.trim()) {
      return detail.message;
    }
    if (typeof detail.code === 'string' && detail.code.trim()) {
      return detail.code;
    }
  }

  return fallback ?? String(detail);
}
