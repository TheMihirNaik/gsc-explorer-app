from flask import request, render_template, session, redirect, url_for
from app import app


@app.route('/recieve-feedback/', methods=['POST', 'GET'])
def recieve_feedback():
    if request.method == 'POST':
        customer_message = request.form.get('customer_message')
        print(customer_message)
        return 'Thank you for your feedback!'
    
    # GET request
    return redirect(url_for('signin'))

# The issue with the code is that the return statement on the POST request is returning an f-string which is not valid. The return statement should return a string or a response object.
