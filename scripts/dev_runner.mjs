import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const isWindows = process.platform === "win32";

const legacyPyDepsDir = path.join(rootDir, "node_modules", ".saher_pydeps");
const pyDepsDir = isWindows ? legacyPyDepsDir : "/var/tmp/saher_pydeps";
const saherBinDir = isWindows
  ? path.join(rootDir, "node_modules", ".saher_bin")
  : "/var/tmp/saher_bin";
const saherLibDir = path.join(saherBinDir, "lib");

if (!isWindows && !fs.existsSync(path.join(pyDepsDir, "fastapi")) && fs.existsSync(path.join(legacyPyDepsDir, "fastapi"))) {
  try {
    fs.mkdirSync(pyDepsDir, { recursive: true });
    fs.cpSync(legacyPyDepsDir, pyDepsDir, { recursive: true });
  } catch {
    // Ignore copy errors
  }
}

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
  if (!isWindows && fs.existsSync(legacyPyDepsDir)) {
    pyPathParts.push(legacyPyDepsDir);
  }
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

function ensureSystemAndPythonDepsSync(pyBin, pyEnv) {
  if (!isWindows) {
    const hasFas =
      fs.existsSync(path.join(rootDir, "data", "models", "tessdata", "fas.traineddata")) ||
      fs.existsSync("/usr/share/tesseract-ocr/5/tessdata/fas.traineddata");
    const hasRaqm =
      fs.existsSync("/usr/lib/x86_64-linux-gnu/libraqm.so.0") ||
      fs.existsSync("/usr/lib/aarch64-linux-gnu/libraqm.so.0");
    const hasTess = spawnSync("which", ["tesseract"], { stdio: "ignore" }).status === 0;
    if (!hasTess || !hasFas || !hasRaqm) {
      spawnSync(
        "sh",
        [
          "-c",
          'export DEBIAN_FRONTEND=noninteractive; dpkg --configure -a < /dev/null >/dev/null 2>&1 || true; apt-get update -qq < /dev/null && apt-get install -y -qq --no-install-recommends -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3-pip tesseract-ocr tesseract-ocr-fas libraqm0 fonts-dejavu-core < /dev/null >/dev/null 2>&1 || true',
        ],
        { cwd: rootDir, stdio: ["ignore", "inherit", "inherit"] },
      );
    }
  }
  ensureLocalModels();
  if (hasPythonDeps(pyBin, pyEnv)) {
    return;
  }
  console.log(`[SAHER] Bootstrapping Python backend dependencies into ${pyDepsDir}...`);
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
      stdio: ["ignore", "inherit", "inherit"],
      shell: isWindows,
    },
  );
}

