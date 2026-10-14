'use strict';

/**
 * EasyFig - Electron main process.
 *
 * Responsibilities:
 *   * own the window and its platform-specific chrome (macOS traffic lights,
 *     a Windows title-bar overlay);
 *   * own the Python chart engine (see python-bridge.js) and expose it to the
 *     renderer over a narrow, context-isolated IPC surface;
 *   * show native file dialogs and the application menu;
 *   * support `--smoke`, a headless self-test that starts the engine, renders the
 *     default figure, screenshots the window and exits - used by CI and by the
 *     test suite.
 */

const { app, BrowserWindow, Menu, dialog, ipcMain, nativeTheme, shell } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const { PythonBridge, PROJECT_ROOT, pythonCandidates, resolvePython } = require('./python-bridge');

const ARGV = process.argv.slice(1);
const SMOKE = ARGV.includes('--smoke');
const PROBE = ARGV.includes('--probe');
// `--mode=compose` (or `--mode compose`) starts the interface in composition
// mode, so the self-test and a screenshot can exercise it too.
const modeIndex = ARGV.findIndex((value) => value === '--mode' || value.startsWith('--mode='));
const START_MODE = modeIndex === -1
  ? ''
  : (ARGV[modeIndex].includes('=')
    ? ARGV[modeIndex].split('=').slice(1).join('=')
    : String(ARGV[modeIndex + 1] || ''));
const shotIndex = ARGV.indexOf('--shot');
const SHOT_PATH = shotIndex !== -1 && ARGV[shotIndex + 1]
  ? path.resolve(ARGV[shotIndex + 1])
  : path.join(PROJECT_ROOT, 'electron', '.smoke', 'shot.png');

const TITLEBAR_HEIGHT = 52;

/** Chrome colours per theme; the renderer mirrors these in CSS. */
const CHROME = {
  light: { background: '#ECECEC', symbol: '#3A3A3C' },
  dark: { background: '#1C1C1E', symbol: '#E5E5E7' },
};

let mainWindow = null;
let engine = null;
let engineError = null;
const stateFile = () => path.join(app.getPath('userData'), 'window-state.json');

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

function chrome() {
  return nativeTheme.shouldUseDarkColors ? CHROME.dark : CHROME.light;
}

function loadWindowState() {
  try {
    return JSON.parse(fs.readFileSync(stateFile(), 'utf8'));
  } catch {
    return null;
  }
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMinimized()) return;
  const bounds = mainWindow.getNormalBounds();
  try {
    fs.mkdirSync(path.dirname(stateFile()), { recursive: true });
    fs.writeFileSync(stateFile(), JSON.stringify({ ...bounds, maximized: mainWindow.isMaximized() }));
  } catch {
    /* not important enough to fail over */
  }
}

function createWindow() {
  const saved = loadWindowState();
  const palette = chrome();

  const options = {
    width: saved?.width ?? 1320,
    height: saved?.height ?? 880,
    x: saved?.x,
    y: saved?.y,
    minWidth: 1080,
    minHeight: 700,
    show: false,
    title: 'EasyFig',
    // An opaque window background keeps the appearance identical on every
    // platform and makes screen captures faithful; the "material" is painted
    // by the stylesheet instead of depending on the OS compositor.
    backgroundColor: palette.background,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  };

  if (process.platform === 'darwin') {
    // Apple's own look: inset traffic lights over a translucent sidebar.
    options.titleBarStyle = 'hiddenInset';
    options.trafficLightPosition = { x: 18, y: 19 };
    options.vibrancy = 'sidebar';
    options.visualEffectState = 'active';
    options.backgroundColor = '#00000000';
  } else if (process.platform === 'win32') {
    options.titleBarStyle = 'hidden';
    options.titleBarOverlay = {
      color: palette.background,
      symbolColor: palette.symbol,
      height: TITLEBAR_HEIGHT,
    };
  }

  mainWindow = new BrowserWindow(options);

  mainWindow.once('ready-to-show', () => {
    if (saved?.maximized) mainWindow.maximize();
    mainWindow.show();
  });

  mainWindow.on('resize', saveWindowState);
  mainWindow.on('move', saveWindowState);
  mainWindow.on('close', saveWindowState);
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'),
    START_MODE ? { query: { mode: START_MODE } } : undefined);
  return mainWindow;
}

