from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, session
import json, os, uuid, requests, secrets, time
from datetime import datetime
from werkzeug.utils import secure_filename
from urllib.parse import urlencode
from dotenv import load_dotenv # Ajouté pour la sécurité

# Charge les variables du fichier .env
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Récupération sécurisée des clés et mise à jour du nom
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = "http://localhost:5000/tiktok/callback"
TIKTOK_AUTH_URL      = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL     = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_UPLOAD_URL    = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_USER_URL      = "https://open.tiktokapis.com/v2/user/info/"

for d in ['uploads/videos', 'uploads/thumbnails', 'data']:
    os.makedirs(d, exist_ok=True)

DATA_FILE  = 'data/posts.json'
TOKEN_FILE = 'data/tiktok_token.json'
ALLOWED_VID = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
ALLOWED_IMG = {'jpg', 'jpeg', 'png', 'webp'}
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024


def load_posts():
    if not os.path.exists(DATA_FILE): return []
    with open(DATA_FILE, encoding='utf-8') as f: return json.load(f)

def save_posts(posts):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

def load_token():
    if not os.path.exists(TOKEN_FILE): return None
    with open(TOKEN_FILE, encoding='utf-8') as f: return json.load(f)

def save_token(data):
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def allowed(filename, exts):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in exts

def get_valid_token():
    token = load_token()
    if not token: return None
    if time.time() > token.get('expires_at', 0) - 60:
        r = requests.post(TIKTOK_TOKEN_URL, data={
            'client_key': TIKTOK_CLIENT_KEY,
            'client_secret': TIKTOK_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': token.get('refresh_token'),
        })
        if r.status_code == 200:
            d = r.json()
            token['access_token'] = d['access_token']
            token['expires_at'] = time.time() + d.get('expires_in', 86400)
            if d.get('refresh_token'): token['refresh_token'] = d['refresh_token']
            save_token(token)
            return token['access_token']
        return None
    return token.get('access_token')


@app.route('/')
def index():
    token = load_token()
    connected = token is not None and time.time() < token.get('expires_at', 0)
    return render_template('index.html', connected=connected, tiktok_user=token if connected else None)


@app.route('/tiktok/connect')
def tiktok_connect():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    params = {
        'client_key': TIKTOK_CLIENT_KEY,
        'response_type': 'code',
        'scope': 'user.info.basic,video.upload,video.publish',
        'redirect_uri': TIKTOK_REDIRECT_URI,
        'state': state,
    }
    return redirect(f"{TIKTOK_AUTH_URL}?{urlencode(params)}")


@app.route('/tiktok/callback')
def tiktok_callback():
    code  = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    if error: return redirect('/?error=' + error)
    if state != session.get('oauth_state'): return redirect('/?error=state_mismatch')

    r = requests.post(TIKTOK_TOKEN_URL, data={
        'client_key': TIKTOK_CLIENT_KEY,
        'client_secret': TIKTOK_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': TIKTOK_REDIRECT_URI,
    })
    if r.status_code != 200: return redirect('/?error=token_failed')

    d = r.json()
    access_token = d.get('access_token')

    user_r = requests.get(
        f"{TIKTOK_USER_URL}?fields=open_id,avatar_url,display_name",
        headers={'Authorization': f'Bearer {access_token}'}
    )
    user_data = {}
    if user_r.status_code == 200:
        user_data = user_r.json().get('data', {}).get('user', {})

    save_token({
        'access_token': access_token,
        'refresh_token': d.get('refresh_token', ''),
        'expires_at': time.time() + d.get('expires_in', 86400),
        'open_id': d.get('open_id', ''),
        'username': user_data.get('display_name', 'Mon TikTok'),
        'avatar': user_data.get('avatar_url', ''),
    })
    return redirect('/?connected=1')


@app.route('/tiktok/disconnect')
def tiktok_disconnect():
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    return redirect('/')


@app.route('/api/tiktok/status')
def tiktok_status():
    token = load_token()
    if not token: return jsonify({'connected': False})
    connected = time.time() < token.get('expires_at', 0)
    return jsonify({'connected': connected, 'username': token.get('username',''), 'avatar': token.get('avatar','')})


@app.route('/api/posts/<post_id>/publish', methods=['POST'])
def publish_to_tiktok(post_id):
    access_token = get_valid_token()
    if not access_token:
        return jsonify({'success': False, 'error': 'Non connecté à TikTok.'}), 401

    posts = load_posts()
    post  = next((p for p in posts if p['id'] == post_id), None)
    if not post: return jsonify({'success': False, 'error': 'Post introuvable'}), 404

    video_path = post.get('video_path', '')
    if not video_path or not os.path.exists(video_path):
        return jsonify({'success': False, 'error': 'Fichier vidéo manquant.'}), 400

    video_size = os.path.getsize(video_path)
    caption = post.get('description', '')
    if post.get('hashtags'): caption = f"{caption}\n\n{post['hashtags']}"
    caption = caption[:2200]

    init_r = requests.post(
        TIKTOK_UPLOAD_URL,
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json; charset=UTF-8'},
        json={
            'post_info': {
                'title': caption,
                'privacy_level': 'PUBLIC_TO_EVERYONE',
                'disable_duet': False,
                'disable_comment': False,
                'disable_stitch': False,
            },
            'source_info': {
                'source': 'FILE_UPLOAD',
                'video_size': video_size,
                'chunk_size': video_size,
                'total_chunk_count': 1,
            }
        }
    )

    if init_r.status_code != 200:
        err = init_r.json()
        msg = err.get('error', {}).get('message', init_r.text)
        return jsonify({'success': False, 'error': f'Erreur TikTok: {msg}'}), 500

    init_data  = init_r.json().get('data', {})
    publish_id = init_data.get('publish_id')
    upload_url = init_data.get('upload_url')
    if not upload_url:
        return jsonify({'success': False, 'error': 'URL upload non reçue'}), 500

    with open(video_path, 'rb') as vf:
        video_bytes = vf.read()

    up_r = requests.put(
        upload_url,
        headers={
            'Content-Type': 'video/mp4',
            'Content-Range': f'bytes 0-{video_size-1}/{video_size}',
            'Content-Length': str(video_size),
        },
        data=video_bytes,
        timeout=300
    )

    if up_r.status_code not in [200, 201, 206]:
        return jsonify({'success': False, 'error': f'Erreur upload: HTTP {up_r.status_code}'}), 500

    for i, p in enumerate(posts):
        if p['id'] == post_id:
            posts[i]['status'] = 'published'
            posts[i]['published_at'] = datetime.now().isoformat()
            posts[i]['tiktok_publish_id'] = publish_id
    save_posts(posts)

    return jsonify({'success': True, 'publish_id': publish_id,
                    'message': 'Vidéo publiée avec succès !'})


