export function Banner({ text, tone = "error" }: { text: string; tone?: "error" | "info" }) {
  if (!text) return null;
  return <div className={tone === "error" ? "sp-banner sp-banner-error" : "sp-banner sp-banner-info"} role="status">{text}</div>;
}