function applyTheme(theme) {
  nativeTheme.themeSource = ['light', 'dark'].includes(theme) ? theme : 'system';
  const palette = chrome();
  if (mainWindow && process.platform !== 'darwin') {
    try {
      mainWindow.setBackgroundColor(palette.background);
    } catch {
      /* ignore */
    }
    if (process.platform === 'win32' && typeof mainWindow.setTitleBarOverlay === 'function') {
      try {
        mainWindow.setTitleBarOverlay({
          color: palette.background,
          symbolColor: palette.symbol,
          height: TITLEBAR_HEIGHT,
        });
      } catch {
        /* ignore */
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Python engine
// ---------------------------------------------------------------------------

function engineInfo() {
  const python = resolvePython();
  return {
    found: Boolean(python),
    path: python,
    candidates: pythonCandidates(),
    projectRoot: PROJECT_ROOT,
    error: engineError ? String(engineError.message || engineError) : null,
  };
}

async function ensureEngine() {
  if (engine && engine.running && engine.ready) return engine;
  engineError = null;
  engine = new PythonBridge({ python: resolvePython() });
  engine.on('stderr', (text) => process.stderr.write(`[engine] ${text}`));
  engine.on('protocol-error', (line) => process.stderr.write(`[engine] non-protocol output: ${line}\n`));
  engine.start();
  await engine.hello();
  return engine;
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------

function registerIpc() {
  ipcMain.handle('app:info', () => ({
    name: 'EasyFig',
    platform: process.platform,
    versions: {
      electron: process.versions.electron,
      chrome: process.versions.chrome,
      node: process.versions.node,
    },
    theme: nativeTheme.themeSource,
    dark: nativeTheme.shouldUseDarkColors,
    titlebarHeight: TITLEBAR_HEIGHT,
    python: engineInfo(),
  }));

  ipcMain.handle('bridge:request', async (_event, cmd, payload) => {
    const instance = await ensureEngine();
    return instance.request(cmd, payload || {});
  });

  ipcMain.handle('theme:set', (_event, theme) => {
    applyTheme(theme);
    return { theme: nativeTheme.themeSource, dark: nativeTheme.shouldUseDarkColors };
  });

  ipcMain.handle('shell:openExternal', (_event, url) => {
    if (typeof url === 'string' && /^https?:\/\//i.test(url)) shell.openExternal(url);
    return true;
  });

  ipcMain.handle('shell:reveal', (_event, target) => {
    if (typeof target === 'string' && target) shell.showItemInFolder(target);
    return true;
  });

  ipcMain.handle('dialog:openTable', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Import a table',
      properties: ['openFile'],
      filters: [
        { name: 'Tables', extensions: ['csv', 'tsv', 'txt', 'xlsx', 'xlsm', 'xls'] },
        { name: 'All files', extensions: ['*'] },
      ],
    });
    if (result.canceled || !result.filePaths.length) return null;
    return result.filePaths[0];
  });

  ipcMain.handle('dialog:openMultiline', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Import multi-line files',
      properties: ['openFile', 'multiSelections'],
      filters: [
        { name: 'Tables', extensions: ['csv', 'tsv', 'txt', 'xlsx', 'xlsm', 'xls'] },
        { name: 'All files', extensions: ['*'] },
      ],
    });
    if (result.canceled || !result.filePaths.length) return null;
    return result.filePaths;
  });

  ipcMain.handle('dialog:saveFigure', async (_event, options = {}) => {
    const result = await dialog.showSaveDialog(mainWindow, {
      title: 'Export figure',
      defaultPath: options.defaultPath || 'easyfig.png',
      filters: [
        { name: 'PNG image', extensions: ['png'] },
        { name: 'PDF document', extensions: ['pdf'] },
        { name: 'SVG vector', extensions: ['svg'] },
        { name: 'JPEG image', extensions: ['jpg', 'jpeg'] },
        { name: 'TIFF image', extensions: ['tif', 'tiff'] },
      ],
    });
    if (result.canceled || !result.filePath) return null;
    return result.filePath;
  });
}

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------

