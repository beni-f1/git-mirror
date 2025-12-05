from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid
from datetime import datetime

from .database_sql import db
from .sync_service import GitSyncService

app = FastAPI(title="Git Mirror", description="Git repository synchronization service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sync_service = GitSyncService()


class RepoCredentials(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key: Optional[str] = None


class RepoPairCreate(BaseModel):
    name: str = Field(..., description="Friendly name for this sync pair")
    source_url: str = Field(..., description="Source repository URL")
    destination_url: str = Field(..., description="Destination repository URL")
    source_credentials: Optional[RepoCredentials] = None
    destination_credentials: Optional[RepoCredentials] = None
    sync_interval_minutes: int = Field(default=60, ge=1, description="Sync interval in minutes")
    enabled: bool = True
    sync_branches: List[str] = Field(default=["*"], description="Branches to sync (* for all)")
    sync_tags: bool = True


class RepoPairUpdate(BaseModel):
    name: Optional[str] = None
    source_url: Optional[str] = None
    destination_url: Optional[str] = None
    source_credentials: Optional[RepoCredentials] = None
    destination_credentials: Optional[RepoCredentials] = None
    sync_interval_minutes: Optional[int] = None
    enabled: Optional[bool] = None
    sync_branches: Optional[List[str]] = None
    sync_tags: Optional[bool] = None


class GlobalConfig(BaseModel):
    default_sync_interval_minutes: int = 60
    max_concurrent_syncs: int = 3
    retry_on_failure: bool = True
    retry_count: int = 3


@app.on_event("startup")
async def startup():
    db.init()
    sync_service.start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    sync_service.stop_scheduler()


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# Repository Pair Endpoints
@app.get("/api/repo-pairs")
async def list_repo_pairs():
    return db.get_all_repo_pairs()


@app.post("/api/repo-pairs")
async def create_repo_pair(repo_pair: RepoPairCreate):
    pair_id = str(uuid.uuid4())
    data = repo_pair.dict()
    data["id"] = pair_id
    data["created_at"] = datetime.utcnow().isoformat()
    data["last_sync"] = None
    data["last_sync_status"] = None
    data["sync_count"] = 0
    db.save_repo_pair(pair_id, data)
    sync_service.schedule_pair(pair_id, data)
    return data


@app.get("/api/repo-pairs/{pair_id}")
async def get_repo_pair(pair_id: str):
    pair = db.get_repo_pair(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    return pair


@app.put("/api/repo-pairs/{pair_id}")
async def update_repo_pair(pair_id: str, update: RepoPairUpdate):
    existing = db.get_repo_pair(pair_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    
    update_data = update.dict(exclude_unset=True)
    existing.update(update_data)
    db.save_repo_pair(pair_id, existing)
    sync_service.reschedule_pair(pair_id, existing)
    return existing


@app.delete("/api/repo-pairs/{pair_id}")
async def delete_repo_pair(pair_id: str):
    if not db.get_repo_pair(pair_id):
        raise HTTPException(status_code=404, detail="Repository pair not found")
    sync_service.unschedule_pair(pair_id)
    db.delete_repo_pair(pair_id)
    return {"message": "Repository pair deleted"}


@app.post("/api/repo-pairs/{pair_id}/sync")
async def trigger_sync(pair_id: str, background_tasks: BackgroundTasks):
    pair = db.get_repo_pair(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    
    background_tasks.add_task(sync_service.sync_now, pair_id)
    return {"message": "Sync triggered", "pair_id": pair_id}


@app.get("/api/repo-pairs/{pair_id}/logs")
async def get_sync_logs(pair_id: str, limit: int = 50):
    if not db.get_repo_pair(pair_id):
        raise HTTPException(status_code=404, detail="Repository pair not found")
    return db.get_sync_logs(pair_id, limit)


# Global Configuration Endpoints
@app.get("/api/config")
async def get_config():
    return db.get_global_config()


@app.put("/api/config")
async def update_config(config: GlobalConfig):
    db.save_global_config(config.dict())
    sync_service.update_config(config.dict())
    return config


# Stats Endpoints
@app.get("/api/stats")
async def get_stats():
    pairs = db.get_all_repo_pairs()
    total_pairs = len(pairs)
    active_pairs = len([p for p in pairs if p.get("enabled", True)])
    total_syncs = sum(p.get("sync_count", 0) for p in pairs)
    
    return {
        "total_pairs": total_pairs,
        "active_pairs": active_pairs,
        "total_syncs": total_syncs,
        "scheduler_running": sync_service.is_running()
    }
