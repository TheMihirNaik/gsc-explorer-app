from flask import Flask
#from pymongo import MongoClient
from datetime import timedelta

import os
from dotenv import load_dotenv

dotenv_path = '.env'  # Specify the path to your .env file
load_dotenv(dotenv_path)

#VALUESERP_API_KEY = os.getenv('VALUESERP_API_KEY')
#print(VALUESERP_API_KEY)
SECRET_KEY = os.getenv('SECRET_KEY')
#print(SECRET_KEY)
#MONGO_URI = os.getenv('MONGO_URI')
#print(MONGO_URI)
#MONGO_DB_NAME = os.getenv('MONGO_DB_NAME')
#print(MONGO_DB_NAME)
#OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
#print(OPENAI_API_KEY)

redis_host = os.getenv('REDIS_HOST')

# Initialize Flask app
app = Flask(__name__)

app.config['PREFERRED_URL_SCHEME'] = 'https'

# Session configuration
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=300)

# Access environment variables
app.config['SECRET_KEY'] = SECRET_KEY

# Configure logging
import logging
from logging.handlers import RotatingFileHandler
import sys

if not app.debug:
    # Set up file handler
    file_handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    
    # Set up console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    console_handler.setLevel(logging.INFO)
    app.logger.addHandler(console_handler)
    
    app.logger.setLevel(logging.INFO)
    app.logger.info('GSC Explorer startup')

# Initialize MongoDB client
#cluster = MongoClient(MONGO_URI)

# fetch a database from cluster connection
#database = cluster[MONGO_DB_NAME]

# Import OpenAI and create client
#from openai import OpenAI

#client = OpenAI(
#    api_key=OPENAI_API_KEY
#    )

# Import routes and models
from app.routes import default_routes, customer_support, datatables, plotly, gsc_api_auth, gsc_routes

