const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("loci", {
  detectEnvironment: () => ipcRenderer.invoke("detect-environment"),
  findMemoryDirs: () => ipcRenderer.invoke("find-memory-dirs"),
  pickDirectory: (title) => ipcRenderer.invoke("pick-directory", { title }),
  runInstall: (opts) => ipcRenderer.invoke("run-install", opts),
  onInstallProgress: (callback) =>
    ipcRenderer.on("install-progress", (_event, msg) => callback(msg)),
});
