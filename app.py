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

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    # .lower() ensures "YES", "Yes", and "yes" are all treated the same
    incoming_msg = request.values.get('Body', '').strip().lower()
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    db = get_db_connection()

    if not db:
        resp.message("⏳ System is waking up. Please resend your message in a moment.")
        return str(resp)

    try:
        cursor = db.cursor(dictionary=True)

        # 1. IDENTIFY THE USER
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()
        if not user:
            resp.message("Registration Error: Your number is not recognized in the system.")
            return str(resp)

      # 2. THE HANDSHAKE (APPROVE TRANSFER)
        if incoming_msg == "yes":
            cursor.execute("""
                SELECT t.lab_id, t.requester_id, l.lab_name, u.name as requester_name 
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
                    cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE owner_id = %s AND lab_id = %s AND status = 'pending' LIMIT 1", (user['barcode_id'], pending['lab_id']))
                    db.commit()
                    
                    # Professional success message
                    resp.message(f"🤝 *Transfer Complete!*\nYou have successfully handed over the *{pending['lab_name']}* key to *{pending['requester_name']}*.\n\nYour responsibility for this key has ended.")
                except Exception as inner_e:
                    db.rollback()
                    resp.message("⚠️ Transfer failed during database update.")
            else:
                resp.message("No pending transfer requests found for you.")
            return str(resp)
        # 3. MAIN MENU
        if incoming_msg in ['hi', 'hello', 'menu']:
            resp.message(f"Welcome {user['name']}!\n\n*Reply with:*\n*1* - Check Lab Status\n*2* - Request Key Transfer")
            return str(resp)

        # 4. SUB-MENUS
        if incoming_msg == '1':
            cursor.execute("SELECT lab_name FROM lab_keys")
            labs = cursor.fetchall()
            menu = "*Check Lab Status*\nWhich lab status you want to check?\n\n"
            for i, l in enumerate(labs):
                menu += f"*{chr(97+i)}.* {l['lab_name']}\n"
            resp.message(menu)
            return str(resp)

        if incoming_msg == '2':
            cursor.execute("""
                SELECT l.lab_name 
                FROM lab_keys l
                JOIN key_logs k ON l.rfid_tag = k.lab_id
                WHERE k.return_time IS NULL
            """)
            labs = cursor.fetchall()
            if not labs:
                resp.message("All keys are currently in the office.")
            else:
                menu = "*Access Lab Key*\nWhich lab key you want to access?\n\n"
                for i, l in enumerate(labs):
                    menu += f"*2{chr(97+i)}.* {l['lab_name']}\n"
                resp.message(menu)
            return str(resp)

        # 5. PROCESS SELECTION (Option 1: a, b... OR Option 2: 2a, 2b...)
        cursor.execute("SELECT rfid_tag, lab_name FROM lab_keys")
        all_labs = cursor.fetchall()
        lab_map_1 = {chr(97+i): l for i, l in enumerate(all_labs)}
        lab_map_2 = {f"2{chr(97+i)}": l for i, l in enumerate(all_labs)}

        # --- OPTION 1: STATUS CHECK ---
        if incoming_msg in lab_map_1:
            selected = lab_map_1[incoming_msg]
            cursor.execute("""
                SELECT u.name, u.semester, u.department, k.issue_time 
                FROM key_logs k
                JOIN users u ON k.user_id = u.barcode_id
                WHERE k.lab_id = %s AND k.return_time IS NULL
            """, (selected['rfid_tag'],))
            h = cursor.fetchone()
            
            if h:
                msg = (f"📍 *{selected['lab_name']}*\n"
                       f"👤 *Holder:* {h['name']}\n"
                       f"🎓 *Sem/Dept:* {h['semester']} - {h['department']}\n"
                       f"⏰ *Since:* {h['issue_time']}")
            else:
                msg = f"✅ *{selected['lab_name']}* is currently in the office."
            resp.message(msg)
            return str(resp)

        # --- OPTION 2: TRANSFER REQUEST ---
        if incoming_msg in lab_map_2:
            selected = lab_map_2[incoming_msg]
            cursor.execute("""
                SELECT u.barcode_id, u.phone_number, u.name, u.semester, u.department 
                FROM key_logs k
                JOIN users u ON k.user_id = u.barcode_id
                WHERE k.lab_id = %s AND k.return_time IS NULL
            """, (selected['rfid_tag'],))
            h = cursor.fetchone()
            
            if h:
                if h['barcode_id'] == user['barcode_id']:
                    resp.message("You already have this key!")
                    return str(resp)

                # Log the transfer request in DB
                cursor.execute("""
                    INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status) 
                    VALUES (%s, %s, %s, 'pending')
                """, (selected['rfid_tag'], user['barcode_id'], h['barcode_id']))
                db.commit()

                # Send Request to current holder with requester's details
                try:
                    twilio_client.messages.create(
                        from_=f"whatsapp:{twilio_number}",
                        body=(f"🔔 *KEY TRANSFER REQUEST*\n\n"
                              f"{user['name']} wants the *{selected['lab_name']}* key.\n"
                              f"🎓 *Requester:* {user['semester']} Sem, {user['department']}\n\n"
                              f"Reply *YES* to approve the transfer."),
                        to=f"whatsapp:{h['phone_number']}"
                    )
                    resp.message(f"⏳ Request sent! Please wait for {h['name']} to approve.")
                except:
                    resp.message(f"⏳ Request logged. Ask {h['name']} to reply 'YES'.")
            else:
                resp.message(f"The {selected['lab_name']} key is already in the office.")
            return str(resp)
        # 6. CATCH-ALL DEFAULT REPLY
        resp.message(
            f"Hello {user['name']}! I didn't quite catch that.\n\n"
            "*Please reply with:*\n"
            "*1* - Check Lab Status\n"
            "*2* - Request Key Transfer\n\n"
            "_Or send 'Hi' to see this menu again._"
        )

    except Exception as e:
        print(f"🔥 Application Error: {e}")
        resp.message("⚠️ An internal error occurred. Please try again.")
    finally:
        if db: db.close()
            
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))