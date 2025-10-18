# Standard library imports
import os
import time
from datetime import datetime, date, timedelta
from functools import wraps

# Third-party imports
import requests
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
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

if os.environ.get('FLASK_ENV') == 'development':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

class Base(DeclarativeBase):
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# Rate limiter
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

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Sentiment mapping (for future use)
sentiment_map = {0: "Neutral 🤔", 1: "Positive 😊", -1: "Negative 💛"}


# --- Database Models ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True)
    
    # Relationships
    entries = db.relationship('JournalEntry', back_populates='user', cascade='all, delete-orphan')
    goals = db.relationship('Goal', back_populates='user', cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', back_populates='user', cascade='all, delete-orphan')


class JournalEntry(db.Model):
    __tablename__ = 'journal_entries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    time_str = db.Column(db.String(20))

    user = db.relationship('User', back_populates='entries')


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


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender = db.Column(db.String(10), nullable=False)
    message = db.Column(db.Text, nullable=False)
    time_str = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='chat_messages')


# --- Forms ---
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Register')


# --- Helper Functions ---
def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_gemini_response(chat_history: list) -> str:
    """Get AI response from Gemini API"""
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
            response = requests.post(
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

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            else:
                return f"Connection Error: Could not connect to Gemini API after all retries. ({e})"

    return "Connection Error: Failed to get a response after all attempts."


# --- Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if session.get('user_id'):
        return redirect(url_for('home'))

    google_login_url = None
    if flow:
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        google_login_url = authorization_url

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and user.password and check_password_hash(user.password, form.password.data):
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['username'] = user.username
            flash("Logged in successfully!", "success")
            return redirect(url_for('home'))
        elif user:
            flash("Invalid password. Try again.", "danger")
        else:
            flash("Email not found. Please register first.", "warning")
            return redirect(url_for('register'))

    return render_template('login.html', form=form, google_login_url=google_login_url)


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    google_login_url = None
    if flow:
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        google_login_url = authorization_url

    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("Email already registered. Please login.", "danger")
            return redirect(url_for('login'))

        if User.query.filter_by(username=form.username.data).first():
            flash("Username already taken. Choose another.", "danger")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(form.password.data)
        new_user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_password
        )
        db.session.add(new_user)
        db.session.commit()

        session['user_id'] = new_user.id
        session['user_email'] = new_user.email
        session['username'] = new_user.username

        flash("Account created! Logged in successfully.", "success")
        return redirect(url_for('home'))

    return render_template('register.html', form=form, google_login_url=google_login_url)


@app.route('/callback')
def callback():
    if not flow:
        flash("Google OAuth is not configured.", "warning")
        return redirect(url_for('login'))

    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        flash(f"Google login failed: {str(e)}", "danger")
        return redirect(url_for('login'))

    credentials = flow.credentials

    request_session = google.auth.transport.requests.Request()
    id_info = google.oauth2.id_token.verify_oauth2_token(
        credentials.id_token, request_session, GOOGLE_CLIENT_ID
    )

    email = id_info.get("email")
    name_from_google = id_info.get("name", email.split('@')[0])

    user = User.query.filter_by(email=email).first()

    if not user:
        base_username = name_from_google.replace(" ", "").lower()
        username = base_username
        counter = 1

        while User.query.filter_by(username=username).first():
            username = f"{base_username}{counter}"
            counter += 1

        new_user = User(email=email, password=None, username=username)
        db.session.add(new_user)
        db.session.commit()
        user = new_user
        flash(f"Welcome, {user.username}! Account created via Google.", "success")

    session['user_id'] = user.id
    session['user_email'] = user.email
    session['username'] = user.username

    flash(f"Logged in as {user.username} via Google!", "success")
    return redirect(url_for('home'))


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for('home'))
    return render_template('logout_confirm.html')


@app.route('/')
@login_required
def home():
    user_id = session.get('user_id')

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == user_id,
        JournalEntry.created_at >= today_start
    ).order_by(JournalEntry.created_at.desc()).all()

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
        new_entry = JournalEntry(
            user_id=user_id,
            text=entry_text,
            sentiment=0,
            time_str=time.strftime("%I:%M %p")
        )
        db.session.add(new_entry)
        db.session.commit()
        flash("Entry saved successfully!", "success")

    return redirect(url_for('home'))


@app.route('/goals')
@login_required
def goals():
    user_id = session.get('user_id')

    all_goals = Goal.query.filter_by(user_id=user_id).order_by(Goal.created_at.desc()).all()

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


@app.route('/insights')
@login_required
def insights():
    user_id = session.get('user_id')

    entries = JournalEntry.query.filter_by(user_id=user_id).order_by(JournalEntry.created_at.desc()).all()
    total_entries = len(entries)

    goals_list = Goal.query.filter_by(user_id=user_id).all()
    total_goals = len(goals_list)
    completed_goals = sum(1 for g in goals_list if g.completed)
    progress_percent = int((completed_goals / total_goals) * 100) if total_goals > 0 else 0

    current_streak = 0
    if entries:
        entry_dates = set(e.created_at.date() for e in entries)
        today = date.today()
        check_date = today if today in entry_dates else today - timedelta(days=1)

        while check_date in entry_dates:
            current_streak += 1
            check_date -= timedelta(days=1)

    weekly_entries = [0] * 7
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    for e in entries:
        entry_date = e.created_at.date()
        if start_of_week <= entry_date <= today:
            day_index = entry_date.weekday()
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


