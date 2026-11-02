Intake Autopilot -- lock service ports to this PC -- 2026-10-26
================================================================
WHY
  The containers publish their ports to the WHOLE network (all of 0.0.0.0):
    5432 database (all client data, default password)   5678 n8n   8000 AI service
    8080 backend   11434 Ollama
  The AI-service log already shows automated scanners probing it. After this change each
  port answers only on this PC (127.0.0.1). The dashboard, n8n, the questionnaire at
  http://localhost:8080/fragebogen and our Tailscale/SSH access all keep working -- they
  run on / connect through this PC. Containers still talk to each other as before.

WHAT IT CHANGES
  Only the "ports:" lines in docker-compose.yml / docker-compose.override.yml:
     - "5432:5432"   ->   - "127.0.0.1:5432:5432"
  Nothing else in either file is touched (the office's own settings stay exactly as they
  are). Backups: docker-compose.yml.pre-ports-2026-10-26 (and .override... if changed).
  No data is touched: the database, n8n and model data live in volumes/folders that a
  container re-create keeps.

STEPS (PowerShell, in this folder)
 1. Check nothing on ANOTHER device uses these ports right now (should print nothing):
      Get-NetTCPConnection -State Established -LocalPort 5432,5678,8000,8080,11434 -ErrorAction SilentlyContinue | Where-Object { $_.RemoteAddress -notin '127.0.0.1','::1' } | Select-Object LocalPort, RemoteAddress
    Also ask the office: does anyone open the dashboard or the questionnaire from ANOTHER
    computer or a phone via this PC's address? If yes -- stop and tell us first.
 2. Preview (changes nothing):
      powershell -ExecutionPolicy Bypass -File .\lock_ports.ps1
 3. Apply:
      powershell -ExecutionPolicy Bypass -File .\lock_ports.ps1 -Apply
 4. Activate (re-creates the containers with the new port setting, ~30 s):
      cd "C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2"
      docker compose up -d
 5. Verify -- every port must start with 127.0.0.1:
      docker ps --format "{{.Names}}  {{.Ports}}"
    and: docker logs --tail 5 intake-backend  -> no "MOCK MODE"; dashboard loads.

ROLLBACK
  In the deploy folder:
      Copy-Item -LiteralPath docker-compose.yml.pre-ports-2026-10-26 -Destination docker-compose.yml -Force
      (same for docker-compose.override.yml.pre-ports-2026-10-26 if it exists)
      docker compose up -d

NOT IN THIS CHANGE
  - The database password is still the default ("password"). With the port locked it is
    no longer reachable from the network; changing it is a separate, careful step.
  - Windows Firewall rules are not changed.
