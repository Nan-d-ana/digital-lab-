import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import mysql.connector

app = Flask(__name__)

# Twilio Client for Handshake notifications
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(account_sid, auth_token)
twilio_number = os.getenv("TWILIO_WHATSAPP_NUMBER")

def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", 16690)),
            ssl_ca="ca.pem",
            ssl_verify_cert=True,
            connect_timeout=10
        )
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return None

@app.route("/test-db")
def test_db():
    db = get_db_connection()
    if db:
        db.close()
        return "✅ System Online", 200
    return "❌ System Offline", 500

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').strip().lower()
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    db = get_db_connection()

    if not db:
        resp.message("⏳ System waking up. Please resend in 5 seconds.")
        return str(resp)

    try:
        cursor = db.cursor(dictionary=True)

        # 1. IDENTIFY USER
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()
        if not user:
            resp.message("Registration Error: Your number is not found in the lab database.")
            return str(resp)

        # 2. HANDSHAKE (APPROVE TRANSFER)
        if incoming_msg == "yes":
            cursor.execute("""
                SELECT t.id, t.lab_id, t.requester_id, l.lab_name 
                FROM transfer_requests t
                JOIN lab_keys l ON t.lab_id = l.rfid_tag
                WHERE t.owner_id = %s AND t.status = 'pending'
                ORDER BY t.request_time DESC LIMIT 1
            """, (user['barcode_id'],))
            pending = cursor.fetchone()
            
            if pending:
                # Close current log
                cursor.execute("UPDATE key_logs SET return_time = NOW() WHERE user_id = %s AND lab_id = %s AND return_time IS NULL", (user['barcode_id'], pending['lab_id']))
                # Create new log for requester
                cursor.execute("INSERT INTO key_logs (user_id, lab_id, issue_time) VALUES (%s, %s, NOW())", (pending['requester_id'], pending['lab_id']))
                # Mark request as approved
                cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE id = %s", (pending['id'],))
                db.commit()
                resp.message(f"✅ Success! The {pending['lab_name']} key has been transferred.")
            else:
                resp.message("No pending transfer requests found for you.")
            return str(resp)

        # 3. MAIN MENU
        if incoming_msg in ['hi', 'hello', 'menu']:
            resp.message(f"Welcome {user['name']}!\n\n*Reply with:*\n*1* - View Lab Status\n*2* - Request Key Transfer")
            return str(resp)

        # 4. SHOW LAB LIST
        if incoming_msg == '1' or incoming_msg == '2':
            prefix = "Check Status" if incoming_msg == '1' else "Request Transfer"
            cursor.execute("SELECT lab_name FROM lab_keys")
            labs = cursor.fetchall()
            menu = f"*{prefix}*\nSelect a lab:\n"
            for i, l in enumerate(labs):
                menu += f"*{incoming_msg}{chr(97+i)}.* {l['lab_name']}\n"
            menu += "\n_Example: Reply '1a' to check the first lab_"
            resp.message(menu)
            return str(resp)

        # 5. SELECTION PROCESSING (1a, 2a, etc.)
        if len(incoming_msg) == 2 and incoming_msg[0] in ['1', '2']:
            mode = 'status' if incoming_msg[0] == '1' else 'transfer'
            idx = ord(incoming_msg[1]) - 97
            
            cursor.execute("SELECT * FROM lab_keys")
            labs = cursor.fetchall()
            
            if 0 <= idx < len(labs):
                selected = labs[idx]
                if mode == 'status':
                    cursor.execute("""
                        SELECT u.name, u.semester, k.issue_time FROM key_logs k
                        JOIN users u ON k.user_id = u.barcode_id
                        WHERE k.lab_id = %s AND k.return_time IS NULL
                    """, (selected['rfid_tag'],))
                    h = cursor.fetchone()
                    msg = f"📍 {selected['lab_name']}\nHolder: {h['name']} (S{h['semester']})\nSince: {h['issue_time']}" if h else f"✅ {selected['lab_name']} is currently in the office."
                    resp.message(msg)
                else:
                    # Request Transfer
                    cursor.execute("""
                        SELECT u.barcode_id, u.phone_number, u.name 
                        FROM key_logs k
                        JOIN users u ON k.user_id = u.barcode_id
                        WHERE k.lab_id = %s AND k.return_time IS NULL
                    """, (selected['rfid_tag'],))
                    h = cursor.fetchone()
                    
                    if h:
                        # Fixed: Corrected parameter count for INSERT
                        cursor.execute("""
                            INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status) 
                            VALUES (%s, %s, %s, 'pending')
                        """, (selected['rfid_tag'], user['barcode_id'], h['barcode_id']))
                        db.commit()

                        # NOTIFY THE HOLDER
                        try:
                            twilio_client.messages.create(
                                from_=f"whatsapp:{twilio_number}",
                                body=f"🔔 *Key Request*\n{user['name']} (S{user['semester']}) requested the {selected['lab_name']} key. Reply *YES* to approve.",
                                to=f"whatsapp:{h['phone_number']}"
                            )
                            resp.message(f"⏳ Request sent! Please wait for {h['name']} to approve.")
                        except Exception as e:
                            print(f"Twilio Notify Error: {e}")
                            resp.message(f"⏳ Request logged. Please ask {h['name']} to check their WhatsApp and reply 'YES'.")
                    else:
                        resp.message(f"The {selected['lab_name']} key is already in the office.")
                return str(resp)

        resp.message("Command not recognized. Send 'Hi' for the main menu.")

    except Exception as e:
        print(f"🔥 Application Error: {e}")
        resp.message("⚠️ An internal error occurred. Please try again.")
    finally:
        if db: db.close()
            
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port) 