// Split on whitespace; "double" or 'single' quoted segments stay together (quotes dropped); an unclosed quote takes the rest.
export function splitArgs(input: string): string[] {
  const out: string[] = [];
  for (const m of input.matchAll(/(?:"([^"]*)(?:"|$)|'([^']*)(?:'|$)|[^\s"']+)+/g)) {
    out.push(m[0].replace(/"([^"]*)(?:"|$)|'([^']*)(?:'|$)/g, (_, d, s) => d ?? s));
  }
  return out;
}
