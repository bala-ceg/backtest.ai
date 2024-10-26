from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/about')
def about():
    return 'About'


@app.route('/')
def index():
    return render_template('index.html')
