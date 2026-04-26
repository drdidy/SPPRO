export function formatPrice(value: number | null | undefined, fallback = "-") {
  if (typeof value !== "number" || Number.isNaN(value)) return fallback;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: value >= 100 ? 2 : 2,
    maximumFractionDigits: 2
  });
}

export function toneFor(value: string | undefined) {
  const normalized = (value ?? "").toLowerCase();
  if (/(enter|valid|within|low|selected|positive|ready)/.test(normalized)) return "positive";
  if (/(wait|watch|major|moderate|near|armed|medium|over)/.test(normalized)) return "warning";
  if (/(no trade|invalid|blocked|extreme|danger|weak)/.test(normalized)) return "danger";
  return "neutral";
}
