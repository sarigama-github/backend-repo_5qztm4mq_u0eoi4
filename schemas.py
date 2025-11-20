"""
Database Schemas for QuizGen

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
- User -> "user"
- Quiz -> "quiz"
- QuizAttempt -> "quizattempt"
- Question is an embedded model used inside Quiz documents
"""

from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal


class UserPreferences(BaseModel):
    theme: Literal["light", "dark", "neon"] = "neon"
    default_difficulty: Literal["Easy", "Medium", "Hard"] = "Easy"


class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    avatar: Optional[str] = Field(None, description="Avatar URL")
    preferences: Optional[UserPreferences] = Field(default_factory=UserPreferences)
    password_hash: str = Field(..., description="BCrypt password hash")


class Question(BaseModel):
    prompt: str = Field(..., description="Question text")
    options: List[str] = Field(..., min_items=2, description="Multiple-choice options")
    answer_index: int = Field(..., ge=0, description="Index of correct answer in options")
    explanation: Optional[str] = Field(None, description="Explanation for the correct answer")


class Quiz(BaseModel):
    title: str
    category: Literal["Academic", "Entertainment", "General Knowledge"]
    subcategory: str
    difficulty: Literal["Easy", "Medium", "Hard"]
    questions: List[Question]
    created_by: Optional[str] = Field(None, description="User id if user-generated")


class UserAnswer(BaseModel):
    question_index: int
    selected_index: Optional[int] = None


class QuizAttempt(BaseModel):
    user_id: str
    quiz_id: str
    status: Literal["ongoing", "completed"] = "ongoing"
    answers: List[UserAnswer] = Field(default_factory=list)
    score: int = 0
    total: int = 0
    duration_seconds: int = 600
"""
Note: timestamps (created_at/updated_at) are added automatically by database helpers.
"""
