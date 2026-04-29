from flask import request, render_template, session, redirect, url_for, flash
from app import app
from app.openai_utils import get_openai_client

@app.route('/openai/', methods=['POST', 'GET'])
def get_completion():
    #check if the user is logged in by checking if email is in session
    if 'email' in session:
        # POST request
        if request.method == 'POST':
            
            print('OpenAI function started')
            system_prompt = request.form.get('system_prompt')
            user_prompt = request.form.get('user_prompt')
            task_prompt = request.form.get('task_prompt')
            
            client = get_openai_client()
            if not client:
                return "OpenAI client could not be initialized. Please set OPENAI_API_KEY environment variable."

            try:
                completion = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": str(user_prompt) + str(task_prompt)},
                        ]
                        )
                return completion.choices[0].message.content
            except Exception as e:
                return f"Error from OpenAI: {str(e)}"
        
        # GET request
        return render_template('/integrations/openai-example.html')
    
    # If email is not in session
    return redirect(url_for('signin'))