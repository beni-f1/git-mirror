import subprocess
import os
import shutil
import threading
import time
import fnmatch
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GitSyncService:
    def __init__(self):
        self.work_dir = Path(os.environ.get("WORK_DIR", "/tmp/git-mirror"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        self._scheduler_thread: Optional[threading.Thread] = None
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._scheduled_pairs: Dict[str, dict] = {}
        self._config = {
            "max_concurrent_syncs": 3,
            "retry_on_failure": True,
            "retry_count": 3
        }
        self._active_syncs: Dict[str, bool] = {}
    
    def start_scheduler(self):
        """Start the background scheduler"""
        if self._running:
            return
        
        self._running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info("Scheduler started")
        
        # Load existing pairs
        from .database_sql import db
        for pair in db.get_all_repo_pairs():
            self.schedule_pair(pair["id"], pair)
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        self._executor.shutdown(wait=False)
        logger.info("Scheduler stopped")
    
    def is_running(self) -> bool:
        return self._running
    
    def _scheduler_loop(self):
        """Main scheduler loop that checks for pairs that need syncing"""
        while self._running:
            try:
                self._check_scheduled_syncs()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            time.sleep(30)  # Check every 30 seconds
    
    def _check_scheduled_syncs(self):
        """Check all pairs and trigger sync if needed"""
        from .database_sql import db
        
        now = datetime.utcnow()
        for pair_id, pair_info in list(self._scheduled_pairs.items()):
            if not pair_info.get("enabled", True):
                continue
            
            if self._active_syncs.get(pair_id):
                continue
            
            last_check = pair_info.get("_last_check")
            interval_minutes = pair_info.get("sync_interval_minutes", 60)
            
            if last_check is None:
                should_sync = True
            else:
                elapsed = (now - last_check).total_seconds() / 60
                should_sync = elapsed >= interval_minutes
            
            if should_sync:
                pair_info["_last_check"] = now
                self._executor.submit(self._do_sync, pair_id)
    
    def schedule_pair(self, pair_id: str, pair_data: dict):
        """Add or update a pair in the scheduler"""
        self._scheduled_pairs[pair_id] = pair_data.copy()
        logger.info(f"Scheduled pair: {pair_id}")
    
    def unschedule_pair(self, pair_id: str):
        """Remove a pair from the scheduler"""
        if pair_id in self._scheduled_pairs:
            del self._scheduled_pairs[pair_id]
        logger.info(f"Unscheduled pair: {pair_id}")
    
    def reschedule_pair(self, pair_id: str, pair_data: dict):
        """Update a pair's schedule"""
        if pair_id in self._scheduled_pairs:
            # Preserve last check time
            last_check = self._scheduled_pairs[pair_id].get("_last_check")
            self._scheduled_pairs[pair_id] = pair_data.copy()
            if last_check:
                self._scheduled_pairs[pair_id]["_last_check"] = last_check
        else:
            self.schedule_pair(pair_id, pair_data)
    
    def update_config(self, config: dict):
        """Update global configuration"""
        self._config.update(config)
        self._executor._max_workers = config.get("max_concurrent_syncs", 3)
    
    def sync_now(self, pair_id: str):
        """Trigger immediate sync for a pair"""
        self._do_sync(pair_id)
    
    def _do_sync(self, pair_id: str):
        """Execute the actual git sync"""
        from .database_sql import db
        
        if self._active_syncs.get(pair_id):
            logger.info(f"Sync already in progress for {pair_id}")
            return
        
        self._active_syncs[pair_id] = True
        pair = db.get_repo_pair(pair_id)
        
        if not pair:
            self._active_syncs[pair_id] = False
            return
        
        start_time = datetime.utcnow()
        log_entry = {
            "started_at": start_time.isoformat(),
            "source_url": pair["source_url"],
            "destination_url": pair["destination_url"],
        }
        
        try:
            logger.info(f"Starting sync for {pair_id}: {pair['name']}")
            
            result = self._perform_git_sync(
                pair_id=pair_id,
                source_url=pair["source_url"],
                destination_url=pair["destination_url"],
                source_creds=pair.get("source_credentials"),
                dest_creds=pair.get("destination_credentials"),
                sync_branches=pair.get("sync_branches", ["*"]),
                sync_tags=pair.get("sync_tags", True)
            )
            
            log_entry["status"] = "success"
            log_entry["message"] = result.get("message", "Sync completed successfully")
            log_entry["branches_synced"] = result.get("branches_synced", [])
            log_entry["tags_synced"] = result.get("tags_synced", 0)
            
            db.update_sync_status(pair_id, "success")
            logger.info(f"Sync completed for {pair_id}")
            
        except Exception as e:
            error_msg = str(e)
            log_entry["status"] = "error"
            log_entry["error"] = error_msg
            
            db.update_sync_status(pair_id, "error", error_msg)
            logger.error(f"Sync failed for {pair_id}: {error_msg}")
            
            # Retry logic
            if self._config.get("retry_on_failure"):
                retry_count = self._config.get("retry_count", 3)
                for attempt in range(retry_count):
                    try:
                        time.sleep(5 * (attempt + 1))  # Exponential backoff
                        self._perform_git_sync(
                            pair_id=pair_id,
                            source_url=pair["source_url"],
                            destination_url=pair["destination_url"],
                            source_creds=pair.get("source_credentials"),
                            dest_creds=pair.get("destination_credentials"),
                            sync_branches=pair.get("sync_branches", ["*"]),
                            sync_tags=pair.get("sync_tags", True)
                        )
                        log_entry["status"] = "success"
                        log_entry["message"] = f"Sync succeeded after {attempt + 1} retries"
                        db.update_sync_status(pair_id, "success")
                        break
                    except Exception as retry_e:
                        logger.error(f"Retry {attempt + 1} failed for {pair_id}: {retry_e}")
        
        finally:
            end_time = datetime.utcnow()
            log_entry["ended_at"] = end_time.isoformat()
            log_entry["duration_seconds"] = (end_time - start_time).total_seconds()
            
            db.add_sync_log(pair_id, log_entry)
            self._active_syncs[pair_id] = False
    
    def _perform_git_sync(
        self,
        pair_id: str,
        source_url: str,
        destination_url: str,
        source_creds: Optional[dict] = None,
        dest_creds: Optional[dict] = None,
        sync_branches: List[str] = None,
        sync_tags: bool = True
    ) -> dict:
        """Perform the actual git mirror operation"""
        
        repo_dir = self.work_dir / pair_id
        
        # Build authenticated URLs
        auth_source_url = self._build_auth_url(source_url, source_creds)
        auth_dest_url = self._build_auth_url(destination_url, dest_creds)
        
        # Setup SSH if needed
        ssh_env = os.environ.copy()
        ssh_key_file = None
        
        if source_creds and source_creds.get("ssh_key"):
            ssh_key_file = self._setup_ssh_key(pair_id, "source", source_creds["ssh_key"])
            ssh_env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_file} -o StrictHostKeyChecking=no"
        elif dest_creds and dest_creds.get("ssh_key"):
            ssh_key_file = self._setup_ssh_key(pair_id, "dest", dest_creds["ssh_key"])
            ssh_env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_file} -o StrictHostKeyChecking=no"
        
        try:
            # Ensure work directory exists
            self.work_dir.mkdir(parents=True, exist_ok=True)
            
            # Clone or fetch from source
            if repo_dir.exists() and (repo_dir / "HEAD").exists():
                # It's a valid git repo, fetch updates
                logger.info(f"Fetching updates for existing repo at {repo_dir}")
                self._run_git(["remote", "set-url", "origin", auth_source_url], cwd=repo_dir, env=ssh_env)
                self._run_git(["fetch", "--all", "--prune"], cwd=repo_dir, env=ssh_env)
            else:
                # Remove if exists but not a valid git repo
                if repo_dir.exists():
                    logger.info(f"Removing invalid repo directory: {repo_dir}")
                    shutil.rmtree(repo_dir)
                # Clone as mirror
                logger.info(f"Cloning mirror from {source_url} to {repo_dir}")
                self._run_git(
                    ["clone", "--mirror", auth_source_url, str(repo_dir)],
                    cwd=self.work_dir,
                    env=ssh_env
                )
            
            # Get branches to sync (mirror repos don't have origin/ prefix)
            branches_output = self._run_git(
                ["branch"],
                cwd=repo_dir,
                env=ssh_env
            )
            all_branches = [b.strip().lstrip("* ") for b in branches_output.split("\n") if b.strip()]
            
            # Filter branches
            if sync_branches and "*" not in sync_branches:
                branches_to_sync = []
                for branch in all_branches:
                    for pattern in sync_branches:
                        if fnmatch.fnmatch(branch, pattern):
                            branches_to_sync.append(branch)
                            break
            else:
                branches_to_sync = all_branches
            
            # Set destination remote
            try:
                self._run_git(["remote", "add", "destination", auth_dest_url], cwd=repo_dir, env=ssh_env)
            except:
                self._run_git(["remote", "set-url", "destination", auth_dest_url], cwd=repo_dir, env=ssh_env)
            
            # Push to destination
            push_args = ["push", "destination", "--mirror", "--force"]
            if not sync_tags:
                push_args = ["push", "destination", "--all", "--force"]
            
            self._run_git(push_args, cwd=repo_dir, env=ssh_env)
            
            # Count tags if synced
            tags_synced = 0
            if sync_tags:
                tags_output = self._run_git(["tag", "-l"], cwd=repo_dir, env=ssh_env)
                tags_synced = len([t for t in tags_output.split("\n") if t.strip()])
            
            return {
                "message": "Sync completed successfully",
                "branches_synced": branches_to_sync,
                "tags_synced": tags_synced
            }
            
        finally:
            # Cleanup SSH key file
            if ssh_key_file and os.path.exists(ssh_key_file):
                os.remove(ssh_key_file)
    
    def _build_auth_url(self, url: str, creds: Optional[dict]) -> str:
        """Build URL with authentication if credentials provided"""
        if not creds or not creds.get("username"):
            return url
        
        if url.startswith("git@") or url.startswith("ssh://"):
            return url  # SSH URLs don't need embedded credentials
        
        username = creds.get("username", "")
        password = creds.get("password", "")
        
        if "://" in url:
            protocol, rest = url.split("://", 1)
            if "@" in rest:
                rest = rest.split("@", 1)[1]
            return f"{protocol}://{username}:{password}@{rest}"
        
        return url
    
    def _setup_ssh_key(self, pair_id: str, key_type: str, ssh_key: str) -> str:
        """Setup SSH key file and return its path"""
        ssh_dir = self.work_dir / "ssh_keys"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        
        key_file = ssh_dir / f"{pair_id}_{key_type}_key"
        key_file.write_text(ssh_key)
        key_file.chmod(0o600)
        
        return str(key_file)
    
    def _run_git(self, args: list, cwd: Optional[Path] = None, env: dict = None) -> str:
        """Run a git command and return output"""
        cmd = ["git"] + args
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env or os.environ,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            raise Exception(f"Git command failed: {result.stderr}")
        
        return result.stdout
