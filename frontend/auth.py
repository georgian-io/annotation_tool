import functools

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)
#from werkzeug.security import check_password_hash, generate_password_hash
#from main_server.db import get_db

from shared.frontend_user_password import get_frontend_user_password

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'GET':
        # This came from a sign-in link. Try to sign in this user immediately.
        username = request.args.get('username')
        password = request.args.get('password')
    elif request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

    if username is not None and password is not None:
        error = None

        # db = get_db()
        # error = None
        # user = db.execute(
        #     'SELECT * FROM user WHERE username = ?', (username,)
        # ).fetchone()

        # user = DUMMY_USER
        
        # if user is None:
        #     error = 'Incorrect username.'
        # elif not check_password_hash(user['password'], password):
        #     error = 'Incorrect password.'

        if get_frontend_user_password(username) != password:
            error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = username
            session['username'] = username
            return redirect(url_for('index'))

        flash(error)

    return render_template('auth/login.html')

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@bp.before_app_request
def load_logged_in_user():
    # user_id = session.get('user_id')

    # if user_id is None:
    #     g.user = None
    # else:
    #     g.user = get_db().execute(
    #         'SELECT * FROM user WHERE id = ?', (user_id,)
    #     ).fetchone()

    if session.get('user_id') is None:
        g.user = None
    else:
        g.user = {
            'user_id': session.get('user_id'),
            'username': str(session.get('username'))
        }

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))

        return view(**kwargs)

    return wrapped_view