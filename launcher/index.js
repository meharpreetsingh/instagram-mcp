'use strict';

const path = require('path');
const spawn = require('cross-spawn');
const fs = require('fs');

function startServer(options = {}) {
  const serverPath = path.join(__dirname, '../src/server.py');

  if (!fs.existsSync(serverPath)) {
    console.error('Error: src/server.py not found');
    process.exit(1);
  }

  const env = { ...process.env };
  if (options.sessionId) env.INSTAGRAM_SESSION_ID = options.sessionId;
  if (options.csrfToken) env.INSTAGRAM_CSRF_TOKEN = options.csrfToken;
  if (options.dsUserId) env.INSTAGRAM_DS_USER_ID = options.dsUserId;

  for (const bin of ['python3', 'python']) {
    try {
      const result = spawn.sync(bin, [serverPath], { stdio: 'inherit', env });
      if (!result.error) return { status: result.status };
      if (result.error.code !== 'ENOENT') {
        console.error(`Error starting server with ${bin}: ${result.error.message}`);
        return { status: result.status || 1, error: result.error };
      }
    } catch (err) {
      console.error(`Unexpected error with ${bin}: ${err.message}`);
    }
  }

  console.error('Could not find python3 or python');
  return { status: 1 };
}

module.exports = { startServer };

if (require.main === module) {
  const { status } = startServer();
  process.exit(status || 0);
}
