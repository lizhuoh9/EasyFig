'use strict';

/**
 * The only bridge between the interface and Node/Electron.
 *
 * Everything the renderer can reach is listed here explicitly; there is no
 * `require`, no filesystem access and no raw IPC channel, so a bug in the
 * interface cannot reach outside the window.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('easyfig', {
  /** Static facts about the host: platform, versions, engine location. */
  info: () => ipcRenderer.invoke('app:info'),

  /** One call into the Python chart engine. */
  request: (cmd, payload) => ipcRenderer.invoke('bridge:request', cmd, payload || {}),

  /** Native file dialogs. */
  openTable: () => ipcRenderer.invoke('dialog:openTable'),
  openMultiline: () => ipcRenderer.invoke('dialog:openMultiline'),
  saveFigure: (options) => ipcRenderer.invoke('dialog:saveFigure', options || {}),

  /** Appearance. */
  setTheme: (theme) => ipcRenderer.invoke('theme:set', theme),

  /** Shell integration. */
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  reveal: (target) => ipcRenderer.invoke('shell:reveal', target),

  /** Engine lifecycle notices from the main process. */
  onEngineReady: (callback) => {
    const handler = () => callback();
    ipcRenderer.on('engine:ready', handler);
    return () => ipcRenderer.removeListener('engine:ready', handler);
  },
  onEngineError: (callback) => {
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on('engine:error', handler);
    return () => ipcRenderer.removeListener('engine:error', handler);
  },

  /** Menu commands. */
  onMenu: (callback) => {
    const channels = [
      'menu:import-table', 'menu:import-multiline', 'menu:export',
      'menu:refresh', 'menu:focus-inspector', 'menu:about-cli',
    ];
    const handlers = channels.map((channel) => {
      const handler = () => callback(channel.replace('menu:', ''));
      ipcRenderer.on(channel, handler);
      return () => ipcRenderer.removeListener(channel, handler);
    });
    const themeHandler = (_event, theme) => callback('theme', theme);
    ipcRenderer.on('menu:theme', themeHandler);
    handlers.push(() => ipcRenderer.removeListener('menu:theme', themeHandler));
    return () => handlers.forEach((dispose) => dispose());
  },

  /** Told to the main process once the first figure has painted. */
  signalRendered: () => ipcRenderer.send('app:rendered'),
});
