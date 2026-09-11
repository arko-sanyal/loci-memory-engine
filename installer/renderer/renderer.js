let detected = null;
let memoryDir = null;
let projectDir = null;

const detectOutput = document.getElementById("detect-output");
const btnDetectNext = document.getElementById("btn-detect-next");

async function runDetect() {
  detected = await window.loci.detectEnvironment();
  const lines = [];
  lines.push(`Platform: ${detected.platform}`);
  if (detected.python) {
    lines.push(`Python found: ${detected.python.bin} (${detected.python.version})`);
  } else {
    lines.push("Python NOT found - install Python 3.11+ and re-run this installer.");
  }
  lines.push(`loci_engine already importable: ${detected.pythonHasLociEngine}`);
  lines.push(`ollama python package importable: ${detected.pythonHasOllamaLib}`);
  lines.push(`Ollama reachable at localhost:11434: ${detected.ollama.reachable}`);
  if (detected.ollama.reachable) {
    lines.push(`nomic-embed-text pulled: ${detected.ollama.hasEmbedModel}`);
  } else {
    lines.push("Ollama not reachable - recall.py needs it running for embeddings.");
  }
  detectOutput.textContent = lines.join("\n");
  btnDetectNext.disabled = !detected.python;
}

btnDetectNext.addEventListener("click", async () => {
  document.getElementById("step-detect").hidden = true;
  document.getElementById("step-choose").hidden = false;

  const select = document.getElementById("memory-dir-select");
  const dirs = await window.loci.findMemoryDirs();
  select.innerHTML = "";
  if (dirs.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "(none found - browse for one)";
    opt.value = "";
    select.appendChild(opt);
  } else {
    for (const dir of dirs) {
      const opt = document.createElement("option");
      opt.value = dir;
      opt.textContent = dir;
      select.appendChild(opt);
    }
    memoryDir = dirs[0];
    document.getElementById("memory-dir-chosen").textContent = memoryDir;
  }
  select.addEventListener("change", () => {
    memoryDir = select.value || null;
    document.getElementById("memory-dir-chosen").textContent = memoryDir || "";
    updateChooseNext();
  });
});

document.getElementById("btn-browse-memory").addEventListener("click", async () => {
  const dir = await window.loci.pickDirectory("Choose the auto-memory directory");
  if (dir) {
    memoryDir = dir;
    document.getElementById("memory-dir-chosen").textContent = memoryDir;
    updateChooseNext();
  }
});

document.getElementById("btn-browse-project").addEventListener("click", async () => {
  const dir = await window.loci.pickDirectory("Choose the project directory");
  if (dir) {
    projectDir = dir;
    document.getElementById("project-dir-chosen").textContent = projectDir;
    updateChooseNext();
  }
});

function updateChooseNext() {
  document.getElementById("btn-choose-next").disabled = !(memoryDir && projectDir);
}

document.getElementById("btn-choose-next").addEventListener("click", async () => {
  document.getElementById("step-choose").hidden = true;
  document.getElementById("step-install").hidden = false;

  const installOutput = document.getElementById("install-output");
  window.loci.onInstallProgress((msg) => {
    installOutput.textContent += msg + "\n";
  });

  const result = await window.loci.runInstall({
    pythonBin: detected.python.bin,
    memoryDir,
    projectDir,
  });

  document.getElementById("step-install").hidden = true;
  document.getElementById("step-done").hidden = false;
  document.getElementById("done-summary").textContent = result.ok
    ? "Setup complete. See the log above for what changed."
    : "Setup failed - see the log above for the error.";
});

runDetect();
