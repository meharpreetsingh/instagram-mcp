#!/usr/bin/env node
'use strict';

// Auto-load .env from project root before anything else reads process.env
require('dotenv').config({ path: require('path').join(__dirname, '../.env'), override: true });

const { program } = require('commander');
const inquirer = require('inquirer');
const chalk = require('chalk');
const { startServer } = require('./index');
const fs = require('fs');
const path = require('path');
const os = require('os');

const pkg = require('../package.json');
const CLI_PATH = path.resolve(__filename);

// ── LLM target registry ────────────────────────────────────────────────────────
// Add a new entry here to support another LLM tool. serverKey is the top-level
// JSON key under which MCP servers are listed. entryShape returns the full entry
// object for that LLM's expected config format.

const LLM_CONFIGS = {
  claude: {
    label: 'Claude Desktop',
    configPath: () => path.join(os.homedir(), 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json'),
    serverKey: 'mcpServers',
    entryShape: (cliPath, creds) => ({
      command: 'node',
      args: [cliPath, 'start'],
      env: creds ? {
        INSTAGRAM_SESSION_ID: creds.sessionId,
        INSTAGRAM_CSRF_TOKEN: creds.csrfToken,
        INSTAGRAM_DS_USER_ID: creds.dsUserId,
      } : {},
    }),
  },
  cursor: {
    label: 'Cursor',
    configPath: () => path.join(os.homedir(), '.cursor', 'mcp.json'),
    serverKey: 'mcpServers',
    entryShape: (cliPath, creds) => ({
      command: 'node',
      args: [cliPath, 'start'],
      env: creds ? {
        INSTAGRAM_SESSION_ID: creds.sessionId,
        INSTAGRAM_CSRF_TOKEN: creds.csrfToken,
        INSTAGRAM_DS_USER_ID: creds.dsUserId,
      } : {},
    }),
  },
  windsurf: {
    label: 'Windsurf',
    configPath: () => path.join(os.homedir(), '.codeium', 'windsurf', 'mcp_config.json'),
    serverKey: 'mcpServers',
    entryShape: (cliPath, creds) => ({
      command: 'node',
      args: [cliPath, 'start'],
      env: creds ? {
        INSTAGRAM_SESSION_ID: creds.sessionId,
        INSTAGRAM_CSRF_TOKEN: creds.csrfToken,
        INSTAGRAM_DS_USER_ID: creds.dsUserId,
      } : {},
    }),
  },
  zed: {
    label: 'Zed',
    // Zed uses context_servers, not mcpServers, and has a different shape
    configPath: () => path.join(os.homedir(), '.config', 'zed', 'settings.json'),
    serverKey: 'context_servers',
    entryShape: (cliPath, creds) => ({
      command: {
        path: 'node',
        args: [cliPath, 'start'],
        env: creds ? {
          INSTAGRAM_SESSION_ID: creds.sessionId,
          INSTAGRAM_CSRF_TOKEN: creds.csrfToken,
          INSTAGRAM_DS_USER_ID: creds.dsUserId,
        } : {},
      },
    }),
  },
};

// ── Shared helpers ─────────────────────────────────────────────────────────────

function _credentialOptions(cmd) {
  return cmd
    .option('-s, --session-id <id>', 'Instagram session ID')
    .option('-c, --csrf-token <token>', 'Instagram CSRF token')
    .option('-d, --ds-user-id <id>', 'Instagram DS user ID')
    .option('--from-file <path>', 'Load credentials from a JSON file');
}

async function _resolveCredentials(options, { interactive = false } = {}) {
  const envSessionId = process.env.INSTAGRAM_SESSION_ID;
  const envCsrfToken = process.env.INSTAGRAM_CSRF_TOKEN;
  const envDsUserId = process.env.INSTAGRAM_DS_USER_ID;

  if (envSessionId && envCsrfToken && envDsUserId) {
    console.error(chalk.green('Using credentials from environment / .env'));
    return { sessionId: envSessionId, csrfToken: envCsrfToken, dsUserId: envDsUserId };
  }

  if (options.sessionId && options.csrfToken && options.dsUserId) {
    console.error(chalk.green('Using credentials from CLI flags'));
    return { sessionId: options.sessionId, csrfToken: options.csrfToken, dsUserId: options.dsUserId };
  }

  if (options.fromFile) {
    return _loadCredentialsFromFile(options.fromFile);
  }

  if (interactive) {
    const answers = await inquirer.prompt([
      { type: 'input', name: 'sessionId', message: 'Instagram Session ID:', validate: v => v.trim() !== '' },
      { type: 'input', name: 'csrfToken', message: 'Instagram CSRF Token:', validate: v => v.trim() !== '' },
      { type: 'input', name: 'dsUserId', message: 'Instagram DS User ID:', validate: v => v.trim() !== '' },
      { type: 'confirm', name: 'saveToFile', message: 'Save credentials to .env?', default: false },
    ]);
    if (answers.saveToFile) {
      _saveEnvFile({ sessionId: answers.sessionId, csrfToken: answers.csrfToken, dsUserId: answers.dsUserId });
    }
    return { sessionId: answers.sessionId, csrfToken: answers.csrfToken, dsUserId: answers.dsUserId };
  }

  return null;
}

function _loadCredentialsFromFile(filePath) {
  try {
    const raw = JSON.parse(fs.readFileSync(path.resolve(filePath), 'utf8'));
    return {
      sessionId: raw.sessionid || raw.sessionId || raw.INSTAGRAM_SESSION_ID,
      csrfToken: raw.csrftoken || raw.csrfToken || raw.INSTAGRAM_CSRF_TOKEN,
      dsUserId: raw.ds_user_id || raw.dsUserId || raw.INSTAGRAM_DS_USER_ID,
    };
  } catch (err) {
    console.error(chalk.red(`Error loading credentials from file: ${err.message}`));
    process.exit(1);
  }
}

function _saveEnvFile(credentials) {
  const envPath = path.join(__dirname, '../.env');
  const content = [
    `INSTAGRAM_SESSION_ID=${credentials.sessionId}`,
    `INSTAGRAM_CSRF_TOKEN=${credentials.csrfToken}`,
    `INSTAGRAM_DS_USER_ID=${credentials.dsUserId}`,
  ].join('\n') + '\n';
  try {
    fs.writeFileSync(envPath, content);
    console.error(chalk.green(`Credentials saved to ${envPath}`));
  } catch (err) {
    console.error(chalk.red(`Error saving .env: ${err.message}`));
  }
}

function _installForLlm(llmKey, credentials) {
  const llmConfig = LLM_CONFIGS[llmKey];
  const configPath = llmConfig.configPath();
  const dir = path.dirname(configPath);

  // Create parent directory if it doesn't exist (e.g. ~/.cursor/)
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  let config = {};
  if (fs.existsSync(configPath)) {
    try {
      config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (err) {
      console.error(chalk.red(`Could not parse ${configPath}: ${err.message}`));
      process.exit(1);
    }
  }

  config[llmConfig.serverKey] = config[llmConfig.serverKey] || {};
  config[llmConfig.serverKey]['InstagramDM'] = llmConfig.entryShape(CLI_PATH, credentials);

  try {
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
    console.error(chalk.green(`${llmConfig.label} config updated: ${configPath}`));
    console.error(chalk.blue(`Command: node ${CLI_PATH} start`));
  } catch (err) {
    console.error(chalk.red(`Failed to write config: ${err.message}`));
    process.exit(1);
  }
}

// ── start ──────────────────────────────────────────────────────────────────────

const startCmd = program
  .command('start')
  .description('Start the Instagram DM MCP server');

_credentialOptions(startCmd);

startCmd.action(async (options) => {
  const credentials = await _resolveCredentials(options, { interactive: true });
  console.error(chalk.blue('Starting Instagram DM MCP server...'));
  const result = startServer(credentials || {});
  if (result.status !== 0) {
    console.error(chalk.red(`Server exited with code ${result.status}`));
    process.exit(result.status);
  }
});

// ── <llm> install subcommands ──────────────────────────────────────────────────

function _registerLlmCommand(llmKey) {
  const llmConfig = LLM_CONFIGS[llmKey];
  const llmCmd = program
    .command(llmKey)
    .description(`Manage MCP integration for ${llmConfig.label}`);

  const installCmd = llmCmd
    .command('install')
    .description(`Register this server in ${llmConfig.label} config`);

  _credentialOptions(installCmd);

  installCmd.action(async (options) => {
    console.error(chalk.blue(`Installing Instagram DM MCP server for ${llmConfig.label}...`));
    const credentials = await _resolveCredentials(options, { interactive: false });
    _installForLlm(llmKey, credentials);
  });
}

Object.keys(LLM_CONFIGS).forEach(_registerLlmCommand);

// ── parse ──────────────────────────────────────────────────────────────────────

program
  .version(pkg.version)
  .description(pkg.description);

program.parse(process.argv);

if (!process.argv.slice(2).length) {
  program.outputHelp();
}
