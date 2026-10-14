'use strict';

/**
 * Manages the Python chart engine as a child process.
 *
 * The engine speaks line-delimited JSON on stdin/stdout (see
 * `easyfig/bridge.py`).  This class owns the process, correlates responses with
 * requests by id, and rejects every pending promise if the process dies so the
 * interface never hangs.
 */

const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_TIMEOUT_MS = 120000;

/** Candidate interpreters, most specific first. */
function pythonCandidates() {
  const candidates = [];
  const push = (value) => {
    if (value && !candidates.includes(value)) candidates.push(value);
  };

  push(process.env.EASYFIG_PYTHON);
  // A copy of the interpreter next to the app (packaged builds).
  if (process.resourcesPath) {
    push(path.join(process.resourcesPath, 'python', 'python.exe'));
    push(path.join(process.resourcesPath, 'python', 'bin', 'python3'));
  }
  // The project's materialised conda environment.
  push(path.join(PROJECT_ROOT, '.conda-env', 'python.exe'));
  push(path.join(PROJECT_ROOT, '.conda-env', 'bin', 'python3'));
  push(path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe'));
  push(path.join(PROJECT_ROOT, '.venv', 'bin', 'python3'));
  // Whatever is on PATH.
  push(process.platform === 'win32' ? 'python.exe' : 'python3');
  push('python');
  return candidates;
}

function isExecutable(candidate) {
  if (!candidate) return false;
  if (candidate === 'python' || candidate === 'python3' || candidate === 'python.exe') {
    return true; // resolved through PATH by spawn
  }
  try {
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

/** First plausible interpreter, or null when nothing looks usable. */
function resolvePython() {
  const candidates = pythonCandidates();
  for (const candidate of candidates) {
    if (isExecutable(candidate)) return candidate;
  }
  return null;
}

class PythonBridge extends EventEmitter {
  constructor(options = {}) {
    super();
    this.python = options.python || resolvePython();
    this.cwd = options.cwd || PROJECT_ROOT;
    this.timeout = options.timeout || DEFAULT_TIMEOUT_MS;
    this.child = null;
    this.pending = new Map();
    this.nextId = 1;
    this.buffer = '';
    this.stderrTail = [];
    this.stopping = false;
    this.ready = false;
  }

  get running() {
    return Boolean(this.child && this.child.exitCode === null && !this.child.killed);
  }

  start() {
    if (this.child) return this.child;
    if (!this.python) {
      const error = new Error(
        'No Python interpreter found. Set EASYFIG_PYTHON or install the project '
        + 'environment (.conda-env) next to the app.',
      );
      error.candidates = pythonCandidates();
      throw error;
    }

    // PYTHONPATH makes `-m easyfig.bridge` work regardless of the working dir.
    const env = {
      ...process.env,
      PYTHONPATH: [this.cwd, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    };
    // Inherited Electron flags must not leak into the interpreter.
    delete env.ELECTRON_RUN_AS_NODE;

    this.child = spawn(this.python, ['-m', 'easyfig.bridge'], {
      cwd: this.cwd,
      env,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', (chunk) => this._onStdout(chunk));

    this.child.stderr.setEncoding('utf8');
    this.child.stderr.on('data', (chunk) => {
      const text = String(chunk);
      this.stderrTail.push(text);
      if (this.stderrTail.length > 40) this.stderrTail.shift();
      this.emit('stderr', text);
    });

    this.child.on('error', (error) => {
      this._failAll(new Error(`Cannot start the Python engine: ${error.message}`));
    });

    this.child.on('exit', (code, signal) => {
      const detail = this.stderrTail.join('').trim().split('\n').slice(-6).join('\n');
      const reason = this.stopping
        ? 'The Python engine stopped.'
        : `The Python engine exited unexpectedly (code ${code}${signal ? `, signal ${signal}` : ''}).`
          + (detail ? `\n${detail}` : '');
      this.child = null;
      this.ready = false;
      this._failAll(new Error(reason));
      this.emit('exit', { code, signal });
    });

    return this.child;
  }

  _onStdout(chunk) {
    this.buffer += chunk;
    let index = this.buffer.indexOf('\n');
    while (index !== -1) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (line) this._onLine(line);
      index = this.buffer.indexOf('\n');
    }
  }

  _onLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.emit('protocol-error', line);
      return;
    }
    const entry = this.pending.get(message.id);
    if (!entry) {
      this.emit('orphan', message);
      return;
    }
    this.pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.ok) {
      entry.resolve(message.result);
    } else {
      const error = new Error(message.error?.message || 'The Python engine reported an error.');
      error.kind = message.error?.kind || 'error';
      error.traceback = message.error?.traceback;
      entry.reject(error);
    }
  }

  _failAll(error) {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    this.pending.clear();
  }

  /** Send one request and resolve with its result. */
  request(cmd, payload = {}, options = {}) {
    if (!this.running) this.start();

    const id = this.nextId++;
    const message = JSON.stringify({ id, cmd, ...payload });
    const timeout = options.timeout || this.timeout;

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        const error = new Error(
          `The Python engine did not answer "${cmd}" within ${Math.round(timeout / 1000)}s.`,
        );
        error.kind = 'timeout';
        reject(error);
      }, timeout);

      this.pending.set(id, { resolve, reject, timer });

      try {
        this.child.stdin.write(`${message}\n`);
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  /** Handshake used to prove the engine is alive and to fetch the schema. */
  async hello() {
    const schema = await this.request('hello', {}, { timeout: 30000 });
    this.ready = true;
    return schema;
  }

  dispose() {
    this.stopping = true;
    if (!this.child) return;
    try {
      this.child.stdin.write(`${JSON.stringify({ id: this.nextId++, cmd: 'shutdown' })}\n`);
    } catch {
      /* the process is already gone */
    }
    const child = this.child;
    setTimeout(() => {
      if (child.exitCode === null) child.kill();
    }, 800).unref?.();
  }
}

module.exports = { PythonBridge, resolvePython, pythonCandidates, PROJECT_ROOT };
