from flask import request, render_template, session, redirect, url_for, flash
from app import app
import plotly.express as px
import pandas as pd

@app.route("/plotly-graphs/")
def plotly_graphs():
    if 'email' in session:
        df = px.data.iris() # iris is a pandas DataFrame
        fig = px.scatter(df, x="sepal_width", y="sepal_length")
        graph = fig.to_html()
        return render_template("/integrations/plotly-graphs-example.html", graph=graph)
    
    # if email is not in session
    flash('Please Sign In.')
    return redirect(url_for('signin'))