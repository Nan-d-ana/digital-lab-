import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import mysql.connector
from datetime import datetime

app = Flask(__name__)

# Twilio Client for Outbound Messages (The Handshake)
# These must be set in your Render Environment Variables
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

def get_db_connection():
    """Establishes a secure SSL connection to Aiven MySQL"""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 13197)),
        ssl_ca="ca.pem",  # Ensure this file is in your GitHub root folder
        ssl_verify_cert=True
    )

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_raw = request.values.get('Body', '').strip()
    incoming_msg = incoming_raw.lower()
    # Identifies the sender by their WhatsApp number (removes 'whatsapp:' prefix)
    from_number = request.values.get('From', '').replace('whatsapp:', '')
    
    resp = MessagingResponse()
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # 1. IDENTIFY USER
    cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
    user = cursor.fetchone()
    
    if not user:
        resp.message("❌ Your number is not registered in the Lab System. Please contact the admin.")
        db.close()
        return str(resp)

    # 2. GREETING
    if incoming_msg in ['hi', 'hello', 'hey']:
        resp.message(f"Welcome {user['name']}! 🔬\n1. Check Lab Status\n2. Transfer Key")

    # 3. OPTION 1: CHECK STATUS
    elif incoming_msg == '1':
        resp.message("Which lab?\nA: Algorithm\nB: Systems\nC: High-Tech\nD: Project")

    elif incoming_msg in ['a', 'b', 'c', 'd']:
        lab_map = {'a': 'Algorithm', 'b': 'Systems', 'c': 'High-Tech', 'd': 'Project'}
        selected_lab = lab_map[incoming_msg]
        
        query = """
            SELECT u.name, u.semester, k.issue_time 
            FROM key_logs k 
            JOIN users u ON k.user_id = u.barcode_id 
            JOIN lab_keys l ON k.lab_id = l.rfid_tag
            WHERE l.lab_name = %s AND k.return_time IS NULL
        """
        cursor.execute(query, (selected_lab,))
        holder = cursor.fetchone()
        
        if holder:
            resp.message(f"📍 {selected_lab}\nHolder: {holder['name']}\nSem: {holder['semester']}\nIssued: {holder['issue_time']}")
        else:
            resp.message(f"✅ The key for {selected_lab} is currently available in the lab office.")

    # 4. OPTION 2: TRANSFER REQUEST (Requester sends this)
    elif incoming_msg == '2':
        resp.message("To request a key from another student, type: REQUEST [Lab Name]\n(e.g., REQUEST Algorithm)")

    elif incoming_msg.startswith('request'):
        try:
            lab_name = incoming_raw.split(' ', 1)[1]
            # Find current owner and their phone number
            cursor.execute("""
                SELECT l.rfid_tag, k.user_id, u.phone_number, u.name 
                FROM lab_keys l
                JOIN key_logs k ON l.rfid_tag = k.lab_id
                JOIN users u ON k.user_id = u.barcode_id
                WHERE l.lab_name = %s AND k.return_time IS NULL
            """, (lab_name,))
            owner_data = cursor.fetchone()

            if owner_data:
                # Log the pending transfer
                cursor.execute("""
                    INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status)
                    VALUES (%s, %s, %s, 'pending')
                """, (owner_data['rfid_tag'], user['barcode_id'], owner_data['user_id']))
                db.commit()

                # NOTIFY THE OWNER (The Handshake)
                twilio_client.messages.create(
                    from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_NUMBER')}",
                    body=f"🔔 {user['name']} wants the {lab_name} key. Reply 'YES {lab_name}' to approve.",
                    to=f"whatsapp:{owner_data['phone_number']}"
                )
                resp.message(f"✅ Request sent to {owner_data['name']}. Please wait for their approval.")
            else:
                resp.message(f"❌ No one currently holds the {lab_name} key.")
        except IndexError:
            resp.message("❌ Please specify the lab. Example: REQUEST Algorithm")

    # 5. APPROVAL (Owner sends this from THEIR phone)
    elif incoming_msg.startswith('yes'):
        try:
            lab_name = incoming_raw.split(' ', 1)[1]
            # Check if this user actually owns a pending request for this lab
            cursor.execute("""
                SELECT tr.*, l.lab_name, u.phone_number as req_phone, u.name as req_name
                FROM transfer_requests tr
                JOIN lab_keys l ON tr.lab_id = l.rfid_tag
                JOIN users u ON tr.requester_id = u.barcode_id
                WHERE tr.owner_id = %s AND l.lab_name = %s AND tr.status = 'pending'
            """, (user['barcode_id'], lab_name))
            request_to_approve = cursor.fetchone()

            if request_to_approve:
                # Atomic Transaction: Handover logic
                cursor.execute("UPDATE key_logs SET return_time = NOW() WHERE user_id = %s AND lab_id = %s AND return_time IS NULL", 
                               (user['barcode_id'], request_to_approve['lab_id']))
                cursor.execute("INSERT INTO key_logs (user_id, lab_id, issue_time) VALUES (%s, %s, NOW())", 
                               (request_to_approve['requester_id'], request_to_approve['lab_id']))
                cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE requester_id = %s AND lab_id = %s", 
                               (request_to_approve['requester_id'], request_to_approve['lab_id']))
                db.commit()

                # Notify the Requester (User A)
                twilio_client.messages.create(
                    from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_NUMBER')}",
                    body=f"🤝 {user['name']} approved your request! You are now the official holder of the {lab_name} key.",
                    to=f"whatsapp:{request_to_approve['req_phone']}"
                )
                resp.message(f"✅ Success! You have transferred the {lab_name} key to {request_to_approve['req_name']}.")
            else:
                resp.message("❌ No pending transfer found for this lab.")
        except Exception as e:
            db.rollback()
            resp.message("❌ Transfer failed. Please try again later.")

    db.close()
    return str(resp)

if __name__ == "__main__":
    # Standard Flask Port logic for Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
