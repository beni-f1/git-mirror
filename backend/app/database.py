import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import threading


class Database:
    def __init__(self, data_dir: str = "/data"):
        self.data_dir = Path(data_dir)
        self.repo_pairs_file = self.data_dir / "repo_pairs.json"
        self.config_file = self.data_dir / "config.json"
        self.logs_dir = self.data_dir / "logs"
        self._lock = threading.Lock()
    
    def init(self):
        """Initialize database directories and files"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.repo_pairs_file.exists():
            self._write_json(self.repo_pairs_file, {})
        
        if not self.config_file.exists():
            self._write_json(self.config_file, self._default_config())
    
    def _default_config(self) -> Dict[str, Any]:
        return {
            "default_sync_interval_minutes": 60,
            "max_concurrent_syncs": 3,
            "retry_on_failure": True,
            "retry_count": 3
        }
    
    def _read_json(self, filepath: Path) -> Dict:
        with self._lock:
            try:
                with open(filepath, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}
    
    def _write_json(self, filepath: Path, data: Dict):
        with self._lock:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2, default=str)
    
    # Repository Pairs
    def get_all_repo_pairs(self) -> List[Dict]:
        data = self._read_json(self.repo_pairs_file)
        return list(data.values())
    
    def get_repo_pair(self, pair_id: str) -> Optional[Dict]:
        data = self._read_json(self.repo_pairs_file)
        return data.get(pair_id)
    
    def save_repo_pair(self, pair_id: str, pair_data: Dict):
        data = self._read_json(self.repo_pairs_file)
        data[pair_id] = pair_data
        self._write_json(self.repo_pairs_file, data)
    
    def delete_repo_pair(self, pair_id: str):
        data = self._read_json(self.repo_pairs_file)
        if pair_id in data:
            del data[pair_id]
            self._write_json(self.repo_pairs_file, data)
        
        # Also delete logs
        log_file = self.logs_dir / f"{pair_id}.json"
        if log_file.exists():
            log_file.unlink()
    
    def update_sync_status(self, pair_id: str, status: str, error: Optional[str] = None):
        pair = self.get_repo_pair(pair_id)
        if pair:
            pair["last_sync"] = datetime.utcnow().isoformat()
            pair["last_sync_status"] = status
            pair["last_sync_error"] = error
            pair["sync_count"] = pair.get("sync_count", 0) + 1
            self.save_repo_pair(pair_id, pair)
    
    # Sync Logs
    def add_sync_log(self, pair_id: str, log_entry: Dict):
        log_file = self.logs_dir / f"{pair_id}.json"
        logs = self._read_json(log_file) if log_file.exists() else {"logs": []}
        
        log_entry["timestamp"] = datetime.utcnow().isoformat()
        logs["logs"].insert(0, log_entry)
        
        # Keep only last 100 logs
        logs["logs"] = logs["logs"][:100]
        self._write_json(log_file, logs)
    
    def get_sync_logs(self, pair_id: str, limit: int = 50) -> List[Dict]:
        log_file = self.logs_dir / f"{pair_id}.json"
        if not log_file.exists():
            return []
        logs = self._read_json(log_file)
        return logs.get("logs", [])[:limit]
    
    # Global Configuration
    def get_global_config(self) -> Dict:
        config = self._read_json(self.config_file)
        return {**self._default_config(), **config}
    
    def save_global_config(self, config: Dict):
        self._write_json(self.config_file, config)


# Global database instance
db = Database(os.environ.get("DATA_DIR", "/data"))
