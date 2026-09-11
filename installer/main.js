// LOCI Engine installer - Electron main process.
//
// Every step here does a real, observable action (spawns python3, hits the
// Ollama HTTP API, reads/writes real files) - nothing here is simulated for
// the wizard UI. Config writes always read-then-merge; they never overwrite
// an existing settings.json wholesale.

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const http = require("http");
const { spawnSync } = require("child_process");

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 720,
    height: 640,
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// ---------------------------------------------------------------------------
// Detection

function findPython() {
  const candidates =
    process.platform === "win32" ? ["python.exe", "python3.exe", "python"] : ["python3", "python"];
  for (const bin of candidates) {
    const result = spawnSync(bin, ["--version"], { encoding: "utf8" });
    if (result.status === 0) {
      const versionOut = (result.stdout || result.stderr || "").trim();
      const which = spawnSync(process.platform === "win32" ? "where" : "which", [bin], {
        encoding: "utf8",
      });
      const resolvedPath = which.status === 0 ? which.stdout.split(/\r?\n/)[0].trim() : bin;
      return { bin: resolvedPath || bin, version: versionOut };
    }
  }
  return null;
}

function checkImportable(pythonBin, moduleName) {
  const result = spawnSync(pythonBin, ["-c", `import ${moduleName}`], { encoding: "utf8" });
  return result.status === 0;
}

function checkOllama() {
  return new Promise((resolve) => {
    const req = http.get({ host: "localhost", port: 11434, path: "/api/tags", timeout: 1500 }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        try {
          const parsed = JSON.parse(body);
          const models = (parsed.models || []).map((m) => m.name || m.model || "");
          resolve({ reachable: true, hasEmbedModel: models.some((m) => m.startsWith("nomic-embed-text")) });
        } catch {
          resolve({ reachable: true, hasEmbedModel: false });
        }
      });
    });
    req.on("error", () => resolve({ reachable: false, hasEmbedModel: false }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ reachable: false, hasEmbedModel: false });
    });
  });
}

ipcMain.handle("detect-environment", async () => {
  const python = findPython();
  const ollama = await checkOllama();
  return {
    platform: process.platform,
    python,
    pythonHasLociEngine: python ? checkImportable(python.bin, "loci_engine") : false,
    pythonHasOllamaLib: python ? checkImportable(python.bin, "ollama") : false,
    ollama,
  };
});

// ---------------------------------------------------------------------------
// Locating the target Claude Code project + auto-memory directory

function findMemoryDirs() {
  const base = path.join(os.homedir(), ".claude", "projects");
  const found = [];
  if (!fs.existsSync(base)) return found;
  for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const memoryDir = path.join(base, entry.name, "memory");
    const memoryIndex = path.join(memoryDir, "MEMORY.md");
    if (fs.existsSync(memoryIndex)) {
      found.push(memoryDir);
    }
  }
  return found;
}

ipcMain.handle("find-memory-dirs", () => findMemoryDirs());

ipcMain.handle("pick-directory", async (_event, { title }) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: title || "Choose a directory",
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// ---------------------------------------------------------------------------
// Install

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) return {};
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null; // malformed - caller must not blindly overwrite
  }
}

function ensureGitignored(projectDir, relativePath) {
  const gitignorePath = path.join(projectDir, ".gitignore");
  const existing = fs.existsSync(gitignorePath) ? fs.readFileSync(gitignorePath, "utf8") : "";
  if (existing.split(/\r?\n/).includes(relativePath)) return;
  const sep = existing.length && !existing.endsWith("\n") ? "\n" : "";
  fs.writeFileSync(
    gitignorePath,
    existing + sep + `\n# Added by loci-engine-installer (personal, machine-specific)\n${relativePath}\n`
  );
}

ipcMain.handle("run-install", async (_event, { pythonBin, memoryDir, projectDir }) => {
  const log = [];
  const step = (msg) => {
    log.push(msg);
    mainWindow.webContents.send("install-progress", msg);
  };

  // 1. Install the bundled loci_engine package.
  const pkgSrc = app.isPackaged
    ? path.join(process.resourcesPath, "loci_engine_pkg")
    : path.join(__dirname, "resources", "loci_engine_pkg");
  step(`Installing loci_engine from ${pkgSrc} ...`);
  const pipInstall = spawnSync(pythonBin, ["-m", "pip", "install", "--user", pkgSrc], {
    encoding: "utf8",
  });
  if (pipInstall.status !== 0) {
    step(`pip install failed:\n${pipInstall.stderr}`);
    return { ok: false, log };
  }
  step("loci_engine installed.");

  // 2. Write recall.py from template.
  fs.mkdirSync(memoryDir, { recursive: true });
  const recallTemplatePath = app.isPackaged
    ? path.join(process.resourcesPath, "templates", "recall.py.tmpl")
    : path.join(__dirname, "templates", "recall.py.tmpl");
  const dbPath = path.join(memoryDir, "loci_memory.sqlite3").replace(/\\/g, "/");
  let recallSrc = fs.readFileSync(recallTemplatePath, "utf8");
  recallSrc = recallSrc.replace("{{DB_PATH}}", dbPath).replace("{{NAMESPACE}}", "claude_memory::");
  const recallOutPath = path.join(memoryDir, "recall.py");
  fs.writeFileSync(recallOutPath, recallSrc);
  step(`Wrote ${recallOutPath}`);

  // 3. Write postcompact_hook.py from template.
  const hookTemplatePath = app.isPackaged
    ? path.join(process.resourcesPath, "templates", "postcompact_hook.py.tmpl")
    : path.join(__dirname, "templates", "postcompact_hook.py.tmpl");
  let hookSrc = fs.readFileSync(hookTemplatePath, "utf8");
  hookSrc = hookSrc.replace("{{PYTHON}}", pythonBin).replace("{{RECALL_PATH}}", recallOutPath);
  const hookOutPath = path.join(memoryDir, "postcompact_hook.py");
  fs.writeFileSync(hookOutPath, hookSrc);
  step(`Wrote ${hookOutPath}`);

  // 4. Merge the PostCompact hook into <projectDir>/.claude/settings.local.json
  //    (read-then-merge - never overwrite an existing file wholesale).
  const claudeDir = path.join(projectDir, ".claude");
  fs.mkdirSync(claudeDir, { recursive: true });
  const settingsPath = path.join(claudeDir, "settings.local.json");
  const settings = readJsonIfExists(settingsPath);
  if (settings === null) {
    step(`ERROR: ${settingsPath} exists but is not valid JSON - refusing to touch it. Fix or remove it and re-run.`);
    return { ok: false, log };
  }
  settings.hooks = settings.hooks || {};
  settings.hooks.PostCompact = settings.hooks.PostCompact || [];
  const alreadyWired = settings.hooks.PostCompact.some((entry) =>
    (entry.hooks || []).some((h) => h.command && h.command.includes("postcompact_hook.py"))
  );
  if (!alreadyWired) {
    settings.hooks.PostCompact.push({
      matcher: ".*",
      hooks: [
        {
          type: "command",
          command: `${pythonBin} ${hookOutPath}`,
          timeout: 60,
          statusMessage: "Reloading memory after compaction...",
        },
      ],
    });
  }
  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n");
  step(`Merged PostCompact hook into ${settingsPath}`);

  // 5. Keep the personal settings file out of the target project's git history.
  ensureGitignored(projectDir, ".claude/settings.local.json");
  step("Confirmed .claude/settings.local.json is gitignored in the target project.");

  step("Done. Restart Claude Code (or run /hooks) in that project for the hook to take effect.");
  return { ok: true, log };
});
