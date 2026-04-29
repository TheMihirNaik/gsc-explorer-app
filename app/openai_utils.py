import os
from openai import OpenAI

def get_openai_client(api_key=None):
    """
    Returns an OpenAI client initialized with the provided API key,
    the environment variable OPENAI_API_KEY, or None if neither is available.
    """
    key = api_key or os.getenv('OPENAI_API_KEY')
    if key:
        return OpenAI(api_key=key)
    return None
