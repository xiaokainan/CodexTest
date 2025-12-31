from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship

from .database import Base


class Flow(Base):
    __tablename__ = "flows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), unique=True, nullable=False)
    category = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    steps = relationship("FlowStep", back_populates="flow", cascade="all, delete-orphan", order_by="FlowStep.order")
    requests = relationship("FlowRequest", back_populates="flow", cascade="all, delete-orphan")


class FlowStep(Base):
    __tablename__ = "flow_steps"

    id = Column(Integer, primary_key=True, index=True)
    flow_id = Column(Integer, ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(150), nullable=False)
    approver_role = Column(String(150), nullable=True)
    order = Column(Integer, nullable=False, default=1)

    flow = relationship("Flow", back_populates="steps")


class FlowRequest(Base):
    __tablename__ = "flow_requests"

    id = Column(Integer, primary_key=True, index=True)
    flow_id = Column(Integer, ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    applicant = Column(String(150), nullable=False)
    applicant_login = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow = relationship("Flow", back_populates="requests")
    approvals = relationship("FlowRequestApproval", back_populates="request", cascade="all, delete-orphan")


class FlowRequestApproval(Base):
    __tablename__ = "flow_request_approvals"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("flow_requests.id", ondelete="CASCADE"), nullable=False)
    step_name = Column(String(150), nullable=True)
    step_order = Column(Integer, nullable=True)
    actor = Column(String(150), nullable=False)
    decision = Column(String(50), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    request = relationship("FlowRequest", back_populates="approvals")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("Submission", back_populates="user", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    applicant = Column(String(100), nullable=False, default="XYY")
    applicant_login = Column(String(100), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    date = Column(Date, nullable=True)
    recipient = Column(String(255), nullable=True)
    amount = Column(Float, nullable=True)
    registration_number = Column(String(100), nullable=True)
    image_path = Column(String(255), nullable=False)
    ocr_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    reviews = relationship("Review", back_populates="submission", cascade="all, delete-orphan")
    user = relationship("User", back_populates="submissions")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    reviewer = Column(String(100), nullable=False)
    status = Column(String(10), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("Submission", back_populates="reviews")
