import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const isWindows = process.platform === "win32";

function resolvePythonBinary() {
  const candidates = isWindows
    ? ["python", "py", "python3"]
    : ["python3", "python"];

  for (const bin of candidates) {
    try {
      const res = spawnSync(bin, ["--version"], {
        stdio: "ignore",
        shell: isWindows,
      });
      if (res.status === 0) {
        return bin;
      }
    } catch {
      // Try next candidate
    }
  }
  return isWindows ? "python" : "python3";
}

function getPythonEnv() {
  const existingPythonPath = process.env.PYTHONPATH || "";
  const sep = isWindows ? ";" : ":";
  const newPythonPath = existingPythonPath
    ? `${rootDir}${sep}${existingPythonPath}`
    : rootDir;
  return {
    ...process.env,
    PYTHONPATH: newPythonPath,
    PYTHONIOENCODING: "utf-8",
  };
}

function spawnManaged(command, args, options = {}) {
  return spawn(command, args, {
    cwd: rootDir,
    stdio: "inherit",
    shell: isWindows,
    ...options,
  });
}

const mode = process.argv[2] || "dev";
const pyBin = resolvePythonBinary();
const pyEnv = getPythonEnv();
const apiPort = process.env.SAHER_API_PORT || "8765";

if (mode === "api") {
  const proc = spawnManaged(
    pyBin,
    ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", apiPort],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "worker") {
  const proc = spawnManaged(
    pyBin,
    ["-m", "services.worker.runner"],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "pytest") {
  const extraArgs = process.argv.slice(3);
  const pytestArgs = extraArgs.length > 0 ? extraArgs : ["-v", "tests/"];
  const proc = spawnManaged(
    pyBin,
    ["-m", "pytest", ...pytestArgs],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "dev") {
  const apiProc = spawn(
    pyBin,
    ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", apiPort],
    {
      cwd: rootDir,
      env: pyEnv,
      stdio: "ignore",
      shell: isWindows,
    },
  );
  apiProc.unref();

  const npmCmd = isWindows ? "npm.cmd" : "npm";
  const webProc = spawn(
    npmCmd,
    ["run", "dev", "--workspace=apps/web"],
    {
      cwd: rootDir,
      env: {
        ...process.env,
        SAHER_BACKEND_URL: process.env.SAHER_BACKEND_URL || `http://127.0.0.1:${apiPort}`,
      },
      stdio: "inherit",
      shell: isWindows,
    },
  );

  let shuttingDown = false;
  function shutdownAll(exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    for (const child of [webProc, apiProc]) {
      if (child && !child.killed) {
        try {
          child.kill("SIGTERM");
        } catch {
          // Ignore kill errors
        }
      }
    }
    process.exit(exitCode);
  }

  process.on("SIGINT", () => shutdownAll(0));
  process.on("SIGTERM", () => shutdownAll(0));

  webProc.on("exit", (code) => shutdownAll(code ?? 0));
} else {
  console.error(`Unknown dev_runner command: ${mode}`);
  process.exit(1);
}
