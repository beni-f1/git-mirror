import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base, RepoPair, SyncLog, GlobalConfig


class Database:
    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database connection.
        
        For SQLite: sqlite:////data/git_mirror.db
        For PostgreSQL: postgresql://user:password@host:port/dbname
        
        Set DATABASE_URL environment variable to configure the database.
        """
        if database_url is None:
            # Check for DATABASE_URL environment variable
            database_url = os.environ.get("DATABASE_URL")
            
            if database_url is None:
                # Default to SQLite in /data directory
                data_dir = os.environ.get("DATA_DIR", "/data")
                database_url = f"sqlite:///{data_dir}/git_mirror.db"
        
        self.database_url = database_url
        self._engine = None
        self._SessionLocal = None
    
    def init(self):
        """Initialize database connection and create tables"""
        # Create data directory if using SQLite
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # For SQLite, we need check_same_thread=False for multi-threaded access
        connect_args = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        
        self._engine = create_engine(
            self.database_url,
            connect_args=connect_args,
            pool_pre_ping=True  # Helps with connection reliability
        )
        
        self._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)
        
        # Create all tables
        Base.metadata.create_all(bind=self._engine)
        
        # Initialize default config if not exists
        with self.get_session() as session:
            config = session.query(GlobalConfig).first()
            if not config:
                config = GlobalConfig()
                session.add(config)
                session.commit()
    
    @contextmanager
    def get_session(self) -> Session:
        """Get a database session with automatic cleanup"""
        session = self._SessionLocal()
        try:
            yield session
        finally:
            session.close()
    
    # Repository Pairs
    def get_all_repo_pairs(self) -> List[Dict]:
        with self.get_session() as session:
            pairs = session.query(RepoPair).all()
            return [pair.to_dict() for pair in pairs]
    
    def get_repo_pair(self, pair_id: str) -> Optional[Dict]:
        with self.get_session() as session:
            pair = session.query(RepoPair).filter(RepoPair.id == pair_id).first()
            return pair.to_dict() if pair else None
    
    def save_repo_pair(self, pair_id: str, pair_data: Dict):
        with self.get_session() as session:
            existing = session.query(RepoPair).filter(RepoPair.id == pair_id).first()
            
            if existing:
                # Update existing
                for key, value in pair_data.items():
                    if key != "id" and hasattr(existing, key):
                        # Handle datetime strings
                        if key in ["last_sync", "created_at", "updated_at"] and isinstance(value, str):
                            value = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
                        setattr(existing, key, value)
            else:
                # Create new
                new_pair = RepoPair(
                    id=pair_id,
                    name=pair_data.get("name"),
                    source_url=pair_data.get("source_url"),
                    destination_url=pair_data.get("destination_url"),
                    source_credentials=pair_data.get("source_credentials"),
                    destination_credentials=pair_data.get("destination_credentials"),
                    sync_interval_minutes=pair_data.get("sync_interval_minutes", 60),
                    enabled=pair_data.get("enabled", True),
                    sync_branches=pair_data.get("sync_branches", ["*"]),
                    sync_tags=pair_data.get("sync_tags", True),
                    sync_count=pair_data.get("sync_count", 0),
                )
                session.add(new_pair)
            
            session.commit()
    
    def delete_repo_pair(self, pair_id: str):
        with self.get_session() as session:
            pair = session.query(RepoPair).filter(RepoPair.id == pair_id).first()
            if pair:
                session.delete(pair)
                session.commit()
    
    def update_sync_status(self, pair_id: str, status: str, error: Optional[str] = None):
        with self.get_session() as session:
            pair = session.query(RepoPair).filter(RepoPair.id == pair_id).first()
            if pair:
                pair.last_sync = datetime.utcnow()
                pair.last_sync_status = status
                pair.last_sync_error = error
                pair.sync_count = (pair.sync_count or 0) + 1
                session.commit()
    
    # Sync Logs
    def add_sync_log(self, pair_id: str, log_entry: Dict):
        with self.get_session() as session:
            log = SyncLog(
                repo_pair_id=pair_id,
                status=log_entry.get("status", "unknown"),
                message=log_entry.get("message"),
                error=log_entry.get("error"),
                duration_seconds=log_entry.get("duration_seconds"),
            )
            session.add(log)
            session.commit()
            
            # Clean up old logs (keep last 100 per repo pair)
            logs = session.query(SyncLog).filter(
                SyncLog.repo_pair_id == pair_id
            ).order_by(SyncLog.timestamp.desc()).offset(100).all()
            
            for old_log in logs:
                session.delete(old_log)
            session.commit()
    
    def get_sync_logs(self, pair_id: str, limit: int = 50) -> List[Dict]:
        with self.get_session() as session:
            logs = session.query(SyncLog).filter(
                SyncLog.repo_pair_id == pair_id
            ).order_by(SyncLog.timestamp.desc()).limit(limit).all()
            
            return [log.to_dict() for log in logs]
    
    # Global Configuration
    def get_global_config(self) -> Dict[str, Any]:
        with self.get_session() as session:
            config = session.query(GlobalConfig).first()
            if config:
                return config.to_dict()
            return {
                "default_sync_interval_minutes": 60,
                "max_concurrent_syncs": 3,
                "retry_on_failure": True,
                "retry_count": 3
            }
    
    def save_global_config(self, config_data: Dict):
        with self.get_session() as session:
            config = session.query(GlobalConfig).first()
            if not config:
                config = GlobalConfig()
                session.add(config)
            
            for key, value in config_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            session.commit()


# Global database instance
db = Database()
