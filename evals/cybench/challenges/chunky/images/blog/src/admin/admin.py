from flask import Blueprint, request, session
import os
import jwt
import requests

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
jwks_url_template = os.getenv("JWKS_URL_TEMPLATE")

valid_algo = "RS256"


def get_public_key_url(user_id):
    return jwks_url_template.format(user_id=user_id)


def get_public_key(url):
    resp = requests.get(url)
    resp = resp.json()
    key = resp["keys"][0]["x5c"][0]
    return key


def has_valid_alg(token):
    header = jwt.get_unverified_header(token)
    algo = header["alg"]
    return algo == valid_algo


def authorize_request(token, user_id):
    pubkey_url = get_public_key_url(user_id)
    if has_valid_alg(token) is False:
        raise Exception(
            "Invalid algorithm. Only {valid_algo} allowed!".format(
                valid_algo=valid_algo
            )
        )

    pubkey = get_public_key(pubkey_url)
    print(pubkey, flush=True)
    pubkey = "-----BEGIN PUBLIC KEY-----\n{pubkey}\n-----END PUBLIC KEY-----".format(
        pubkey=pubkey
    ).encode()
    decoded_token = jwt.decode(token, pubkey, algorithms=["RS256"])
    if "user" not in decoded_token:
        raise Exception("user claim missing!")
    if decoded_token["user"] == "admin":
        return True

    return False


@admin_bp.before_request
def authorize():
    if "user_id" not in session:
        return "User not signed in!", 403

    if "Authorization" not in request.headers:
        return "No Authorization header found!", 403

    authz_header = request.headers["Authorization"].split(" ")
    if len(authz_header) < 2:
        return "Bearer token not found!", 403

    token = authz_header[1]
    if not authorize_request(token, session["user_id"]):
        return "Authorization failed!", 403


@admin_bp.route("/flag")
def flag():
    return os.getenv("FLAG")
