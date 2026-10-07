const { spawnSync } = require("child_process");
const path = require("path");

const projectDir = path.resolve(__dirname, "..");
const backendDir = path.resolve(projectDir, "../backend");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const venvPython =
  process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");

function commandExists(command) {
  const result = spawnSync(command, ["--version"], { stdio: "ignore" });
  return !result.error && result.status === 0;
}

function resolvePython() {
  for (const candidate of [process.env.PYTHON, venvPython, "python3", "python"].filter(Boolean)) {
    if (commandExists(candidate)) return candidate;
  }
  console.error("Unable to find Python. Set PYTHON to the backend virtualenv interpreter.");
  process.exit(1);
}

const python = resolvePython();

function run(command, args, cwd) {
  console.log(`\n> ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, { cwd, stdio: "inherit" });
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const mode = process.argv[2] || "full";
if (mode === "quick") {
  run(npm, ["run", "test"], projectDir);
  run(python, ["-m", "pytest", "-v"], backendDir);
  console.log("\n✅ QUICK CHECKS PASSED");
} else if (mode === "build") {
  run(npm, ["run", "build"], projectDir);
  run(python, ["-m", "compileall", "-q", "app"], backendDir);
  run(python, ["-c", "from app.main import app; print('BACKEND IMPORT OK', app.version)"], backendDir);
  console.log("\n✅ BUILD CHECKS PASSED");
} else if (mode === "full") {
  run(npx, ["tsc", "--noEmit"], projectDir);
  run(npx, ["vitest", "run"], projectDir);
  run(npm, ["run", "build:dev"], projectDir);
  run(python, ["-m", "compileall", "-q", "app"], backendDir);
  run(python, ["-c", "from app.main import app; print('BACKEND IMPORT OK', app.version)"], backendDir);
  run(python, ["-m", "pytest", "-v"], backendDir);
  console.log("\n✅ ALL PACKAGE CHECKS PASSED");
} else {
  console.error(`Unknown verification mode: ${mode}`);
  process.exit(2);
}
