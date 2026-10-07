module.exports = {
  apps: [{
    name: "autodraft-backend",
    script: "run.py",
    interpreter: "python3",
    cwd: __dirname,
    env: { HOST: "127.0.0.1", PORT: 3001, PYTHONUNBUFFERED: "1" },
    instances: 1,
    autorestart: true,
    watch: false,
    max_restarts: 10,
    restart_delay: 5000,
    max_memory_restart: "1G",
  }],
};
