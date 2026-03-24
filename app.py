import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)

# Twilio Client for sending outbound notifications to the Key Owner
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(account_sid, auth_token)
twilio_number = os.getenv("TWILIO_WHATSAPP_NUMBER")

def get_db_connection():
    """Connects to Aiven MySQL using SSL and environment variables."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 16690)),
        ssl_ca="ca.pem",
        ssl_verify_cert=True,
        connect_timeout=15
    )

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

        # 1. USER IDENTIFICATION: Query the 'users' table by phone
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()

        if not user:
            resp.message(f"Registration Error: Number {from_number} not found. Contact Admin.")
            return str(resp)

        user_id = user['barcode_id']
        user_name = user['name']

        # 2. HANDSHAKE APPROVAL: If user replies "yes [lab_name]"
        if incoming_msg.startswith("yes "):
            lab_requested = incoming_msg.replace("yes ", "").strip()
            
            # Check for a pending request where THIS user is the 'owner_id'
            cursor.execute("""
                SELECT t.*, u.name as requester_name, l.lab_name, u.phone_number as requester_phone
                FROM transfer_requests t
                JOIN users u ON t.requester_id = u.barcode_id
                JOIN lab_keys l ON t.lab_id = l.rfid_tag
                WHERE t.owner_id = %s AND LOWER(l.lab_name) = %s AND t.status = 'pending'
            """, (user_id, lab_requested))
            pending = cursor.fetchone()

            if pending:
                lab_id = pending['lab_id']
                req_id = pending['requester_id']

                # ATOMIC TRANSACTION: Handover
                # A. Return the key from Current Owner
                cursor.execute("UPDATE key_logs SET return_time = NOW() WHERE user_id = %s AND lab_id = %s AND return_time IS NULL", (user_id, lab_id))
                # B. Issue key to New Requester
                cursor.execute("INSERT INTO key_logs (user_id, lab_id, issue_time) VALUES (%s, %s, NOW())", (req_id, lab_id))
                # C. Approve Request
                cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE owner_id = %s AND lab_id = %s", (user_id, lab_id))
                
                db.commit()
                resp.message(f"✅ Transfer Confirmed! You have handed the {pending['lab_name']} key to {pending['requester_name']}.")
                
                # Notify the Requester
                twilio_client.messages.create(
                    from_=f"whatsapp:{twilio_number}",
                    body=f"✅ {user_name} has approved your request! You are now the official holder of the {pending['lab_name']} key.",
                    to=f"whatsapp:{pending['requester_phone']}"
                )
                return str(resp)

        # 3. MAIN MENU
        if incoming_msg in ['hi', 'hello']:
            resp.message(f"Welcome to Lab Tracker, {user_name}! 🔬\n1. Check Lab Status\n2. Transfer Key")

        # FEATURE 1: CHECK STATUS
        elif incoming_msg == '1':
            cursor.execute("SELECT lab_name FROM lab_keys")
            labs = cursor.fetchall()
            lab_list = "\n".join([f"• {l['lab_name']}" for l in labs])
            resp.message(f"Enter Lab Name to see current holder:\n\n{lab_list}")

        # FEATURE 2: REQUEST TRANSFER
        elif incoming_msg == '2':
            resp.message("Enter the Lab Name you want to take over:")

        # 4. DYNAMIC LAB LOGIC (Retrieve data based on Lab Name input)
        else:
            cursor.execute("SELECT * FROM lab_keys WHERE LOWER(lab_name) = %s", (incoming_msg,))
            lab = cursor.fetchone()

            if lab:
                # Find current holder from key_logs
                cursor.execute("""
                    SELECT u.name, u.semester, k.issue_time, u.barcode_id, u.phone_number
                    FROM key_logs k 
                    JOIN users u ON k.user_id = u.barcode_id 
                    WHERE k.lab_id = %s AND k.return_time IS NULL
                """, (lab['rfid_tag'],))
                holder = cursor.fetchone()

                if holder:
                    if holder['barcode_id'] == user_id:
                        resp.message(f"You already hold the {lab['lab_name']} key!")
                    else:
                        # Log the transfer request
                        cursor.execute("INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status) VALUES (%s, %s, %s, 'pending')", 
                                       (lab['rfid_tag'], user_id, holder['barcode_id'], 'pending'))
                        db.commit()
                        
                        resp.message(f"⏳ Request logged. {holder['name']} must reply 'YES {lab['lab_name']}' to confirm.")
                        
                        # Trigger Outbound message to User B (The Owner)
                        twilio_client.messages.create(
                            from_=f"whatsapp:{twilio_number}",
                            body=f"🔔 {user_name} wants to take over the {lab['lab_name']} key. Reply 'YES {lab['lab_name']}' to confirm handover.",
                            to=f"whatsapp:{holder['phone_number']}"
                        )
                else:
                    resp.message(f"The {lab['lab_name']} key is currently available in the Lab Office ✅")
            else:
                resp.message("Command not recognized. Use '1' for Status or '2' for Transfer.")

    except Error as e:
        resp.message(f"⚠️ Connection Error: Please ensure the database firewall is open.")
    finally:
        if db and db.is_connected():
            db.close()

    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)