@app.route('/api/posts', methods=['GET'])
def get_posts():
    posts = load_posts()
    posts.sort(key=lambda x: x.get('scheduled_at', ''))
    return jsonify(posts)

@app.route('/api/posts', methods=['POST'])
def create_post():
    posts = load_posts()
    data  = request.form.to_dict()
    post  = {
        'id': str(uuid.uuid4()),
        'title': data.get('title', ''),
        'description': data.get('description', ''),
        'hashtags': data.get('hashtags', ''),
        'scheduled_at': data.get('scheduled_at', ''),
        'status': data.get('status', 'scheduled'),
        'created_at': datetime.now().isoformat(),
        'video_path': '', 'video_name': '',
        'thumbnail_path': '', 'thumbnail_name': '',
        'tiktok_publish_id': '',
    }
    _handle_uploads(post, request)
    posts.append(post)
    save_posts(posts)
    return jsonify({'success': True, 'post': post})

@app.route('/api/posts/<post_id>', methods=['PUT'])
def update_post(post_id):
    posts = load_posts()
    data  = request.form.to_dict()
    for i, post in enumerate(posts):
        if post['id'] == post_id:
            post.update({
                'title': data.get('title', post['title']),
                'description': data.get('description', post['description']),
                'hashtags': data.get('hashtags', post['hashtags']),
                'scheduled_at': data.get('scheduled_at', post['scheduled_at']),
                'status': data.get('status', post['status']),
            })
            _handle_uploads(post, request, replace=True)
            posts[i] = post
            save_posts(posts)
            return jsonify({'success': True, 'post': post})
    return jsonify({'success': False, 'error': 'Post non trouvé'}), 404

@app.route('/api/posts/<post_id>', methods=['DELETE'])
def delete_post(post_id):
    posts = load_posts()
    new = []
    for p in posts:
        if p['id'] == post_id:
            for k in ['video_path', 'thumbnail_path']:
                if p.get(k) and os.path.exists(p[k]): os.remove(p[k])
        else:
            new.append(p)
    save_posts(new)
    return jsonify({'success': True})

@app.route('/api/posts/<post_id>/status', methods=['PATCH'])
def update_status(post_id):
    posts = load_posts()
    new_status = request.json.get('status')
    for i, p in enumerate(posts):
        if p['id'] == post_id:
            posts[i]['status'] = new_status
            save_posts(posts)
            return jsonify({'success': True})
    return jsonify({'success': False}), 404

@app.route('/api/stats')
def get_stats():
    posts = load_posts()
    return jsonify({
        'total':     len(posts),
        'scheduled': sum(1 for p in posts if p['status'] == 'scheduled'),
        'published': sum(1 for p in posts if p['status'] == 'published'),
        'draft':     sum(1 for p in posts if p['status'] == 'draft'),
    })

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory('.', 'uploads/' + filename)

def _handle_uploads(post, req, replace=False):
    if 'video' in req.files:
        v = req.files['video']
        if v and v.filename and allowed(v.filename, ALLOWED_VID):
            if replace and post.get('video_path') and os.path.exists(post['video_path']):
                os.remove(post['video_path'])
            ext = v.filename.rsplit('.', 1)[1].lower()
            fname = f"{post['id']}.{ext}"
            v.save(f"uploads/videos/{fname}")
            post['video_path'] = f"uploads/videos/{fname}"
            post['video_name'] = secure_filename(v.filename)
    if 'thumbnail' in req.files:
        t = req.files['thumbnail']
        if t and t.filename and allowed(t.filename, ALLOWED_IMG):
            if replace and post.get('thumbnail_path') and os.path.exists(post['thumbnail_path']):
                os.remove(post['thumbnail_path'])
            ext = t.filename.rsplit('.', 1)[1].lower()
            fname = f"{post['id']}.{ext}"
            t.save(f"uploads/thumbnails/{fname}")
            post['thumbnail_path'] = f"uploads/thumbnails/{fname}"
            post['thumbnail_name'] = secure_filename(t.filename)

if __name__ == '__main__':
    # Nom du projet mis à jour
    print("\n🚀 Propulsion IA - Agent d'automatisation démarré")
    print("👉 Accès local : http://localhost:5000\n")
    app.run(debug=True, port=5000)