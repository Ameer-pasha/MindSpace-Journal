# Standard library imports
import json
import os
import pathlib
import time
import uuid
from datetime import datetime, date, timedelta
from functools import wraps

# Third-party imports
import joblib
import requests
import requests as http_requests
from dotenv import load_dotenv

# Google authentication imports
import google.oauth2.id_token
import google.auth.transport.requests
from google_auth_oauthlib.flow import Flow

# Flask imports
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Flask extensions and validators
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length

# SQLAlchemy imports
from sqlalchemy.orm import DeclarativeBase, relationship




load_dotenv()

if os.environ.get('FLASK_ENV') == 'development':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

class Base(DeclarativeBase):
    pass


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# Load ML models
classifier = joblib.load("models/tweet_sentiment_model.pkl")
vectorizer = joblib.load("models/tfidf_vectorizer.pkl")

# Sentiment mapping
sentiment_map = {0: "Neutral 🤔", 1: "Positive 😊", -1: "Negative 💛"}
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)
# API configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent"
SYSTEM_PROMPT = "You are a warm, empathetic, and supportive AI companion for a personal journal app. Your goal is to engage in thoughtful and helpful conversation, acknowledging the user's feelings and encouraging them to share more."

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'http://127.0.0.1:5000/callback')

# Only setup OAuth if client_secret.json exists
if os.path.exists('client_secret.json'):
    flow = Flow.from_client_secrets_file(
        'client_secret.json',
        scopes=[
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile',
            'openid'
        ],
        redirect_uri=REDIRECT_URI
    )
else:
    flow = None

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# --- User Model ---
class User(db.Model):
    __tablename__ = 'users'  # <-- explicitly define table name
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=True)

    # Relationships
    entries = db.relationship('JournalEntry', back_populates='user', cascade='all, delete-orphan')
    goals = db.relationship('Goal', back_populates='user', cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', back_populates='user', cascade='all, delete-orphan')


# --- JournalEntry Model ---
class JournalEntry(db.Model):
    __tablename__ = 'journal_entries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.Integer, default=0)  # -1, 0, 1
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    time_str = db.Column(db.String(20))  # "03:45 PM"

    user = db.relationship('User', back_populates='entries')


# --- Goal Model ---
class Goal(db.Model):
    __tablename__ = 'goals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    deadline = db.Column(db.String(20))
    reason = db.Column(db.String(500))
    completed_date = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='goals')


# --- ChatMessage Model ---
class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender = db.Column(db.String(10), nullable=False)  # 'user' or 'ai'
    message = db.Column(db.Text, nullable=False)
    time_str = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='chat_messages')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Register')


# Helper function for authentication (OPTIONAL now)
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Optional: Allow access even without login
        return f(*args, **kwargs)
    return decorated_function


