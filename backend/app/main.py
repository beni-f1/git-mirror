from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header, Cookie, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid
from datetime import datetime
from functools import wraps

from .database_sql import db
from .sync_service import GitSyncService
from .models import UserRole

app = FastAPI(title="Git Mirror", description="Git repository synchronization service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sync_service = GitSyncService()


# ==================== Pydantic Models ====================

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


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=4)
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = Field(default=UserRole.VIEW.value)


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=4)


# ==================== Authentication Helpers ====================

async def get_current_user(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None)
) -> Optional[dict]:
    """Extract and validate user from session token"""
    token = None
    
    # Check Authorization header first (Bearer token)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    # Fall back to cookie
    elif session_token:
        token = session_token
    
    if not token:
        return None
    
    return db.get_session_user(token)


async def require_auth(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None)
) -> dict:
    """Require authenticated user"""
    user = await get_current_user(authorization, session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_role(required_roles: List[str]):
    """Factory for role-based authorization"""
    async def check_role(
        authorization: Optional[str] = Header(None),
        session_token: Optional[str] = Cookie(None)
    ) -> dict:
        user = await get_current_user(authorization, session_token)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if user["role"] not in required_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return check_role


def require_view():
    """Require at least VIEW role"""
    return Depends(require_auth)


def require_edit():
    """Require at least EDIT role"""
    async def check(
        authorization: Optional[str] = Header(None),
        session_token: Optional[str] = Cookie(None)
    ) -> dict:
        user = await get_current_user(authorization, session_token)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if user["role"] not in [UserRole.EDIT.value, UserRole.ADMIN.value]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return Depends(check)


def require_admin():
    """Require ADMIN role"""
    async def check(
        authorization: Optional[str] = Header(None),
        session_token: Optional[str] = Cookie(None)
    ) -> dict:
        user = await get_current_user(authorization, session_token)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if user["role"] != UserRole.ADMIN.value:
            raise HTTPException(status_code=403, detail="Admin access required")
        return user
    return Depends(check)


# ==================== App Events ====================

@app.on_event("startup")
async def startup():
    db.init()
    # Create or update admin user based on environment variables
    import os
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
    result = db.create_default_admin()
    if result == "created":
        print(f"Created admin user (username: {admin_username}, password: {admin_password})")
    elif result == "updated":
        print(f"Updated admin user (username: {admin_username}, password: {admin_password})")
    sync_service.start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    sync_service.stop_scheduler()


# ==================== Health Check ====================

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ==================== Authentication Endpoints ====================

@app.post("/api/auth/login")
async def login(login_data: LoginRequest, response: Response):
    user = db.authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = db.create_session(user["id"])
    
    # Set cookie for browser
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400,  # 24 hours
        samesite="lax"
    )
    
    return {
        "token": token,
        "user": user
    }


@app.post("/api/auth/logout")
async def logout(
    response: Response,
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None)
):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif session_token:
        token = session_token
    
    if token:
        db.delete_session(token)
    
    response.delete_cookie("session_token")
    return {"message": "Logged out successfully"}


@app.get("/api/auth/me")
async def get_current_user_info(user: dict = require_view()):
    return user


