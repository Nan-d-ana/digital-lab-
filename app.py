import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import mysql.connector

app = Flask(__name__)

# Twilio Client for Outbound Handshake
# Ensure these are in Render Environment Variables
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

def get_db_connection():
    """Establishes a secure SSL connection to Aiven MySQL with Timeout Fix"""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 13197)),
        ssl_ca="ca.pem",
        ssl_verify_cert=True,
        connect_timeout=10  # Stops the "Worker Timeout" crash
    )

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_raw = request.values.get('Body', '').strip()
    incoming_msg = incoming_raw.lower()
    # Clean the phone number (removes + and whatsapp: prefix)
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # 1. IDENTIFY USER
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()
        
        if not user:
            # Fallback so you know the connection is working even if DB entry is missing
            resp.message(f"⚠️ Connection Live! But number {from_number} not found in DB.")
            db.close()
            return str(resp)

        # 2. GREETING (If user exists)
        if incoming_msg in ['hi', 'hello', 'hey']:
            resp.message(f"Welcome {user['name']}! 🔬\n1. Check Lab Status\n2. Transfer Key")
        else:
            resp.message("Please reply with '1' for Lab Status or '2' to Transfer a Key.")

        db.close()
    except Exception as e:
        # This will text you the EXACT error if the database connection fails
        resp.message(f"❌ System Error: {str(e)}")
        
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)