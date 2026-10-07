const { spawnSync } = require("child_process");
const path = require("path");

const projectDir = path.resolve(__dirname, "..");
const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const result = spawnSync(npx, ["webpack", "--mode", "production"], {
  cwd: projectDir,
  stdio: "inherit",
  env: { ...process.env, BASE_URL: process.env.BASE_URL || "https://word-addin-plum.vercel.app/" },
});
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