function ensureLocalModels() {
  const cachedModelsDir = isWindows
    ? path.join(rootDir, "node_modules", ".saher_models")
    : "/var/tmp/saher_models";
  const targetModelsDir = path.join(rootDir, "data", "models");
  const targetTessdataDir = path.join(targetModelsDir, "tessdata");
  const targetFas = path.join(targetTessdataDir, "fas.traineddata");
  if (!fs.existsSync(targetFas)) {
    if (fs.existsSync(cachedModelsDir)) {
      try {
        fs.mkdirSync(targetModelsDir, { recursive: true });
        fs.cpSync(cachedModelsDir, targetModelsDir, { recursive: true });
      } catch {
        // Ignore copy errors
      }
    } else if (fs.existsSync("/usr/share/tesseract-ocr/5/tessdata/fas.traineddata")) {
      try {
        fs.mkdirSync(targetTessdataDir, { recursive: true });
        const cacheTessDir = path.join(cachedModelsDir, "tessdata");
        fs.mkdirSync(cacheTessDir, { recursive: true });
        for (const f of ["fas.traineddata", "eng.traineddata", "osd.traineddata"]) {
          const src = path.join("/usr/share/tesseract-ocr/5/tessdata", f);
          if (fs.existsSync(src)) {
            fs.copyFileSync(src, path.join(targetTessdataDir, f));
            fs.copyFileSync(src, path.join(cacheTessDir, f));
          }
        }
      } catch {
        // Ignore copy errors
      }
    }
  }

  const targetFontsDir = path.join(targetModelsDir, "fonts");
  const targetFontFile = path.join(targetFontsDir, "Vazirmatn.ttf");
  const bundledVazirmatn = path.join(rootDir, "apps", "web", "public", "fonts", "Vazirmatn.woff2");
  if (fs.existsSync(bundledVazirmatn)) {
    try {
      fs.mkdirSync(targetFontsDir, { recursive: true });
      fs.copyFileSync(bundledVazirmatn, targetFontFile);
      const cacheFontsDir = path.join(cachedModelsDir, "fonts");
      fs.mkdirSync(cacheFontsDir, { recursive: true });
      fs.copyFileSync(bundledVazirmatn, path.join(cacheFontsDir, "Vazirmatn.ttf"));
    } catch {
      // Ignore copy errors
    }
  } else if (!fs.existsSync(targetFontFile)) {
    const sysFonts = [
      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
      "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    ];
    for (const sf of sysFonts) {
      if (fs.existsSync(sf)) {
        try {
          fs.mkdirSync(targetFontsDir, { recursive: true });
          fs.copyFileSync(sf, targetFontFile);
          const cacheFontsDir = path.join(cachedModelsDir, "fonts");
          fs.mkdirSync(cacheFontsDir, { recursive: true });
          fs.copyFileSync(sf, path.join(cacheFontsDir, "Vazirmatn.ttf"));
        } catch {
          // Ignore copy errors
        }
        break;
      }
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
const apiPort = process.env.SAHER_API_PORT || "8765";

if (mode === "dev") {
  let shuttingDown = false;
  let apiProc = null;
  let standInServer = null;

  // 1. Start a lightweight warmup listener on 127.0.0.1:8765 immediately so Vite proxy
  // never encounters ECONNREFUSED while Python dependencies or Uvicorn are booting.
  standInServer = http.createServer((req, res) => {
    const url = req.url || "/";
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    if (url.startsWith("/health")) {
      res.writeHead(200);
      res.end(
        JSON.stringify({
          status: "starting",
          service: "saher-local-api",
          version: "0.3.0",
          database: "initializing",
          storage_accessible: true,
          demo_mode: false,
          worker_online: false,
          ocr_ready: false,
        }),
      );
    } else {
      res.writeHead(425);
      res.end(
        JSON.stringify({
          detail: "سرویس محلی ساهر در حال راه‌اندازی اولیه است. لطفاً چند ثانیه صبر کنید…",
          code: "BACKEND_STARTING",
        }),
      );
    }
  });
  standInServer.on("error", () => {
    standInServer = null;
  });
  standInServer.listen(Number(apiPort), "127.0.0.1");

  // 2. Start Vite on port 3000 immediately before any synchronous checks so port 3000 binds in <500ms
  const viteCandidates = [
    path.join(rootDir, "apps", "web", "node_modules", "vite", "bin", "vite.js"),
    path.join(rootDir, "node_modules", "vite", "bin", "vite.js"),
  ];
  const viteBinJs = viteCandidates.find((p) => fs.existsSync(p));
  const webDir = path.join(rootDir, "apps", "web");
  const webEnv = {
    ...process.env,
    SAHER_BACKEND_URL: process.env.SAHER_BACKEND_URL || `http://127.0.0.1:${apiPort}`,
  };

  const webProc = viteBinJs
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

  // 3. Defer Python/backend startup slightly so Vite finishes binding port 3000 without I/O contention
  setTimeout(() => {
    if (shuttingDown) return;
    const pyBin = resolvePythonBinary();
    const pyEnv = getPythonEnv();
    ensureLocalModels();

    function spawnUvicorn() {
      if (shuttingDown || apiProc) return;
      ensureLocalModels();
      apiProc = spawn(
        pyBin,
        ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", apiPort],
        {
          cwd: rootDir,
          env: pyEnv,
          stdio: ["ignore", "inherit", "inherit"],
          shell: isWindows,
        },
      );

      apiProc.on("exit", (code) => {
        apiProc = null;
        if (!shuttingDown && code !== 0) {
          setTimeout(() => {
            if (!shuttingDown) startApiServer();
          }, 2000);
        }
      });
    }

    function startApiServer() {
      if (shuttingDown || apiProc) return;
      if (standInServer) {
        const srv = standInServer;
        standInServer = null;
        try {
          if (typeof srv.closeAllConnections === "function") {
            srv.closeAllConnections();
          }
          srv.close(() => {
            spawnUvicorn();
          });
        } catch {
          spawnUvicorn();
        }
      } else {
        spawnUvicorn();
      }
    }

    const hasFas =
      fs.existsSync(path.join(rootDir, "data", "models", "tessdata", "fas.traineddata")) ||
      fs.existsSync("/usr/share/tesseract-ocr/5/tessdata/fas.traineddata");
    const hasRaqm =
      fs.existsSync("/usr/lib/x86_64-linux-gnu/libraqm.so.0") ||
      fs.existsSync("/usr/lib/aarch64-linux-gnu/libraqm.so.0");

    if (hasPythonDeps(pyBin, pyEnv)) {
      startApiServer();
      if ((!hasFas || !hasRaqm) && !isWindows) {
        const modelBoot = spawn(
          "sh",
          [
            "-c",
            'export DEBIAN_FRONTEND=noninteractive; dpkg --configure -a < /dev/null >/dev/null 2>&1 || true; apt-get update -qq < /dev/null && apt-get install -y -qq --no-install-recommends -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" tesseract-ocr tesseract-ocr-fas libraqm0 fonts-dejavu-core < /dev/null >/dev/null 2>&1 || true',
          ],
          { cwd: rootDir, env: pyEnv, stdio: ["ignore", "inherit", "inherit"] },
        );
        modelBoot.on("exit", () => {
          ensureLocalModels();
        });
      }
    } else {
      const bootCmd = isWindows ? "python" : "sh";
      const bootArgs = isWindows
        ? [
            "-m",
            "pip",
            "install",
            "--quiet",
            "--target",
            pyDepsDir,
            "fastapi",
            "uvicorn",
            "pydantic",
            "python-multipart",
            "pypdf",
            "pypdfium2",
            "Pillow",
            "pytesseract",
            "reportlab",
            "python-docx",
            "openpyxl",
            "pytest",
            "pytest-asyncio",
            "httpx",
          ]
        : [
            "-c",
            `if ! python3 -m pip --version >/dev/null 2>&1 || [ ! -f /usr/share/tesseract-ocr/5/tessdata/fas.traineddata ] || [ ! -f /usr/lib/x86_64-linux-gnu/libraqm.so.0 ]; then export DEBIAN_FRONTEND=noninteractive; dpkg --configure -a < /dev/null >/dev/null 2>&1 || true; apt-get update -qq < /dev/null && apt-get install -y -qq --no-install-recommends -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3-pip tesseract-ocr tesseract-ocr-fas libraqm0 fonts-dejavu-core < /dev/null >/dev/null 2>&1 || true; fi; if [ ! -d "${pyDepsDir}/fastapi" ]; then mkdir -p "${pyDepsDir}" && python3 -m pip install --quiet --target="${pyDepsDir}" "fastapi>=0.110.0" "uvicorn>=0.29.0" "pydantic>=2.7.0" "python-multipart>=0.0.9" "pypdf>=4.2.0" "pypdfium2>=4.25.0" "Pillow>=10.0.0" "pytesseract>=0.3.10" "reportlab>=4.0.0" "python-docx>=1.1.0" "openpyxl>=3.1.2" "pytest>=8.0.0" "pytest-asyncio>=0.23.0" "httpx>=0.27.0" < /dev/null; fi`,
          ];
      const bootProc = spawn(bootCmd, bootArgs, {
        cwd: rootDir,
        env: pyEnv,
        stdio: ["ignore", "inherit", "inherit"],
      });
      bootProc.on("exit", () => {
        if (!shuttingDown) startApiServer();
      });
    }
  }, 300);

  function shutdownAll(exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    if (standInServer) {
      try {
        standInServer.close();
      } catch {
        // Ignore close errors
      }
      standInServer = null;
    }
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
} else if (mode === "build") {
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
  const pyBin = resolvePythonBinary();
  const pyEnv = getPythonEnv();
  ensureSystemAndPythonDepsSync(pyBin, pyEnv);
  const proc = spawnManaged(
    pyBin,
    ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", apiPort],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "worker") {
  const pyBin = resolvePythonBinary();
  const pyEnv = getPythonEnv();
  ensureSystemAndPythonDepsSync(pyBin, pyEnv);
  const proc = spawnManaged(
    pyBin,
    ["-m", "services.worker.runner"],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else if (mode === "pytest") {
  const pyBin = resolvePythonBinary();
  const pyEnv = getPythonEnv();
  ensureSystemAndPythonDepsSync(pyBin, pyEnv);
  const extraArgs = process.argv.slice(3);
  const pytestArgs = extraArgs.length > 0 ? extraArgs : ["-v", "tests/"];
  const proc = spawnManaged(
    pyBin,
    ["-m", "pytest", ...pytestArgs],
    { env: pyEnv },
  );
  proc.on("exit", (code) => process.exit(code ?? 0));
} else {
  console.error(`Unknown dev_runner command: ${mode}`);
  process.exit(1);
}