# Gemini AI helper function
def get_gemini_response(chat_history: list) -> str:
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY is not set."

    api_contents = []
    for turn in chat_history:
        role = "user" if turn["sender"] == "user" else "model"
        api_contents.append({"role": role, "parts": [{"text": turn["message"]}]})

    payload = {
        "contents": api_contents,
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}
    }
    headers = {"Content-Type": "application/json"}

    max_retries = 3
    delay = 1

    for attempt in range(max_retries):
        try:
            response = http_requests.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                json=payload,
                headers=headers
            )

            if response.status_code == 200:
                data = response.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
                if text:
                    return text.strip()
                else:
                    return "AI Response Error: Received an empty response."

            elif response.status_code == 429:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                else:
                    return "Connection Error: API rate limit exceeded after multiple retries."
            else:
                return f"API returned error {response.status_code}: {response.text}"

        except http_requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            else:
                return f"Connection Error: Could not connect to Gemini API after all retries. ({e})"

    return "Connection Error: Failed to get a response after all attempts."


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    # If already logged in, redirect to home
    if session.get('user_id'):
        return redirect(url_for('home'))

    # Google login URL setup (MUST be done before form validation check for initial load)
    google_login_url = None
    # Check if 'flow' object (from OAuth setup) exists before accessing it
    if 'flow' in globals() and flow:
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        google_login_url = authorization_url

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and user.password and check_password_hash(user.password, form.password.data):
            # Log user in
            session['user_id'] = user.id
            session['user_email'] = user.email

            # Flash success message
            flash("Logged in successfully!", "success")

            # CRITICAL FIX: Redirect to the login page to display the flash message
            # and trigger the JavaScript animation before the final redirect to 'home'.
            return redirect(url_for('login'))

        elif user:
            flash("Invalid password. Try again.", "danger")
        else:
            flash("Email not found. Please register first.", "warning")
            return redirect(url_for('register'))

    # Pass the Google URL to the template on initial load or failure
    return render_template('login.html', form=form, google_login_url=google_login_url)


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    # Google login URL setup (copied from /login to ensure the link works on this page too)
    google_login_url = None
    if 'flow' in globals() and flow:
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        google_login_url = authorization_url

    if form.validate_on_submit():
        # Check if email or username already exists
        if User.query.filter_by(email=form.email.data).first():
            flash("Email already registered. Please login.", "danger")
            return redirect(url_for('login'))

        if User.query.filter_by(username=form.username.data).first():
            flash("Username already taken. Choose another.", "danger")
            # Keep form data on redirect if possible, or just redirect back
            return redirect(url_for('register'))

            # Hash password and create user
        hashed_password = generate_password_hash(form.password.data)
        new_user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_password
        )
        db.session.add(new_user)
        db.session.commit()

        # Automatically log in the user
        session['user_id'] = new_user.id
        session['user_email'] = new_user.email
        session['username'] = new_user.username

        flash("Account created! Logged in successfully.", "success")

        # CRITICAL FIX: Redirect to the register page to display the flash message
        # and trigger the JavaScript animation before the final redirect to 'home'.
        return redirect(url_for('register'))

    # Pass the form and Google URL to the template on initial load or failure
    return render_template('register.html', form=form, google_login_url=google_login_url)


# ... all imports and database setup remain the same ...

@app.route('/callback')
def callback():
    if not flow:
        flash("Google OAuth is not configured.", "warning")
        return redirect(url_for('login'))

    try:
        # Step 1: Fetch the token using the authorization response
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        # Handle token fetch errors (e.g., state mismatch)
        flash(f"Google login failed: {str(e)}", "danger")
        return redirect(url_for('login'))

    credentials = flow.credentials

    # Step 2: Verify the ID token and get user info
    request_session = google.auth.transport.requests.Request()
    id_info = google.oauth2.id_token.verify_oauth2_token(
        credentials.id_token, request_session, GOOGLE_CLIENT_ID
    )

    email = id_info.get("email")
    # Get the user's name from the Google profile, or use the email prefix as a fallback
    name_from_google = id_info.get("name", email.split('@')[0])

    # Step 3: Check if user exists
    user = User.query.filter_by(email=email).first()

    if not user:
        # --- CRITICAL FIX: Ensure Unique and Non-Null Username ---
        base_username = name_from_google.replace(" ", "").lower()
        username = base_username
        counter = 1

        # Check for username conflict (REQUIRED if username is unique in DB)
        while User.query.filter_by(username=username).first():
            username = f"{base_username}{counter}"
            counter += 1

        # Create new user with a unique username and NO password
        new_user = User(email=email, password=None, username=username)
        db.session.add(new_user)
        db.session.commit()
        user = new_user
        flash(f"Welcome, {user.username}! Account created via Google.", "success")

    # Step 4: Log the user in
    session['user_id'] = user.id
    session['user_email'] = user.email
    session['username'] = user.username  # Ensure username is set in session

    flash(f"Logged in as {user.username} via Google!", "success")
    return redirect(url_for('home'))


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        # User confirmed logout
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for('home'))

    # GET request: show confirmation page
    return render_template('logout_confirm.html')


@app.route('/')
@login_required
def home():
    user_id = session.get('user_id')

    # Get today's entries from database
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == user_id,
        JournalEntry.created_at >= today_start
    ).order_by(JournalEntry.created_at.desc()).all()

    # Convert to dict format for template
    entries_list = [{
        'text': entry.text,
        'sentiment': entry.sentiment,
        'time': entry.time_str
    } for entry in entries]

    return render_template(
        'home.html',
        entries=entries_list,
        current_page='home',
        sentiment_map=sentiment_map
    )


