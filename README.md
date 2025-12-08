# GSC Explorer

[![Live Demo](https://img.shields.io/badge/Live%20Demo-gscexplorer.app-brightgreen)](https://www.gscexplorer.app)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0.0-green)](https://flask.palletsprojects.com/)

**GSC Explorer** is an open-source web application that extends Google Search Console's capabilities, providing advanced analytics, unlimited data access, and powerful visualization tools for SEO professionals and website owners.

## 🌟 Features

### Core Capabilities

- **🔐 Google OAuth Integration** - Secure sign-in with your Google Account
- **📊 Unlimited Data Access** - Break free from Google Search Console's 1,000-row limitation
- **🔍 Brand vs Non-Brand Query Classification** - Automatically categorize queries using configurable brand keywords
- **📈 Period Comparisons** - Pre-calculated comparisons for:
  - Current Period vs Previous Period
  - Current Period vs Previous Year
- **📉 Interactive Visualizations** - Beautiful charts and graphs powered by Plotly
- **📋 Advanced Data Tables** - Filtering, sorting, and export capabilities with DataTables

### Available Reports

1. **Sitewide Overview** - Comprehensive performance insights across different periods, countries, and devices
2. **Sitewide Queries** - Analyze search query performance with brand/non-brand classification
3. **Sitewide Pages** - Page-level performance analysis
4. **Query Aggregate Report** - Aggregated query performance metrics
5. **Organic CTR Analysis** - Click-through rate optimization insights
6. **Sitewide Analysis** - Deep-dive analysis of site performance

### Data Export

Export your data in multiple formats:
- CSV
- Excel
- PDF
- Print

## 🚀 Tech Stack

### Backend
- **Flask 3.0.0** - Web framework
- **Google API Python Client** - Google Search Console API integration
- **Pandas 2.2.2** - Data manipulation and analysis

### Frontend
- **DaisyUI + Tailwind CSS** - Modern, responsive UI framework
- **HTMX** - Dynamic interactivity without complex JavaScript
- **DataTables** - Advanced table features (filtering, sorting, pagination, export)
- **Plotly Express** - Interactive charts and visualizations

### Additional Tools
- **BeautifulSoup4** - HTML parsing
- **NLTK** - Natural language processing for query classification
- **SpaCy** - Advanced NLP capabilities
- **OpenAI API** - AI-powered insights (optional)

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.11+
- Google Cloud Project with Search Console API enabled
- OAuth 2.0 credentials (client_secrets.json)

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/gsc-explorer-app.git
cd gsc-explorer-app
```

### 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables

Create a `.env` file in the root directory:

```env
SECRET_KEY=your-secret-key-here
FLASK_ENV=development
```

### 5. Configure Google OAuth

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the Google Search Console API
3. Create OAuth 2.0 credentials
4. Download the credentials and save as `client_secrets.json` in the root directory

### 6. Run the Application

#### Development Mode

```bash
python run.py
```

The application will be available at `https://127.0.0.1:5000` (with SSL in development mode).

#### Production Mode

```bash
# Using Gunicorn
gunicorn run:app --timeout 180
```

## 🐳 Deployment

The project includes configuration for Heroku deployment:

- `Procfile` - Defines web process
- `runtime.txt` - Specifies Python version

### Heroku Deployment Steps

1. Create a Heroku app
2. Set environment variables in Heroku dashboard
3. Deploy using Git:

```bash
git push heroku main
```

## 📁 Project Structure

```
gsc-explorer-app/
├── app/
│   ├── __init__.py          # Flask app initialization
│   ├── extensions.py         # Extensions configuration
│   ├── routes/               # Route handlers
│   │   ├── default_routes.py
│   │   ├── gsc_api_auth.py
│   │   ├── gsc_routes.py
│   │   └── ...
│   ├── static/               # Static files
│   └── templates/            # Jinja2 templates
│       ├── default/
│       ├── sitewide-report/
│       ├── sitewide-queries/
│       └── ...
├── client_secrets.json       # Google OAuth credentials
├── requirements.txt          # Python dependencies
├── Procfile                  # Heroku process file
├── runtime.txt              # Python version
└── run.py                   # Application entry point
```

## 🔧 Configuration

### Brand Keywords

After signing in, configure your brand keywords in the property selection page. These keywords are used to automatically classify queries as "Brand" or "Non-Brand".

### Session Configuration

Sessions are configured with:
- 300-minute lifetime
- Secure cookies (HTTPS only)
- SameSite=Lax policy

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is open source. Please check the repository for license details.

## 🐛 Known Issues

- Development mode requires SSL certificates (`cert.pem` and `key.pem`) for OAuth to work properly
- Some MongoDB-related code is commented out but may be used in future versions

## 🔗 Links

- **Live Demo**: [gscexplorer.app](https://www.gscexplorer.app)
- **Google Search Console API**: [Documentation](https://developers.google.com/webmaster-tools)

## 🙏 Acknowledgments

- Google Search Console API
- Flask community
- All contributors and users of this project

## 📧 Support

For issues, questions, or contributions, please open an issue on the GitHub repository.

---

**Made with ❤️ for the SEO community**
