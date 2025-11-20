import os
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from bson import ObjectId
import hashlib
import hmac
import time
import jwt

from database import db, create_document, get_documents
from schemas import User, Quiz, QuizAttempt, Question, UserAnswer

# Environment and constants
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_me")
JWT_ALGO = "HS256"
TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7

# FastAPI app
app = FastAPI(title="QuizGen: AI-Powered Quiz Hub")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)


# Utility helpers
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def hash_password(password: str) -> str:
    # Simple sha256 for demo; in production use bcrypt
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def create_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    if not creds:
        return None
    token = creds.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        user = db["user"].find_one({"_id": ObjectId(user_id)})
        if not user:
            return None
        user["_id"] = str(user["_id"])
        return user
    except Exception:
        return None


# Public endpoints
@app.get("/")
def root():
    return {"message": "QuizGen API running"}


@app.get("/test")
def test_database():
    status = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": [],
    }
    try:
        collections = db.list_collection_names()
        status["database"] = "✅ Connected"
        status["collections"] = collections
    except Exception as e:
        status["database"] = f"❌ {str(e)}"
    return status


# Auth models
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/register", response_model=TokenResponse)
def register(body: RegisterRequest):
    existing = db["user"].find_one({"email": body.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
    ).model_dump()
    user_id = create_document("user", user)
    token = create_token(user_id)
    return TokenResponse(access_token=token)


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = db["user"].find_one({"email": body.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(str(user["_id"]))
    return TokenResponse(access_token=token)


# Categories and subcategories
CATEGORIES = {
    "Academic": ["Physics", "Chemistry", "Mathematics", "Biology"],
    "Entertainment": ["Movies", "Music", "Sports", "Gaming"],
    "General Knowledge": ["History", "Geography", "Current Affairs", "Science"]
}


@app.get("/categories")
def get_categories():
    return CATEGORIES


class GenerateQuizRequest(BaseModel):
    category: str
    subcategory: str
    difficulty: str
    num_questions: int = 5


# Placeholder AI generation using simple templating. In real scenario integrate OpenAI.
def generate_questions_locally(subcat: str, difficulty: str, n: int) -> List[Question]:
    base_options = ["Option A", "Option B", "Option C", "Option D"]
    questions: List[Question] = []
    for i in range(n):
        q = Question(
            prompt=f"[{difficulty}] {subcat} question {i+1}?",
            options=base_options,
            answer_index=i % 4,
            explanation=f"Explanation for {subcat} question {i+1}."
        )
        questions.append(q)
    return questions


@app.post("/quiz/generate")
def generate_quiz(body: GenerateQuizRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if body.category not in CATEGORIES or body.subcategory not in CATEGORIES[body.category]:
        raise HTTPException(status_code=400, detail="Invalid category/subcategory")
    questions = generate_questions_locally(body.subcategory, body.difficulty, body.num_questions)
    quiz = Quiz(
        title=f"{body.subcategory} - {body.difficulty}",
        category=body.category,
        subcategory=body.subcategory,
        difficulty=body.difficulty,
        questions=questions,
        created_by=(user.get("_id") if user else None),
    ).model_dump()
    quiz_id = create_document("quiz", quiz)
    attempt = QuizAttempt(
        user_id=(user.get("_id") if user else "guest"),
        quiz_id=quiz_id,
        total=len(questions),
        duration_seconds=600,
    ).model_dump()
    attempt_id = create_document("quizattempt", attempt)
    return {"quiz_id": quiz_id, "attempt_id": attempt_id, "quiz": quiz}


# Attempts flow
class AnswerRequest(BaseModel):
    attempt_id: str
    answers: List[UserAnswer]


@app.post("/attempt/submit")
def submit_attempt(body: AnswerRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    try:
        attempt = db["quizattempt"].find_one({"_id": ObjectId(body.attempt_id)})
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt not found")
        quiz = db["quiz"].find_one({"_id": ObjectId(attempt["quiz_id"])})
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")
        correct = 0
        for ans in body.answers:
            q = quiz["questions"][ans.question_index]
            if ans.selected_index is not None and ans.selected_index == q["answer_index"]:
                correct += 1
        score = correct
        db["quizattempt"].update_one(
            {"_id": ObjectId(body.attempt_id)},
            {"$set": {"status": "completed", "answers": [a.model_dump() for a in body.answers], "score": score, "total": len(quiz["questions"])}}
        )
        return {"score": score, "total": len(quiz["questions"]) }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/me/attempts")
def my_attempts(user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    user_id = user.get("_id") if user else "guest"
    attempts = list(db["quizattempt"].find({"user_id": user_id}).sort("created_at", -1))
    for a in attempts:
        a["_id"] = str(a["_id"])
    return attempts