@app.put("/api/auth/password")
async def change_password(password_data: PasswordChange, user: dict = require_view()):
    # Verify current password
    if not db.authenticate_user(user["username"], password_data.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    db.update_user(user["id"], {"password": password_data.new_password})
    return {"message": "Password changed successfully"}


# ==================== User Management Endpoints (Admin Only) ====================

@app.get("/api/users")
async def list_users(user: dict = require_admin()):
    return db.get_all_users()


@app.post("/api/users")
async def create_user(user_data: UserCreate, user: dict = require_admin()):
    # Check if username exists
    if db.get_user_by_username(user_data.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Validate role
    valid_roles = [r.value for r in UserRole]
    if user_data.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")
    
    user_id = str(uuid.uuid4())
    new_user = db.create_user(
        user_id=user_id,
        username=user_data.username,
        password=user_data.password,
        email=user_data.email,
        full_name=user_data.full_name,
        role=user_data.role
    )
    return new_user


@app.get("/api/users/{user_id}")
async def get_user(user_id: str, user: dict = require_admin()):
    target_user = db.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    return target_user


@app.put("/api/users/{user_id}")
async def update_user(user_id: str, user_data: UserUpdate, user: dict = require_admin()):
    target_user = db.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_data.dict(exclude_unset=True)
    
    # Validate role if provided
    if "role" in update_data:
        valid_roles = [r.value for r in UserRole]
        if update_data["role"] not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")
    
    # Check username uniqueness if changing
    if "username" in update_data and update_data["username"] != target_user["username"]:
        if db.get_user_by_username(update_data["username"]):
            raise HTTPException(status_code=400, detail="Username already exists")
    
    updated_user = db.update_user(user_id, update_data)
    return updated_user


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str, user: dict = require_admin()):
    # Prevent self-deletion
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    target_user = db.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete_user(user_id)
    return {"message": "User deleted successfully"}


@app.get("/api/roles")
async def get_roles(user: dict = require_admin()):
    """Get available user roles"""
    return [{"value": r.value, "label": r.value.title()} for r in UserRole]


# ==================== Repository Pair Endpoints ====================

@app.get("/api/repo-pairs")
async def list_repo_pairs(user: dict = require_view()):
    return db.get_all_repo_pairs()


@app.post("/api/repo-pairs")
async def create_repo_pair(repo_pair: RepoPairCreate, user: dict = require_edit()):
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
async def get_repo_pair(pair_id: str, user: dict = require_view()):
    pair = db.get_repo_pair(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    return pair


@app.put("/api/repo-pairs/{pair_id}")
async def update_repo_pair(pair_id: str, update: RepoPairUpdate, user: dict = require_edit()):
    existing = db.get_repo_pair(pair_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    
    update_data = update.dict(exclude_unset=True)
    existing.update(update_data)
    db.save_repo_pair(pair_id, existing)
    sync_service.reschedule_pair(pair_id, existing)
    return existing


@app.delete("/api/repo-pairs/{pair_id}")
async def delete_repo_pair(pair_id: str, user: dict = require_edit()):
    if not db.get_repo_pair(pair_id):
        raise HTTPException(status_code=404, detail="Repository pair not found")
    sync_service.unschedule_pair(pair_id)
    db.delete_repo_pair(pair_id)
    return {"message": "Repository pair deleted"}


@app.post("/api/repo-pairs/{pair_id}/sync")
async def trigger_sync(pair_id: str, user: dict = require_edit()):
    pair = db.get_repo_pair(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    
    # sync_now now handles background execution internally
    sync_service.sync_now(pair_id)
    return {"message": "Sync triggered", "pair_id": pair_id}


@app.post("/api/repo-pairs/{pair_id}/abort")
async def abort_sync(pair_id: str, user: dict = require_edit()):
    """Abort a running sync for a repo pair"""
    pair = db.get_repo_pair(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Repository pair not found")
    
    if sync_service.abort_sync(pair_id):
        return {"message": "Abort requested", "pair_id": pair_id}
    else:
        raise HTTPException(status_code=400, detail="No sync in progress for this pair")


@app.get("/api/sync-status")
async def get_sync_status(user: dict = require_view()):
    """Get list of currently syncing repo pair IDs"""
    return {"syncing": sync_service.get_active_syncs()}


@app.get("/api/repo-pairs/{pair_id}/logs")
async def get_sync_logs(pair_id: str, limit: int = 50, user: dict = require_view()):
    if not db.get_repo_pair(pair_id):
        raise HTTPException(status_code=404, detail="Repository pair not found")
    return db.get_sync_logs(pair_id, limit)


@app.get("/api/recent-activity")
async def get_recent_activity(limit: int = 10, user: dict = require_view()):
    """Get recent sync activity across all repository pairs"""
    return db.get_recent_activity(limit)


# ==================== Global Configuration Endpoints ====================

@app.get("/api/config")
async def get_config(user: dict = require_view()):
    return db.get_global_config()


@app.put("/api/config")
async def update_config(config: GlobalConfig, user: dict = require_admin()):
    db.save_global_config(config.dict())
    sync_service.update_config(config.dict())
    return config


# ==================== Stats Endpoints ====================

@app.get("/api/stats")
async def get_stats(user: dict = require_view()):
    pairs = db.get_all_repo_pairs()
    total_pairs = len(pairs)
    active_pairs = len([p for p in pairs if p.get("enabled", True)])
    total_syncs = sum(p.get("sync_count", 0) for p in pairs)
    users = db.get_all_users()
    
    return {
        "total_pairs": total_pairs,
        "active_pairs": active_pairs,
        "total_syncs": total_syncs,
        "total_users": len(users),
        "scheduler_running": sync_service.is_running()
    }
