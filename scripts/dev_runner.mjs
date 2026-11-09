import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const isWindows = process.platform === "win32";

const pyDepsDir = path.join(rootDir, "node_modules", ".saher_pydeps");
const saherBinDir = path.join(rootDir, "node_modules", ".saher_bin");
const saherLibDir = path.join(saherBinDir, "lib");

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
  const sep = isWindows ? ";" : ":";
  const existingPythonPath = process.env.PYTHONPATH || "";
  const pyPathParts = [rootDir, pyDepsDir];
  if (existingPythonPath) {
    pyPathParts.push(existingPythonPath);
  }

  const existingPath = process.env.PATH || "";
  const pathParts = [
    saherBinDir,
    path.join(pyDepsDir, "bin"),
    existingPath,
  ].filter(Boolean);

  const existingLdPath = process.env.LD_LIBRARY_PATH || "";
  const ldParts = [saherLibDir, existingLdPath].filter(Boolean);

  return {
    ...process.env,
    PYTHONPATH: pyPathParts.join(sep),
    PATH: pathParts.join(sep),
    LD_LIBRARY_PATH: ldParts.join(sep),
    PYTHONIOENCODING: "utf-8",
    PIP_BREAK_SYSTEM_PACKAGES: "1",
  };
}

function hasPythonDeps(pyBin, pyEnv) {
  try {
    const res = spawnSync(
      pyBin,
      ["-c", "import fastapi, uvicorn, pydantic, docx, PIL, pypdf, pypdfium2, pytesseract, reportlab"],
      {
        cwd: rootDir,
        env: pyEnv,
        stdio: "ignore",
        shell: isWindows,
      },
    );
    return res.status === 0;
  } catch {
    return false;
  }
}

function ensurePythonDepsSync(pyBin, pyEnv) {
  if (hasPythonDeps(pyBin, pyEnv)) {
    return;
  }
  console.log("[SAHER] Bootstrapping Python backend dependencies into node_modules/.saher_pydeps...");
  fs.mkdirSync(pyDepsDir, { recursive: true });
  const pkgs = [
    "fastapi>=0.110.0",
    "uvicorn>=0.29.0",
    "pydantic>=2.7.0",
    "python-multipart>=0.0.9",
    "pypdf>=4.2.0",
    "pypdfium2>=4.25.0",
    "Pillow>=10.0.0",
    "pytesseract>=0.3.10",
    "reportlab>=4.0.0",
    "python-docx>=1.1.0",
    "openpyxl>=3.1.2",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
  ];
  spawnSync(
    pyBin,
    ["-m", "pip", "install", "--quiet", "--target", pyDepsDir, ...pkgs],
    {
      cwd: rootDir,
      env: pyEnv,
      stdio: "inherit",
      shell: isWindows,
    },
  );
}

