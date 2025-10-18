# Life Journal - Personal Wellness Application

A Flask-based personal journaling and wellness application with AI-powered emotional support, goal tracking, mindfulness exercises, and comprehensive insights.

## Features

- **Daily Journaling**: Write and track daily journal entries with sentiment analysis
- **AI Support**: Chat with an empathetic AI companion powered by Google's Gemini API
- **Goal Management**: Set, track, and complete personal goals with deadlines
- **Mind Space**: Access guided wellness exercises including:
  - 5-minute breathing exercises
  - Gratitude practice
  - Mindfulness meditation
- **Insights Dashboard**: Visual analytics of your journaling habits and goal progress
- **Google OAuth**: Sign in with Google or traditional email/password authentication

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite with SQLAlchemy ORM
- **Authentication**: Flask-Login, Google OAuth 2.0
- **ML/AI**: 
  - Scikit-learn (sentiment analysis)
  - Google Gemini API (conversational AI)
- **Frontend**: HTML, CSS, JavaScript
- **Charts**: Chart.js
- **Forms**: Flask-WTF, WTForms

## Prerequisites

- Python 3.8+
- pip (Python package manager)
- Google Cloud Project (for OAuth and Gemini API)

## Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd life-journal
```

2. **Create a virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Set up environment variables**

Create a `.env` file in the root directory (see `.env.example` for template):

```env
SECRET_KEY=your-secret-key-here
GEMINI_API_KEY=your-gemini-api-key
GOOGLE_CLIENT_ID=your-google-client-id
REDIRECT_URI=http://127.0.0.1:5000/callback
```

5. **Set up Google OAuth**

Download your `client_secret.json` from Google Cloud Console and place it in the root directory.

6. **Initialize the database**
```bash
python app.py
```

The database will be created automatically on first run.

## Configuration

### Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URIs:
   - `http://127.0.0.1:5000/callback`
   - `http://localhost:5000/callback`
6. Download the JSON file and save as `client_secret.json`

### Gemini API Setup

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create an API key
3. Add it to your `.env` file as `GEMINI_API_KEY`

## Usage

1. **Start the application**
```bash
python app.py
```

2. **Access the application**
Open your browser and navigate to `http://127.0.0.1:5000`

3. **Register/Login**
- Sign up with email/password
- Or use Google OAuth for quick access

4. **Features**
- **Journal**: Write daily entries on the home page
- **AI Support**: Get emotional support and reflection guidance
- **Goals**: Set and track personal goals
- **Mind Space**: Access wellness exercises
- **Insights**: View your progress analytics

## Project Structure

```
life-journal/
├── app.py                  # Main application file
├── models/                 # ML models directory
│   ├── tweet_sentiment_model.pkl
│   └── tfidf_vectorizer.pkl
├── templates/              # HTML templates
│   ├── home.html
│   ├── ai-support.html
│   ├── goals.html
│   ├── mind_space.html
│   ├── insights.html
│   ├── login.html
│   ├── register.html
│   └── logout_confirm.html
├── static/
│   └── css/
│       └── styles.css
├── .env                    # Environment variables (not tracked)
├── .env.example           # Environment template
├── .gitignore             # Git ignore rules
├── client_secret.json     # Google OAuth config (not tracked)
├── mydatabase.db          # SQLite database (not tracked)
├── requirements.txt       # Python dependencies
├── LICENSE                # MIT License
└── README.md              # This file
```

## Database Models

### User
- `id`: Primary key
- `username`: Unique username
- `email`: Unique email address
- `password`: Hashed password (nullable for OAuth users)

### JournalEntry
- Links to User
- Contains text, sentiment, and timestamp

### Goal
- Links to User
- Tracks goals with deadlines, completion status

### ChatMessage
- Links to User
- Stores AI conversation history

## API Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Home/Journal page |
| `/login` | GET, POST | Login page |
| `/register` | GET, POST | Registration page |
| `/callback` | GET | Google OAuth callback |
| `/logout` | GET, POST | Logout confirmation |
| `/save-entry` | POST | Save journal entry |
| `/ai-support` | GET, POST | AI chat interface |
| `/clear-chat` | GET | Clear chat history |
| `/goals` | GET | Goals dashboard |
| `/add-goal` | POST | Add new goal |
| `/toggle-goal/<id>` | POST | Toggle goal completion |
| `/delete-goal/<id>` | POST | Delete goal |
| `/mind-space` | GET | Wellness exercises |
| `/insights` | GET | Analytics dashboard |
| `/generate-insights-summary` | POST | AI-generated summary |

## Security Notes

- Never commit `.env` or `client_secret.json`
- Use strong, unique `SECRET_KEY` in production
- Enable HTTPS in production (remove `OAUTHLIB_INSECURE_TRANSPORT`)
- Regularly update dependencies
- Review Google OAuth scopes periodically

## Development

To run in development mode:
```bash
export FLASK_ENV=development  # On Windows: set FLASK_ENV=development
python app.py
```

## Production Deployment

1. Set `OAUTHLIB_INSECURE_TRANSPORT=0` (or remove it)
2. Use a production WSGI server (Gunicorn, uWSGI)
3. Set up proper database (PostgreSQL, MySQL)
4. Configure reverse proxy (Nginx, Apache)
5. Use environment variables for secrets
6. Enable HTTPS

## Troubleshooting

**Google OAuth fails**
- Check `client_secret.json` is present
- Verify redirect URI in Google Console matches your app
- Ensure Google+ API is enabled

**AI responses fail**
- Verify `GEMINI_API_KEY` is set correctly
- Check API quota limits
- Review network connectivity

**Database errors**
- Delete `mydatabase.db` and restart app
- Check file permissions

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request


## Contributors

- **Ameer Pasha** – Developed the application ([GitHub](https://github.com/Ameer-pasha))
- **Faizan** – UI/UX and design ([GitHub](https://github.com/shaikzan))  
- **Prince** – Idea conception  ([GitHub](https://github.com/Prince649294u83))  
- **Tarun** – Feature suggestions



## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Google Gemini API for AI capabilities
- Chart.js for data visualization
- Flask community for excellent documentation

## Support

For issues and questions:
- Open an issue on GitHub
- Check existing documentation
- Review Flask and Google OAuth documentation

---

**Made with ❤️ for mental wellness and personal growth**