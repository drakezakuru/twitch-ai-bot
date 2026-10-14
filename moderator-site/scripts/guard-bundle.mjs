// MOD-02 gate: the built bundle must contain no owner-panel artifacts or secrets.
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const assetsDir = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "assets");
const files = readdirSync(assetsDir).filter((name) => name.endsWith(".js"));
if (files.length === 0) {
  console.error("no bundle found — run `pnpm build` first");
  process.exit(1);
}
const forbidden = [/api\//, /secret/i, /token/i, /static\/app/, /data-i18n/];
let failed = false;
for (const name of files) {
  const content = readFileSync(join(assetsDir, name), "utf8");
  for (const pattern of forbidden) {
    if (pattern.test(content)) {
      console.error(`bundle ${name} matches forbidden pattern ${pattern}`);
      failed = true;
    }
  }
}
console.log(failed ? "bundle guard FAILED" : `bundle guard OK (${files.length} file(s))`);
process.exit(failed ? 1 : 0);