@app.route('/generate-insights-summary', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def generate_insights_summary():
    try:
        data = request.get_json()

        total_entries = data.get('total_entries', 0)
        goals_completed = data.get('goals_completed', 0)
        total_goals = data.get('total_goals', 0)
        progress_rate = data.get('progress_rate', 0)
        current_streak = data.get('current_streak', 0)

        user_metrics = f"Journal Entries: {total_entries}, Goals Completed: {goals_completed} out of {total_goals} ({progress_rate}%), Current Streak: {current_streak} days."

        insights_chat = [
            {
                "sender": "user",
                "message": f"Generate a motivational performance summary based on these metrics: {user_metrics}. Write a concise, two-paragraph report. Paragraph 1: Summarize current efforts, highlighting the highest metric as a primary win. Paragraph 2: Provide one clear, actionable focus area for the next week. Use markdown formatting."
            }
        ]

        ai_response = get_gemini_response(insights_chat)

        if ai_response.startswith("Error:") or ai_response.startswith("Connection Error:") or ai_response.startswith("API Response Error:"):
            return jsonify({'success': False, 'error': ai_response})

        return jsonify({'success': True, 'summary': ai_response})

    except Exception as e:
        return jsonify({'success': False, 'error': f"Server error: {str(e)}"})


@app.route('/mind-space')
@login_required
def mind_space():
    return render_template('mind_space.html', current_page='mind_space')


@app.route("/ai-support", methods=["GET", "POST"])
@login_required
@limiter.limit("100 per hour")
def ai_support():
    user_id = session.get('user_id')
    analysis_text = request.args.get('analyze_text')

    if analysis_text:
        user_input_check = f"Please read and help me reflect on this journal entry: \"{analysis_text}\""
        last_user_msg = ChatMessage.query.filter_by(user_id=user_id, sender='user').order_by(
            ChatMessage.created_at.desc()).first()

        if not last_user_msg or last_user_msg.message.strip() != user_input_check.strip():
            user_input = user_input_check
            current_time = datetime.now().strftime("%I:%M %p")

            user_message = ChatMessage(
                user_id=user_id,
                sender='user',
                message=user_input,
                time_str=current_time
            )
            db.session.add(user_message)
            db.session.flush()

            analysis_prompt = (
                f"The user has submitted a journal entry for reflection: \"{analysis_text}\". "
                f"Respond in a supportive and conversational tone. Your response **must be extremely concise, no more than 3 sentences long**. "
                f"First, briefly acknowledge the entry's content (even if it is non-conventional). "
                f"Second, ask **ONE single, specific, open-ended question** to encourage deeper reflection."
            )

            chat_history_db = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
            chat_for_ai = [{"sender": msg.sender, "message": msg.message} for msg in chat_history_db[:-1]]
            chat_for_ai.append({"sender": "user", "message": analysis_prompt})

            try:
                ai_response = get_gemini_response(chat_for_ai)
            except Exception as e:
                ai_response = "I encountered an error trying to analyze your entry. Please try again."
                print(f"AI Generation Error: {e}")

            ai_message = ChatMessage(
                user_id=user_id,
                sender='ai',
                message=ai_response,
                time_str=datetime.now().strftime("%I:%M %p")
            )
            db.session.add(ai_message)
            db.session.commit()

            flash("AI has analyzed your entry! Continue your conversation below.", "success")

        return redirect(url_for("ai_support"))

    if request.method == "POST":
        user_input = request.form.get("user_input", "").strip()
        if user_input:
            current_time = datetime.now().strftime("%I:%M %p")

            user_message = ChatMessage(
                user_id=user_id,
                sender='user',
                message=user_input,
                time_str=current_time
            )
            db.session.add(user_message)
            db.session.flush()

            chat_history_db = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
            chat_for_ai = [{"sender": msg.sender, "message": msg.message} for msg in chat_history_db]

            try:
                ai_response = get_gemini_response(chat_for_ai)
            except Exception as e:
                ai_response = "I encountered an error responding to your message. Please try again."
                print(f"AI Generation Error: {e}")

            ai_message = ChatMessage(
                user_id=user_id,
                sender='ai',
                message=ai_response,
                time_str=datetime.now().strftime("%I:%M %p")
            )
            db.session.add(ai_message)
            db.session.commit()

            return redirect(url_for("ai_support"))

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
    ChatMessage.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    flash("Chat history cleared!", "info")
    return redirect(url_for("ai_support"))


# Initialize database tables on startup
with app.app_context():
    db.create_all()
    
if __name__ == "__main__":
    with app.app_context():
        db.drop_all()  # Add this line
        db.create_all()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
