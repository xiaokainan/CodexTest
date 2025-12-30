from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship

from .database import Base


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    applicant = Column(String(100), nullable=False, default="XYY")
    date = Column(Date, nullable=True)
    recipient = Column(String(255), nullable=True)
    amount = Column(Float, nullable=True)
    registration_number = Column(String(100), nullable=True)
    image_path = Column(String(255), nullable=False)
    ocr_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    reviews = relationship("Review", back_populates="submission", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    reviewer = Column(String(100), nullable=False)
    status = Column(String(10), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("Submission", back_populates="reviews")
