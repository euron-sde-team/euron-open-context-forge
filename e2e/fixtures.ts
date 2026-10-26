/** A small support conversation with facts stated early and buried under small talk. */
export function supportThread(turns = 20): { role: string; content: string }[] {
  const filler = "I checked the dashboard again and the page looks the same as before, nothing new to report. ";
  const msgs = [
    { role: "system", content: "You are Acme support. Be concise." },
    { role: "user", content: "Hi, our account is ACC-77120 and we need to upgrade 42 seats before 2026-11-01." },
    { role: "assistant", content: "Business costs $49 per seat. We must not change the billing contact without verification." },
  ];
  for (let i = 0; i < turns; i++) {
    msgs.push({ role: "user", content: filler.repeat(3) + (i === 3 ? "Is SSO included?" : "") });
    msgs.push({ role: "assistant", content: `Thanks for the update. ${filler.repeat(2)}` });
  }
  msgs.push({ role: "user", content: "What happens to our API keys during the upgrade?" });
  return msgs;
}
