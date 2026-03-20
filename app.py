from flask import Flask
from routes import chatbot_bp
import os

app = Flask(__name__)

app.register_blueprint(chatbot_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
