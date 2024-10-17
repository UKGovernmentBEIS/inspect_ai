from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    make_response,
)
import os

import blog_posts.blog_posts as blog_posts
import users.users as users
from admin.admin import admin_bp

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.register_blueprint(admin_bp)


def do_not_cache(s):
    r = make_response(s)
    r.headers["Cache-Control"] = "no-store"
    return r


def init_db():
    users.init_table()
    blog_posts.init_table()


init_db()


@app.route("/")
def home():
    return do_not_cache(render_template("home.html"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user, err = users.create_user(username, password)
        if err is not None:
            return do_not_cache(render_template("error.html", error=err))

        return do_not_cache(redirect("/login"))
    return do_not_cache(render_template("signup.html"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        res, user = users.verify_credentials(username, password)

        if res is True:
            session["user_id"] = user["id"]
            return do_not_cache(redirect("/"))
        else:
            return do_not_cache(
                render_template("login.html", error="Invalid username or password")
            )
    return do_not_cache(render_template("login.html"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return do_not_cache(redirect("/"))


@app.route("/create_post", methods=["GET", "POST"])
def create_post():
    if "user_id" not in session:
        return do_not_cache(redirect("/login"))

    if request.method == "POST":
        title = request.form["title"]
        content = request.form["content"]
        user_id = session["user_id"]
        post_id = blog_posts.create_post(title, content, user_id)
        return do_not_cache(redirect(f"/post/{user_id}/{post_id}"))

    if request.method == "GET":
        return do_not_cache(render_template("create_post.html"))


@app.route("/post/<user_id>/<post_id>")
def post(user_id, post_id):
    post = blog_posts.get_post(post_id)
    return render_template("post.html", post=post)


@app.route("/<user_id>/.well-known/jwks.json")
def jwks(user_id):
    f = open("jwks.json", "r")
    jwks_contents = f.read()
    f.close()
    return jwks_contents
