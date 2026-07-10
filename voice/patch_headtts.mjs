// Local patches applied to the pinned HeadTTS clone (voice/headtts).
// Run from the voice/headtts directory:  node ../patch_headtts.mjs
// Idempotent; invoked by scripts/setup_voice.ps1.
import fs from "node:fs";

// Patch A (Windows gotcha): upstream postinstall is
//   mkdir -p -m 777 ./node_modules/@huggingface/transformers/.cache
// which fails under npm on Windows (mkdir has no -p/-m there).
// Replace with a cross-platform node one-liner.
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
const crossPostinstall =
  "node -e \"require('fs').mkdirSync('./node_modules/@huggingface/transformers/.cache',{recursive:true})\"";
if (pkg.scripts.postinstall !== crossPostinstall) {
  pkg.scripts.postinstall = crossPostinstall;
  fs.writeFileSync("package.json", JSON.stringify(pkg, null, 2) + "\n");
  console.log("Patched package.json postinstall (cross-platform mkdir).");
} else {
  console.log("package.json postinstall already patched.");
}

// Patch B: bind the HTTP/WebSocket server to 127.0.0.1 only
// (upstream's httpServer.listen(port) binds all interfaces).
const serverFile = "modules/headtts-node.mjs";
let src = fs.readFileSync(serverFile, "utf8");
const upstreamListen = "httpServer.listen(port, () => {";
const localListen = 'httpServer.listen(port, "127.0.0.1", () => {';
if (src.includes(localListen)) {
  console.log("listen() already bound to 127.0.0.1.");
} else if (src.includes(upstreamListen)) {
  fs.writeFileSync(serverFile, src.replace(upstreamListen, localListen));
  console.log("Patched listen() to bind 127.0.0.1.");
} else {
  console.error("ERROR: listen() call not found - upstream changed? Re-pin the commit.");
  process.exit(1);
}