@app.route('/save-entry', methods=['POST'])
@login_required
@limiter.limit("50 per hour")
def save_entry():
    user_id = session.get('user_id')
    entry_text = request.form.get('entry')

    if entry_text:
        # Create new journal entry in database
        new_entry = JournalEntry(
            user_id=user_id,
            text=entry_text,
            sentiment=0,  # You can add sentiment analysis here
            time_str=time.strftime("%I:%M %p")
        )
        db.session.add(new_entry)
        db.session.commit()

        flash("Entry saved successfully!", "success")

    return redirect(url_for('home'))



# ... other imports (Flask, render_template, request, session, redirect, url_for, login_required)

# --- Helper Functions (Re-added for robust ID-based management) ---
def find_goal_by_id(goals_list, goal_id):
    """Finds a goal dictionary in the list by its unique ID."""
    # Note: goal_id from the route is an integer, so we ensure the stored ID is an int too.
    return next((g for g in goals_list if g.get('id') == goal_id), None)


def generate_goal_id():
    """Generates a sufficiently unique short integer ID for the goal."""
    return int(uuid.uuid4().int % 1000000)

@app.route('/goals')
@login_required
def goals():
    user_id = session.get('user_id')

    # Get all goals for the user
    all_goals = Goal.query.filter_by(user_id=user_id).order_by(Goal.created_at.desc()).all()

    # Split into current and completed
    current_goals = [g for g in all_goals if not g.completed]
    completed_goals_list = [g for g in all_goals if g.completed]

    total_goals = len(all_goals)
    completed_goals_count = len(completed_goals_list)
    progress_percent = int((completed_goals_count / total_goals) * 100) if total_goals > 0 else 0

    return render_template(
        'goals.html',
        current_page='goals',
        goals_list=current_goals,
        completed_goals_list=completed_goals_list,
        total_goals=total_goals,
        completed_goals=completed_goals_count,
        progress_percent=progress_percent
    )


@app.route('/add-goal', methods=['POST'])
@login_required
def add_goal():
    user_id = session.get('user_id')
    goal_text = request.form.get('goal')
    deadline = request.form.get('deadline')
    reason = request.form.get('reason')

    if goal_text:
        new_goal = Goal(
            user_id=user_id,
            text=goal_text,
            completed=False,
            deadline=deadline if deadline else None,
            reason=reason if reason else None
        )
        db.session.add(new_goal)
        db.session.commit()

        flash("Goal added successfully!", "success")

    return redirect(url_for('goals'))


@app.route('/toggle-goal/<int:goal_id>', methods=['POST'])
@login_required
def toggle_goal(goal_id):
    user_id = session.get('user_id')
    goal = Goal.query.filter_by(id=goal_id, user_id=user_id).first()

    if goal:
        goal.completed = not goal.completed

        if goal.completed:
            goal.completed_date = datetime.now().strftime('%Y-%m-%d')
        else:
            goal.completed_date = None

        db.session.commit()
        flash("Goal updated!", "success")

    return redirect(url_for('goals'))



@app.route('/delete-goal/<int:goal_id>', methods=['POST'])
@login_required
def delete_goal(goal_id):
    user_id = session.get('user_id')
    goal = Goal.query.filter_by(id=goal_id, user_id=user_id).first()

    if goal:
        db.session.delete(goal)
        db.session.commit()
        flash("Goal deleted successfully!", "success")

    return redirect(url_for('goals'))