function buildMenu() {
  const isMac = process.platform === 'darwin';
  const send = (channel, payload) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload);
  };

  const template = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { label: 'Preferences...', accelerator: 'Cmd+,', click: () => send('menu:focus-inspector') },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    }] : []),
    {
      label: 'File',
      submenu: [
        { label: 'Import Table...', accelerator: 'CmdOrCtrl+O', click: () => send('menu:import-table') },
        { label: 'Import Multi-Line...', accelerator: 'CmdOrCtrl+Shift+O', click: () => send('menu:import-multiline') },
        { type: 'separator' },
        { label: 'Export Figure...', accelerator: 'CmdOrCtrl+S', click: () => send('menu:export') },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { label: 'Refresh Preview', accelerator: 'CmdOrCtrl+R', click: () => send('menu:refresh') },
        { type: 'separator' },
        { label: 'Light Appearance', click: () => send('menu:theme', 'light') },
        { label: 'Dark Appearance', click: () => send('menu:theme', 'dark') },
        { label: 'Match System', click: () => send('menu:theme', 'system') },
        { type: 'separator' },
        { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { role: 'toggleDevTools' },
      ],
    },
    { role: 'windowMenu' },
    {
      role: 'help',
      submenu: [
        { label: 'EasyFig on the command line', click: () => send('menu:about-cli') },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------------------
// Smoke test
// ---------------------------------------------------------------------------

/** Dump element geometry so layout problems can be diagnosed without guessing. */
const PROBE_SCRIPT = `(() => {
  const rect = (selector) => {
    const node = document.querySelector(selector);
    if (!node) return null;
    const box = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return {
      top: Math.round(box.top), bottom: Math.round(box.bottom),
      left: Math.round(box.left), right: Math.round(box.right),
      w: Math.round(box.width), h: Math.round(box.height),
      display: style.display, rows: style.gridTemplateRows, overflow: style.overflow,
    };
  };
  return JSON.stringify({
    viewport: { w: window.innerWidth, h: window.innerHeight },
    body: rect('body'),
    titlebar: rect('.titlebar'),
    workspace: rect('.workspace'),
    sidebar: rect('.sidebar'),
    stage: rect('.stage'),
    stageToolbar: rect('.stage__toolbar'),
    canvasArea: rect('.canvas-area'),
    canvasFrame: rect('#canvasFrame'),
    stats: rect('#statsPanel'),
    statsBody: rect('#statsBody'),
    inspector: rect('.inspector'),
    statusbar: rect('.statusbar'),
  }, null, 2);
})()`;

async function runProbe() {
  try {
    const json = await mainWindow.webContents.executeJavaScript(PROBE_SCRIPT, true);
    process.stdout.write(`${json}\n`);
    app.exit(0);
  } catch (error) {
    process.stderr.write(`probe: ${error.message}\n`);
    app.exit(1);
  }
}

function runSmoke() {
  const timeout = setTimeout(() => {
    process.stderr.write('smoke: timed out waiting for the first render\n');
    app.exit(1);
  }, 120000);

  ipcMain.once('app:rendered', async () => {
    clearTimeout(timeout);
    if (PROBE) {
      await runProbe();
      return;
    }
    try {
      fs.mkdirSync(path.dirname(SHOT_PATH), { recursive: true });
      // Give the interface a moment to finish painting the preview.
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const image = await mainWindow.webContents.capturePage();
      fs.writeFileSync(SHOT_PATH, image.toPNG());
      process.stdout.write(`smoke: ok ${SHOT_PATH}\n`);
      app.exit(0);
    } catch (error) {
      process.stderr.write(`smoke: ${error.message}\n`);
      app.exit(1);
    }
  });
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

if (!app.requestSingleInstanceLock() && !SMOKE) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    registerIpc();
    buildMenu();
    createWindow();

    // Warm the engine up so the first render is instant.
    ensureEngine()
      .then(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('engine:ready');
        }
      })
      .catch((error) => {
        engineError = error;
        process.stderr.write(`engine: ${error.message}\n`);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('engine:error', { message: error.message });
        }
      });

    if (SMOKE || PROBE) runSmoke();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin' || SMOKE) app.quit();
  });

  app.on('before-quit', () => {
    if (engine) engine.dispose();
  });
}
