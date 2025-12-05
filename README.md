# Git Mirror

A Docker-based application to synchronize Git repositories. This tool allows you to set up one-way mirroring from a source repository to a destination repository with a web-based UI for configuration.

## Features

- **One-way sync**: Mirror repositories from source to destination
- **Web UI**: Easy-to-use interface for managing repository pairs
- **Scheduled sync**: Automatic synchronization at configurable intervals
- **Multiple pairs**: Manage multiple source/destination repository pairs
- **Authentication support**: HTTP(S) with username/password or SSH keys
- **Branch filtering**: Sync all branches or select specific ones
- **Tag syncing**: Optionally sync tags along with branches
- **Sync logs**: View detailed logs for each sync operation
- **Retry mechanism**: Automatic retries on failure

## Quick Start

### Prerequisites

- Docker
- Docker Compose

### Running the Application

1. Clone or download this repository

2. Start the application:
   ```bash
   docker-compose up -d
   ```

3. Open your browser and navigate to:
   ```
   http://localhost:8080
   ```

4. Add your first repository pair using the Web UI

### Stopping the Application

```bash
docker-compose down
```

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Backend only
docker-compose logs -f backend

# Frontend only
docker-compose logs -f frontend
```

## Configuration

### Adding a Repository Pair

1. Click "Add Pair" in the Repo Pairs section
2. Fill in the details:
   - **Name**: A friendly name for this sync pair
   - **Source URL**: The repository to sync FROM
   - **Destination URL**: The repository to sync TO
   - **Sync Interval**: How often to sync (in minutes)
   - **Branches**: Which branches to sync (`*` for all)
   - **Sync Tags**: Whether to include tags

### Authentication

#### HTTPS with Username/Password (or Token)

For GitHub, GitLab, etc., you can use a personal access token as the password:

- Username: Your username
- Password: Your personal access token

#### SSH Keys

Paste your private SSH key in the SSH Key field. Make sure the corresponding public key is added to your Git hosting service.

### Global Settings

- **Default Sync Interval**: Default interval for new pairs
- **Max Concurrent Syncs**: How many syncs can run simultaneously
- **Retry on Failure**: Whether to retry failed syncs
- **Retry Count**: Number of retry attempts

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │
│    Frontend     │────▶│    Backend      │
│    (nginx)      │     │   (FastAPI)     │
│    Port 8080    │     │                 │
│                 │     │                 │
└─────────────────┘     └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │                 │
                        │   Git Repos     │
                        │   (local clone) │
                        │                 │
                        └─────────────────┘
```

### Components

- **Frontend**: Static HTML/JS served by nginx, proxies API calls to backend
- **Backend**: FastAPI application handling:
  - REST API for configuration
  - Git sync operations
  - Scheduler for automatic syncing
  - Persistent storage for configuration

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/repo-pairs` | List all repository pairs |
| POST | `/api/repo-pairs` | Create a new pair |
| GET | `/api/repo-pairs/{id}` | Get pair details |
| PUT | `/api/repo-pairs/{id}` | Update a pair |
| DELETE | `/api/repo-pairs/{id}` | Delete a pair |
| POST | `/api/repo-pairs/{id}/sync` | Trigger immediate sync |
| GET | `/api/repo-pairs/{id}/logs` | Get sync logs |
| GET | `/api/config` | Get global config |
| PUT | `/api/config` | Update global config |
| GET | `/api/stats` | Get statistics |

## Data Persistence

All data is stored in Docker volumes:
- `git-mirror-data`: SQLite database and configuration
- `git-mirror-work`: Working directory for git operations

To backup your configuration:
```bash
docker run --rm -v git-mirror_git-mirror-data:/data -v $(pwd):/backup alpine tar cvf /backup/git-mirror-backup.tar /data
```

## Database

By default, Git Mirror uses **SQLite** for data storage. The database file is stored at `/data/git_mirror.db` inside the container.

### Upgrading to PostgreSQL

For production environments or higher scalability, you can switch to PostgreSQL:

1. Add a PostgreSQL service to `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: git-mirror-postgres
    environment:
      - POSTGRES_USER=gitmirror
      - POSTGRES_PASSWORD=your_secure_password
      - POSTGRES_DB=git_mirror
    volumes:
      - git-mirror-postgres:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - git-mirror-network

volumes:
  git-mirror-postgres:
    driver: local
```

2. Update the backend service environment in `docker-compose.yml`:

```yaml
  backend:
    environment:
      - DATABASE_URL=postgresql://gitmirror:your_secure_password@postgres:5432/git_mirror
```

3. Add `psycopg2-binary` to `backend/requirements.txt`:

```
psycopg2-binary==2.9.9
```

4. Rebuild and restart the services:

```bash
docker-compose build backend
docker-compose up -d
```

**Note**: When switching databases, existing data from SQLite will not be automatically migrated. You may need to manually export/import your repository pairs.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | `/data` | Directory for configuration storage |
| `WORK_DIR` | `/tmp/git-mirror` | Working directory for git operations |

## Troubleshooting

### Sync fails with authentication error

- Verify your credentials are correct
- For HTTPS: Use a personal access token instead of password
- For SSH: Ensure the key format is correct and has proper permissions

### Container won't start

Check logs for errors:
```bash
docker-compose logs backend
```

### Changes not syncing

1. Check if the pair is enabled
2. Verify the sync interval hasn't elapsed yet
3. Try triggering a manual sync
4. Check the sync logs for errors

## Development

### Running locally without Docker

Backend:
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (with a simple HTTP server):
```bash
cd frontend
python -m http.server 3000
```

Note: You'll need to configure CORS or use a proxy for local development.

## License

MIT License - feel free to use and modify as needed.