@app.route('/generate-insights-summary', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def generate_insights_summary():
    """Generate AI-powered motivational summary for insights page"""
    try:
        data = request.get_json()

        total_entries = data.get('total_entries', 0)
        goals_completed = data.get('goals_completed', 0)
        total_goals = data.get('total_goals', 0)
        progress_rate = data.get('progress_rate', 0)
        current_streak = data.get('current_streak', 0)

        # Create a formatted metrics string
        user_metrics = f"Journal Entries: {total_entries}, Goals Completed: {goals_completed} out of {total_goals} ({progress_rate}%), Current Streak: {current_streak} days."

        # Create a custom chat history for insights summary
        insights_chat = [
            {
                "sender": "user",
                "message": f"Generate a motivational performance summary based on these metrics: {user_metrics}. Write a concise, two-paragraph report. Paragraph 1: Summarize current efforts, highlighting the highest metric as a primary win. Paragraph 2: Provide one clear, actionable focus area for the next week. Use markdown formatting."
            }
        ]

        # Use your existing get_gemini_response function
        ai_response = get_gemini_response(insights_chat)

        # Check if response is an error
        if ai_response.startswith("Error:") or ai_response.startswith("Connection Error:") or ai_response.startswith(
                "API Response Error:"):
            return jsonify({
                'success': False,
                'error': ai_response
            })

        return jsonify({
            'success': True,
            'summary': ai_response
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Server error: {str(e)}"
        })






from datetime import date, timedelta

@app.route('/insights')
def insights():
    user_id = session.get('user_id')

    # Get journal entries sorted by creation time
    entries = JournalEntry.query.filter_by(user_id=user_id).order_by(JournalEntry.created_at.desc()).all()
    total_entries = len(entries)

    # Goals data
    goals_list = Goal.query.filter_by(user_id=user_id).all()
    total_goals = len(goals_list)
    completed_goals = sum(1 for g in goals_list if g.completed)
    progress_percent = int((completed_goals / total_goals) * 100) if total_goals > 0 else 0

    # --- Current Streak Calculation ---
    current_streak = 0
    if entries:
        # Set of dates with entries
        entry_dates = set(e.created_at.date() for e in entries)

        today = date.today()
        check_date = today if today in entry_dates else today - timedelta(days=1)

        while check_date in entry_dates:
            current_streak += 1
            check_date -= timedelta(days=1)

    # --- Weekly Entries Distribution (Mon-Sun) ---
    weekly_entries = [0] * 7
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())  # Monday

    for e in entries:
        entry_date = e.created_at.date()
        if start_of_week <= entry_date <= today:
            day_index = entry_date.weekday()  # 0=Mon, 6=Sun
            weekly_entries[day_index] += 1

    return render_template(
        'insights.html',
        current_page='insights',
        total_entries=total_entries,
        total_goals=total_goals,
        completed_goals=completed_goals,
        progress_percent=progress_percent,
        current_streak=current_streak,
        weekly_entries=weekly_entries
    )














# --- Configuration (Simulated for this environment) ---
# In a real environment, these would be set up via environment variables.
# We must use os.environ.get to access these values securely.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_URL = os.environ.get('GEMINI_API_URL')
GEMINI_MODEL_NAME = "gemini-2.5-flash-preview-09-2025"
SYSTEM_PROMPT = "You are a helpful assistant."


# --- Security Decorator Fix ---
def login_required(f):
    @wraps(f)  # FIX: This preserves the original function name for Flask endpoints
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # Assuming you have a route named 'login'
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# --- Helper Function for Server-Side AI Call ---

def get_gemini_response_server(
        user_prompt: str,
        system_instruction: str,
        response_mime_type: str = "text/plain",
        response_schema: dict = None,
        tools: list = None
) -> dict:
    """
    Handles secure, server-side calls to the Gemini API, including retries.
    Returns a dictionary containing the response text and status.
    """
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY is not set.")
        return {"status": "error", "message": "API key not configured on server."}

    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]}
    }

    generation_config = {"responseMimeType": response_mime_type}

    if response_schema:
        generation_config["responseSchema"] = response_schema

    if tools:
        payload["tools"] = tools

    payload["generationConfig"] = generation_config

    headers = {"Content-Type": "application/json"}

    max_retries = 3
    delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            # Construct the API URL with the key securely on the server
            response = requests.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                json=payload,
                headers=headers
            )

            if response.status_code == 200:
                data = response.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
                if text:
                    return {"status": "success", "text": text.strip()}
                else:
                    return {"status": "error", "message": "AI Response Error: Received an empty response."}

            elif response.status_code == 429:
                print(f"Rate limit hit. Retrying in {delay}s...")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                else:
                    return {"status": "error", "message": "API rate limit exceeded after multiple retries."}
            else:
                # Log the detailed error from the server
                print(f"API returned error {response.status_code}: {response.text}")
                return {"status": "error", "message": f"API Error: {response.status_code} - {response.text}"}

        except requests.exceptions.RequestException as e:
            print(f"Connection Error: {e}. Retrying in {delay}s...")
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            else:
                return {"status": "error",
                        "message": f"Connection Error: Failed to connect to Gemini API after all retries. ({e})"}

    return {"status": "error", "message": "Connection Error: Failed to get a response after all attempts."}




@app.route('/mind-space')
@login_required
def mind_space():
    return render_template('mind_space.html', current_page='mind_space')


