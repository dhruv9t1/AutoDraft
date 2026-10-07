const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const projectDir = path.resolve(__dirname, "..");
const manifestPath = path.join(projectDir, "manifest.xml");
const bin = process.platform === "win32"
  ? path.join(projectDir, "node_modules", ".bin", "office-addin-debugging.cmd")
  : path.join(projectDir, "node_modules", ".bin", "office-addin-debugging");

// Office debugging sessions can leave a stale sideload registration behind if
// Word or the terminal was closed without `npm run stop`. A best-effort stop
// before each start makes repeated local runs idempotent.
const result = spawnSync(bin, ["stop", "manifest.xml"], {
  cwd: projectDir,
  stdio: "inherit",
});

if (result.error && result.error.code !== "ENOENT") {
  console.warn(`[AutoDraft] Previous debug-session cleanup could not run: ${result.error.message}`);
}

// On macOS, Office's XML-manifest sideloading uses a link inside Word's `wef`
// directory. If the debugging process was interrupted, that link can survive
// and the next start fails with EEXIST. Remove only entries that are the same
// filesystem object as *this project's* manifest; never delete unrelated add-ins.
if (process.platform === "darwin") {
  const wefDir = path.join(
    os.homedir(),
    "Library",
    "Containers",
    "com.microsoft.Word",
    "Data",
    "Documents",
    "wef"
  );
  try {
    if (fs.existsSync(wefDir) && fs.existsSync(manifestPath)) {
      const manifestStat = fs.statSync(manifestPath);
      for (const name of fs.readdirSync(wefDir)) {
        if (!name.endsWith(".manifest.xml")) continue;
        const candidate = path.join(wefDir, name);
        try {
          const candidateStat = fs.statSync(candidate);
          if (candidateStat.dev === manifestStat.dev && candidateStat.ino === manifestStat.ino) {
            fs.unlinkSync(candidate);
            console.log(`[AutoDraft] Removed stale Word sideload registration: ${name}`);
          }
        } catch {
          // A concurrently removed/inaccessible entry is harmless; startup can proceed.
        }
      }
    }
  } catch (error) {
    console.warn(`[AutoDraft] Stale Word registration cleanup skipped: ${error instanceof Error ? error.message : String(error)}`);
  }
}

// Never block startup merely because there was no previous session to stop.
process.exit(0);
