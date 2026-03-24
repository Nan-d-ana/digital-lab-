import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)

# Twilio Client for outbound Handshake notifications
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(account_sid, auth_token)
twilio_number = os.getenv("TWILIO_WHATSAPP_NUMBER")

# State tracker for menus (resets if server sleeps)
user_sessions = {}

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", 16690)),
            ssl_ca="ca.pem",
            ssl_verify_cert=True,
            connect_timeout=10 # Reduced to 10s for faster testing
        )
        print("✅ DATABASE CONNECTED SUCCESSFULLY")
        return conn
    except Exception as e:
        print(f"❌ DATABASE CONNECTION FAILED: {e}")
        raise e

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_raw = request.values.get('Body', '').strip()
    incoming_msg = incoming_raw.lower()
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    db = None

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # 1. USER IDENTIFICATION
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()
        if not user:
            resp.message(f"Registration Error: {from_number} not found.")
            return str(resp)

        user_id = user['barcode_id']

        # 2. THE HANDSHAKE (Approval Logic)
        if incoming_msg == "yes":
            cursor.execute("""
                SELECT t.*, l.lab_name, u.phone_number as req_phone 
                FROM transfer_requests t
                JOIN lab_keys l ON t.lab_id = l.rfid_tag
                JOIN users u ON t.requester_id = u.barcode_id
                WHERE t.owner_id = %s AND t.status = 'pending'
            """, (user_id,))
            pending = cursor.fetchone()
            if pending:
                cursor.execute("UPDATE key_logs SET return_time = NOW() WHERE user_id = %s AND lab_id = %s AND return_time IS NULL", (user_id, pending['lab_id']))
                cursor.execute("INSERT INTO key_logs (user_id, lab_id, issue_time) VALUES (%s, %s, NOW())", (pending['requester_id'], pending['lab_id']))
                cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE owner_id = %s AND status = 'pending'", (user_id,))
                db.commit()
                resp.message(f"✅ Key for {pending['lab_name']} transferred!")
                return str(resp)

        # 3. MAIN MENU (Hi/Hello)
        if incoming_msg in ['hi', 'hello']:
            user_sessions[from_number] = None
            resp.message(f"Welcome {user['name']}! 🔬\n1. Check Lab Status\n2. Transfer Key")
            return str(resp)

        # 4. SUB-MENU (1 or 2 selected)
        if incoming_msg == '1' or incoming_msg == '2':
            user_sessions[from_number] = 'status' if incoming_msg == '1' else 'transfer'
            cursor.execute("SELECT lab_name FROM lab_keys")
            labs = cursor.fetchall()
            menu = "Select a lab:\n"
            for i, l in enumerate(labs):
                menu += f"{chr(97+i)}. {l['lab_name']}\n"
            resp.message(menu)
            return str(resp)

        # 5. LETTER SELECTION (a, b, c)
        if from_number in user_sessions and user_sessions[from_number] and len(incoming_msg) == 1:
            idx = ord(incoming_msg) - 97
            cursor.execute("SELECT * FROM lab_keys")
            labs = cursor.fetchall()

            if 0 <= idx < len(labs):
                selected = labs[idx]
                if user_sessions[from_number] == 'status':
                    cursor.execute("""
                        SELECT u.name, u.semester, k.issue_time FROM key_logs k
                        JOIN users u ON k.user_id = u.barcode_id
                        WHERE k.lab_id = %s AND k.return_time IS NULL
                    """, (selected['rfid_tag'],))
                    h = cursor.fetchone()
                    msg = f"📍 {selected['lab_name']}\nHolder: {h['name']} (S{h['semester']})\nTime: {h['issue_time']}" if h else f"{selected['lab_name']} is Available ✅"
                    resp.message(msg)
                elif user_sessions[from_number] == 'transfer':
                    cursor.execute("SELECT user_id FROM key_logs WHERE lab_id = %s AND return_time IS NULL", (selected['rfid_tag'],))
                    h = cursor.fetchone()
                    if h:
                        cursor.execute("INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status) VALUES (%s, %s, %s, 'pending')", (selected['rfid_tag'], user_id, h['user_id'], 'pending'))
                        db.commit()
                        resp.message(f"⏳ Request for {selected['lab_name']} sent.")
                    else:
                        resp.message("Key is in the office.")
                user_sessions[from_number] = None
                return str(resp)

    except Error as e:
        resp.message("⚠️ Database Error. Check Aiven Firewall.")
    finally:
        if db: db.close()
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)