function ensureLocalModels() {
  const cachedModelsDir = path.join(rootDir, "node_modules", ".saher_models");
  const targetModelsDir = path.join(rootDir, "data", "models");
  const targetFas = path.join(targetModelsDir, "tessdata", "fas.traineddata");
  if (!fs.existsSync(targetFas) && fs.existsSync(cachedModelsDir)) {
    try {
      fs.mkdirSync(targetModelsDir, { recursive: true });
      fs.cpSync(cachedModelsDir, targetModelsDir, { recursive: true });
    } catch {
      // Ignore copy errors
    }
  }
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
ensureLocalModels();

if (mode === "build") {
  const npmCmd = isWindows ? "npm.cmd" : "npm";
  const buildRes = spawnSync(npmCmd, ["run", "build", "--workspace=apps/web"], {
    cwd: rootDir,
    stdio: "inherit",
    shell: isWindows,
  });
  if (buildRes.status !== 0) {
    process.exit(buildRes.status ?? 1);
  }
  const webDist = path.join(rootDir, "apps", "web", "dist");
  const rootDist = path.join(rootDir, "dist");
  if (!fs.existsSync(webDist)) {
    console.error(`Expected build output at ${webDist} was not found.`);
    process.exit(1);
  }
  fs.rmSync(rootDist, { recursive: true, force: true });
  fs.cpSync(webDist, rootDist, { recursive: true });
  process.exit(0);
} else if (mode === "api") {
  ensurePythonDepsSync(pyBin, pyEnv);
  const proc = spawnManaged(
    pyBin,
    ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", apiPort],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "worker") {
  ensurePythonDepsSync(pyBin, pyEnv);
  const proc = spawnManaged(
    pyBin,
    ["-m", "services.worker.runner"],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "pytest") {
  ensurePythonDepsSync(pyBin, pyEnv);
  const extraArgs = process.argv.slice(3);
  const pytestArgs = extraArgs.length > 0 ? extraArgs : ["-v", "tests/"];
  const proc = spawnManaged(
    pyBin,
    ["-m", "pytest", ...pytestArgs],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "dev") {
  let shuttingDown = false;
  let apiProc = null;

  // 1. Start Vite on port 3000 IMMEDIATELY so the dev server port is bound within <1s
  const viteBinJs = path.join(rootDir, "apps", "web", "node_modules", "vite", "bin", "vite.js");
  const webDir = path.join(rootDir, "apps", "web");
  const webEnv = {
    ...process.env,
    SAHER_BACKEND_URL: process.env.SAHER_BACKEND_URL || `http://127.0.0.1:${apiPort}`,
  };

  const webProc = fs.existsSync(viteBinJs)
    ? spawn(process.execPath, [viteBinJs, "--host", "0.0.0.0", "--port", "3000"], {
        cwd: webDir,
        env: webEnv,
        stdio: "inherit",
      })
    : spawn(isWindows ? "npm.cmd" : "npm", ["run", "dev", "--workspace=apps/web"], {
        cwd: rootDir,
        env: webEnv,
        stdio: "inherit",
        shell: isWindows,
      });

  // 2. Launch and supervise FastAPI backend on port 8765
  function startApiServer() {
    if (shuttingDown) return;
    apiProc = spawn(
      pyBin,
      ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", apiPort],
      {
        cwd: rootDir,
        env: pyEnv,
        stdio: "inherit",
        shell: isWindows,
      },
    );

    apiProc.on("exit", (code) => {
      if (!shuttingDown && code !== 0) {
        setTimeout(() => {
          if (!shuttingDown) startApiServer();
        }, 2000);
      }
    });
  }

  if (hasPythonDeps(pyBin, pyEnv)) {
    startApiServer();
  } else {
    // Bootstrap Python deps asynchronously without blocking Vite on port 3000
    const bootCmd = isWindows ? "python" : "sh";
    const bootArgs = isWindows
      ? ["-m", "pip", "install", "--quiet", "--target", pyDepsDir, "fastapi", "uvicorn", "pydantic", "python-multipart", "pypdf", "pypdfium2", "Pillow", "pytesseract", "reportlab", "python-docx", "openpyxl"]
      : [
          "-c",
          `if ! python3 -m pip --version >/dev/null 2>&1; then export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq python3-pip tesseract-ocr >/dev/null 2>&1 || true; fi; mkdir -p "${pyDepsDir}" && python3 -m pip install --quiet --target="${pyDepsDir}" "fastapi>=0.110.0" "uvicorn>=0.29.0" "pydantic>=2.7.0" "python-multipart>=0.0.9" "pypdf>=4.2.0" "pypdfium2>=4.25.0" "Pillow>=10.0.0" "pytesseract>=0.3.10" "reportlab>=4.0.0" "python-docx>=1.1.0" "openpyxl>=3.1.2"`,
        ];
    const bootProc = spawn(bootCmd, bootArgs, {
      cwd: rootDir,
      env: pyEnv,
      stdio: "inherit",
    });
    bootProc.on("exit", () => {
      if (!shuttingDown) startApiServer();
    });
  }

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

