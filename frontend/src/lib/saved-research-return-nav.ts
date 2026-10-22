/** Safe back-link from saved research detail (VAL-05 return to validation period). */

export function savedResearchBackLink(returnTo: string | null): {
  href: string;
  label: string;
} {
  if (returnTo && returnTo.startsWith("/validation")) {
    return { href: returnTo, label: "Итоги исследований" };
  }
  return { href: "/saved", label: "Сохранённое" };
}