@app.route("/ai-support", methods=["GET", "POST"])
@login_required
@limiter.limit("100 per hour")
def ai_support():
    user_id = session.get('user_id')
    # Use request.args for GET parameters
    analysis_text = request.args.get('analyze_text')

    # --- 1. Handle incoming analysis request from the 'home' page (GET request) ---
    if analysis_text:
        # Check if the last conversation turn was already about this entry to prevent duplicates on refresh.
        user_input_check = f"Please read and help me reflect on this journal entry: \"{analysis_text}\""
        last_user_msg = ChatMessage.query.filter_by(user_id=user_id, sender='user').order_by(
            ChatMessage.created_at.desc()).first()

        if not last_user_msg or last_user_msg.message.strip() != user_input_check.strip():
            # 1a. Create the user's simulated message (the entry prompt)
            user_input = user_input_check
            current_time = datetime.now().strftime("%I:%M %p")

            user_message = ChatMessage(
                user_id=user_id,
                sender='user',
                message=user_input,
                time_str=current_time
            )
            db.session.add(user_message)
            db.session.flush()  # Ensures the new message is available for the AI's context history query

            # 1b. Define prompt for AI to analyze the entry
            # MODIFIED: Added strict length and format rules to ensure a concise response (max 3 sentences).
            analysis_prompt = (
                f"The user has submitted a journal entry for reflection: \"{analysis_text}\". "
                f"Respond in a supportive and conversational tone. Your response **must be extremely concise, no more than 3 sentences long**. "
                f"First, briefly acknowledge the entry's content (even if it is non-conventional). "
                f"Second, ask **ONE single, specific, open-ended question** to encourage deeper reflection."
            )


            # Get the complete history including the new user message
            # The AI model needs the full history, but we use the custom analysis_prompt for the AI's turn
            chat_history_db = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
            chat_for_ai = [{"sender": msg.sender, "message": msg.message} for msg in chat_history_db[:-1]]
            # Replace the user's last message with the strict instruction for the AI model
            chat_for_ai.append({"sender": "user", "message": analysis_prompt})


            # Get AI response
            try:
                ai_response = get_gemini_response(chat_for_ai)
            except Exception as e:
                ai_response = "I encountered an error trying to analyze your entry. Please try again."
                print(f"AI Generation Error: {e}")


            # 1c. Save AI response
            ai_message = ChatMessage(
                user_id=user_id,
                sender='ai',
                message=ai_response,
                time_str=datetime.now().strftime("%I:%M %p")
            )
            db.session.add(ai_message)
            db.session.commit()

            flash("AI has analyzed your entry! Continue your conversation below.", "success")

        # Redirect to the clean URL (without the analyze_text parameter) to prevent re-submitting on refresh
        return redirect(url_for("ai_support"))

    # --- 2. Handle standard POST requests (user typing a new message) ---
    if request.method == "POST":
        user_input = request.form.get("user_input", "").strip()
        if user_input:
            current_time = datetime.now().strftime("%I:%M %p")

            # Save user message to database
            user_message = ChatMessage(
                user_id=user_id,
                sender='user',
                message=user_input,
                time_str=current_time
            )
            db.session.add(user_message)
            db.session.flush()

            # Get chat history for AI context (including the new user input)
            chat_history_db = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
            chat_for_ai = [{"sender": msg.sender, "message": msg.message} for msg in chat_history_db]

            # Get AI response
            try:
                ai_response = get_gemini_response(chat_for_ai)
            except Exception as e:
                ai_response = "I encountered an error responding to your message. Please try again."
                print(f"AI Generation Error: {e}")

            # Save AI response to database
            ai_message = ChatMessage(
                user_id=user_id,
                sender='ai',
                message=ai_response,
                time_str=datetime.now().strftime("%I:%M %p")
            )
            db.session.add(ai_message)
            db.session.commit()

            return redirect(url_for("ai_support"))

    # --- 3. Handle standard GET request (display chat history) ---
    chat_history_db = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
    chat_history = [{
        'sender': msg.sender,
        'message': msg.message,
        'time': msg.time_str
    } for msg in chat_history_db]

    return render_template("ai-support.html", chat_history=chat_history, current_page='ai_support')


@app.route("/clear-chat")
@login_required
def clear_chat():
    user_id = session.get('user_id')

    # Delete all chat messages for this user
    ChatMessage.query.filter_by(user_id=user_id).delete()
    db.session.commit()

    flash("Chat history cleared!", "info")
    return redirect(url_for("ai_support"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
