#!/usr/bin/env node

/**
 * Cross-platform launcher for ONYX: The Cobalt Scarab.
 *
 * Responsibilities:
 *   1. Locate a working Python 3 interpreter on macOS, Windows, or Linux.
 *   2. Create a local .venv inside the project root if one doesn't exist.
 *   3. Install the onyx_vault package (pyproject.toml) into that venv, once.
 *   4. Forward all CLI args through to `python -m onyx_vault`.
 */

"use strict";

const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawnSync, spawn } = require("child_process");

const ROOT_DIR = path.resolve(__dirname, "..");
const VENV_DIR = path.join(ROOT_DIR, ".venv");
const IS_WIN = process.platform === "win32";

const VENV_PYTHON = IS_WIN
  ? path.join(VENV_DIR, "Scripts", "python.exe")
  : path.join(VENV_DIR, "bin", "python");

const DEPS_MARKER = path.join(VENV_DIR, ".deps_installed");
const PYPROJECT = path.join(ROOT_DIR, "pyproject.toml");

function log(msg) {
  console.log(`[onyx] ${msg}`);
}

function err(msg) {
  console.error(`[onyx] ${msg}`);
}

/** Try a list of candidate commands, return the first that reports a usable Python 3. */
function findSystemPython() {
  const candidates = IS_WIN
    ? [["python", []], ["py", ["-3"]], ["python3", []]]
    : [["python3", []], ["python", []]];

  for (const [cmd, baseArgs] of candidates) {
    const result = spawnSync(cmd, [...baseArgs, "--version"], {
      encoding: "utf8",
      shell: false,
    });
    if (result.status === 0) {
      const versionStr = (result.stdout || result.stderr || "").trim();
      const match = versionStr.match(/Python (\d+)\.(\d+)/);
      if (match && parseInt(match[1], 10) >= 3 && parseInt(match[2], 10) >= 9) {
        return { cmd, baseArgs, versionStr };
      }
      if (match && parseInt(match[1], 10) >= 3) {
        // Python 3.x present but older than 3.9 — still return it, main.py
        // requirements will surface a clearer error if something breaks.
        return { cmd, baseArgs, versionStr };
      }
    }
  }
  return null;
}

function ensureVenv(systemPython) {
  if (fs.existsSync(VENV_PYTHON)) {
    return;
  }
  log("No virtual environment found. Creating one at .venv (first run only)...");
  const result = spawnSync(
    systemPython.cmd,
    [...systemPython.baseArgs, "-m", "venv", VENV_DIR],
    { stdio: "inherit" }
  );
  if (result.status !== 0) {
    err("Failed to create the Python virtual environment. See output above.");
    process.exit(result.status || 1);
  }
}

function needsInstall() {
  if (!fs.existsSync(DEPS_MARKER)) return true;
  try {
    const markerTime = fs.statSync(DEPS_MARKER).mtimeMs;
    const pyprojectTime = fs.statSync(PYPROJECT).mtimeMs;
    return pyprojectTime > markerTime;
  } catch {
    return true;
  }
}

function installDeps() {
  log("Installing dependencies into .venv (this only happens once, or after updates)...");
  const result = spawnSync(VENV_PYTHON, ["-m", "pip", "install", "--quiet", "--upgrade", "pip"], {
    stdio: "inherit",
    cwd: ROOT_DIR,
  });
  if (result.status !== 0) {
    err("Failed to upgrade pip inside the virtual environment.");
    process.exit(result.status || 1);
  }

  const install = spawnSync(VENV_PYTHON, ["-m", "pip", "install", "--quiet", "-e", "."], {
    stdio: "inherit",
    cwd: ROOT_DIR,
  });
  if (install.status !== 0) {
    err("Failed to install onyx-vault's Python dependencies. See output above.");
    err(
      "If this mentions PyAudio, you may need PortAudio installed first " +
        "(e.g. `brew install portaudio` on macOS, or the prebuilt PyAudio wheel on Windows)."
    );
    process.exit(install.status || 1);
  }

  fs.writeFileSync(DEPS_MARKER, new Date().toISOString());
  log("Dependencies installed.");
}

function forwardToPython(args) {
  const child = spawn(VENV_PYTHON, ["-m", "onyx_vault", ...args], {
    stdio: "inherit",
    cwd: ROOT_DIR,
    env: {
      ...process.env,
      // Force UTF-8 I/O regardless of the host console's codepage, so ONYX's
      // emoji-heavy persona output renders correctly on legacy Windows terminals.
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
    },
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      // Re-raise the same signal so the parent shell reports it consistently
      // across platforms (mainly relevant for Ctrl+C / SIGINT).
      process.exit(1);
    }
    process.exit(code === null ? 1 : code);
  });

  // Let the child handle SIGINT itself (graceful shutdown / Map-Reduce pass);
  // just make sure this wrapper doesn't die before the child does.
  process.on("SIGINT", () => {});
}

function main() {
  const args = process.argv.slice(2);

  const systemPython = findSystemPython();
  if (!systemPython) {
    err("Python 3.9+ is required but wasn't found on your PATH.");
    err(
      IS_WIN
        ? "Install it from https://www.python.org/downloads/ or `winget install Python.Python.3.11`."
        : "Install it via your system package manager or https://www.python.org/downloads/."
    );
    process.exit(1);
  }

  ensureVenv(systemPython);

  if (needsInstall()) {
    installDeps();
  }

  forwardToPython(args);
}

main();
