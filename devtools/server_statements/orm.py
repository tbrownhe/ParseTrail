from sqlalchemy import TIMESTAMP, Column, Enum, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

PluginStatusEnum = Enum("pending", "ready", name="plugin_status")


class StatementUploads(Base):
    """SQLAlchemy model for the backend statement_uploads table."""

    __tablename__ = "statement_uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False, index=True)
    metadata_field = Column(String, nullable=True, name="metadata")
    init_vector = Column(LargeBinary, nullable=False)
    auth_tag = Column(LargeBinary, nullable=False)
    client_ip = Column(String(50), nullable=False)
    user_agent = Column(String(255), nullable=True)
    timestamp = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    plugin_status = Column(
        PluginStatusEnum, nullable=False, server_default="pending", default="pending"
    )
