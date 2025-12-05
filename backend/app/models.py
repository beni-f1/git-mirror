from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class RepoPair(Base):
    __tablename__ = "repo_pairs"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    source_url = Column(String(1024), nullable=False)
    destination_url = Column(String(1024), nullable=False)
    
    # Credentials stored as JSON for flexibility
    source_credentials = Column(JSON, nullable=True)
    destination_credentials = Column(JSON, nullable=True)
    
    sync_interval_minutes = Column(Integer, default=60)
    enabled = Column(Boolean, default=True)
    sync_branches = Column(JSON, default=["*"])  # List of branches or ["*"] for all
    sync_tags = Column(Boolean, default=True)
    
    # Sync status
    last_sync = Column(DateTime, nullable=True)
    last_sync_status = Column(String(50), nullable=True)  # success, error, in_progress
    last_sync_error = Column(Text, nullable=True)
    sync_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to sync logs
    sync_logs = relationship("SyncLog", back_populates="repo_pair", cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "source_url": self.source_url,
            "destination_url": self.destination_url,
            "source_credentials": self.source_credentials,
            "destination_credentials": self.destination_credentials,
            "sync_interval_minutes": self.sync_interval_minutes,
            "enabled": self.enabled,
            "sync_branches": self.sync_branches or ["*"],
            "sync_tags": self.sync_tags,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "last_sync_status": self.last_sync_status,
            "last_sync_error": self.last_sync_error,
            "sync_count": self.sync_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SyncLog(Base):
    __tablename__ = "sync_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_pair_id = Column(String(36), ForeignKey("repo_pairs.id", ondelete="CASCADE"), nullable=False)
    
    status = Column(String(50), nullable=False)  # success, error
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    repo_pair = relationship("RepoPair", back_populates="sync_logs")
    
    def to_dict(self):
        return {
            "id": self.id,
            "repo_pair_id": self.repo_pair_id,
            "status": self.status,
            "message": self.message,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class GlobalConfig(Base):
    __tablename__ = "global_config"
    
    id = Column(Integer, primary_key=True, default=1)
    default_sync_interval_minutes = Column(Integer, default=60)
    max_concurrent_syncs = Column(Integer, default=3)
    retry_on_failure = Column(Boolean, default=True)
    retry_count = Column(Integer, default=3)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "default_sync_interval_minutes": self.default_sync_interval_minutes,
            "max_concurrent_syncs": self.max_concurrent_syncs,
            "retry_on_failure": self.retry_on_failure,
            "retry_count": self.retry_count,
        }
