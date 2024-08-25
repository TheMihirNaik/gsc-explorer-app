from flask import render_template, request, url_for, redirect, flash, session, jsonify
from app import app
import sys
from celery import Celery
from app.extensions import celery
from celery.result import AsyncResult

# In-memory task status storage
task_status = {}


@app.route('/task-status/<task_id>')
def task_status_view(task_id):
    result = AsyncResult(task_id, app=celery)
    
    if result.state == 'PENDING':
        task_status[task_id] = {'status': 'pending'}
        #print(result)
    elif result.state == 'SUCCESS':
        task_status[task_id] = {'status': 'completed', 'data': result.result}
        #print(result.result)
    elif result.state == 'FAILURE':
        task_status[task_id] = {'status': 'failed', 'error': str(result.result)}
        #print(result)
    #return jsonify(result.result)
    return jsonify(task_status.get(task_id, {'status': 'unknown'}))