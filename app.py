import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import mysql.connector

app = Flask(__name__)

# Twilio Credentials from Render Environment Variables
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
        print(f"❌ DB Connection Error: {e}")
        return None

@app.route("/", methods=['GET'])
def health_check():
    return "Bot is Awake", 200

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').strip().lower()
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    db = get_db_connection()

    if not db:
        resp.message("⏳ System is waking up. Please resend your message in a moment.")
        return str(resp)

    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()
        
        if not user:
            resp.message("Registration Error: Your number is not recognized in the system.")
            return str(resp)

        # --- 1. THE HANDSHAKE (APPROVE TRANSFER) ---
        if incoming_msg == "yes":
            cursor.execute("""
                SELECT t.lab_id, t.requester_id, l.lab_name, u.name as requester_name,
                       u.phone_number as requester_phone 
                FROM transfer_requests t
                JOIN lab_keys l ON t.lab_id = l.rfid_tag
                JOIN users u ON t.requester_id = u.barcode_id
                WHERE t.owner_id = %s AND t.status = 'pending'
                LIMIT 1
            """, (user['barcode_id'],))
            pending = cursor.fetchone()
        
            if pending:
                try:
                    cursor.execute("UPDATE key_logs SET return_time = NOW() WHERE user_id = %s AND lab_id = %s AND return_time IS NULL", (user['barcode_id'], pending['lab_id']))
                    cursor.execute("INSERT INTO key_logs (user_id, lab_id, issue_time) VALUES (%s, %s, NOW())", (pending['requester_id'], pending['lab_id']))
                    cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE owner_id = %s AND lab_id = %s AND status = 'pending'", (user['barcode_id'], pending['lab_id']))
                    db.commit()
                    
                    try:
                        twilio_client.messages.create(
                            from_=f"whatsapp:{twilio_number}",
                            body=(f"🔑 *KEY TRANSFER APPROVED*\n\n"
                                  f"Hello *{pending['requester_name']}*,\n"
                                  f"*{user['name']}* has authorized your request for the *{pending['lab_name']}* key."),
                            to=f"whatsapp:{pending['requester_phone']}"
                        )
                    except Exception as e:
                        print(f"🔥 Twilio Notify Error: {e}")

                    resp.message(f"🤝 *Transfer Successful!*\nYou handed over the *{pending['lab_name']}* key to *{pending['requester_name']}*.")
                except Exception as e:
                    db.rollback()
                    resp.message("⚠️ Database update failed.")
            else:
                resp.message("No pending requests found.")
            return str(resp)

        # --- 2. MAIN MENU ---
        if incoming_msg in ['hi', 'hello', 'menu']:
            resp.message(f"Welcome {user['name']}!\n\n*1* - Check Lab Status\n*2* - Request Key Transfer")
            return str(resp)

        cursor.execute("SELECT rfid_tag, lab_name FROM lab_keys ORDER BY lab_name ASC")
        all_labs = cursor.fetchall()
        lab_map_1 = {chr(97+i): l for i, l in enumerate(all_labs)}
        lab_map_2 = {f"2{chr(97+i)}": l for i, l in enumerate(all_labs)}

        if incoming_msg == '1':
            menu = "*Check Lab Status*\n\n"
            for i, l in enumerate(all_labs):
                menu += f"*{chr(97+i)}.* {l['lab_name']}\n"
            resp.message(menu)
            return str(resp)

        if incoming_msg == '2':
            cursor.execute("SELECT lab_id FROM key_logs WHERE return_time IS NULL")
            held_ids = [row['lab_id'] for row in cursor.fetchall()]
            menu = "*Access Lab Key*\n\n"
            found_held = False
            for i, l in enumerate(all_labs):
                if l['rfid_tag'] in held_ids:
                    menu += f"*2{chr(97+i)}.* {l['lab_name']}\n"
                    found_held = True
            resp.message(menu if found_held else "All keys are currently in the office.")
            return str(resp)

        if incoming_msg in lab_map_1:
            selected = lab_map_1[incoming_msg]
            cursor.execute("SELECT u.name FROM key_logs k JOIN users u ON k.user_id = u.barcode_id WHERE k.lab_id = %s AND k.return_time IS NULL", (selected['rfid_tag'],))
            h = cursor.fetchone()
            resp.message(f"📍 *{selected['lab_name']}*\n👤 *Holder:* {h['name']}" if h else f"✅ {selected['lab_name']} is in office.")
            return str(resp)

        # --- 3. SELECTION 2 (REQUEST LOGIC) ---
        if incoming_msg in lab_map_2:
            selected = lab_map_2[incoming_msg]
            cursor.execute("SELECT u.barcode_id, u.phone_number, u.name FROM key_logs k JOIN users u ON k.user_id = u.barcode_id WHERE k.lab_id = %s AND k.return_time IS NULL", (selected['rfid_tag'],))
            h = cursor.fetchone()
            
            if h:
                if h['barcode_id'] == user['barcode_id']:
                    resp.message("You already have this key!")
                else:
                    cursor.execute("SELECT id FROM transfer_requests WHERE lab_id = %s AND status = 'pending'", (selected['rfid_tag'],))
                    if cursor.fetchone():
                        resp.message(f"⚠️ A request for *{selected['lab_name']}* is already pending with *{h['name']}*.")
                    else:
                        cursor.execute("INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status) VALUES (%s, %s, %s, 'pending')", (selected['rfid_tag'], user['barcode_id'], h['barcode_id']))
                        db.commit()
                        
                        target_phone = str(h['phone_number']).strip()
                        if not target_phone.startswith('+'):
                            target_phone = f"+{target_phone}"

                        try:
                            twilio_client.messages.create(
                                from_=f"whatsapp:{twilio_number}",
                                body=(f"🔔 *KEY REQUEST*\n\n"
                                      f"Dear *{h['name']}*,\n"
                                      f"*{user['name']}* wants the *{selected['lab_name']}* key. Reply YES to approve."),
                                to=f"whatsapp:{target_phone}"
                            )
                            resp.message(f"✅ Request forwarded to *{h['name']}*.")
                        except Exception as e:
                            print(f"🔥 Twilio Error: {e}")
                            resp.message(f"✅ Request Logged. Inform *{h['name']}* to reply YES.")
            return str(resp)

        resp.message(f"Hello {user['name']}! Reply 'Menu' for options.")

    except Exception as e:
        print(f"🔥 Global Error: {e}")
        resp.message("⚠️ System encountered an error.")
    finally:
        if db:
            db.close()
            
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))