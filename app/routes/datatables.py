from flask import request, render_template, session, redirect, url_for
from app import app
import pandas as pd 
import plotly.express as px

@app.route("/datatables/")
def datatables():
    #check if the user is logged in by checking if email is in session
    if 'email' in session:
        df = px.data.iris()  
        return render_template("/integrations/datatables-example.html", df=df.to_dict('records'))
    
    # If email is not in session
    return redirect(url_for('signin'))