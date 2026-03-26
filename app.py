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
    incoming_msg = request.values.get('Body', '').strip().lower()
    # Standardize phone number format
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    db = get_db_connection()

    if not db:
        resp.message("⏳ System is waking up. Please resend your message in a moment.")
        return str(resp)

    try:
        cursor = db.cursor(dictionary=True)

        # 1. IDENTIFY THE USER SENDING THE MESSAGE
        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (from_number,))
        user = cursor.fetchone()
        if not user:
            resp.message("Registration Error: Your number is not recognized in the system.")
            return str(resp)

        # 2. THE HANDSHAKE: PROCESSING "YES" APPROVAL
        if incoming_msg == "yes":
            # Fetch the most recent pending request where this user is the owner
            cursor.execute("""
                SELECT t.id, t.lab_id, t.requester_id, l.lab_name 
                FROM transfer_requests t
                JOIN lab_keys l ON t.lab_id = l.rfid_tag
                WHERE t.owner_id = %s AND t.status = 'pending'
                ORDER BY t.request_time DESC LIMIT 1
            """, (user['barcode_id'],))
            pending = cursor.fetchone()
            
            if pending:
                try:
                    # Step A: Close the current owner's log
                    cursor.execute("""
                        UPDATE key_logs 
                        SET return_time = NOW() 
                        WHERE user_id = %s AND lab_id = %s AND return_time IS NULL
                    """, (user['barcode_id'], pending['lab_id']))
                    
                    # Step B: Create a new log for the requester
                    cursor.execute("""
                        INSERT INTO key_logs (user_id, lab_id, issue_time) 
                        VALUES (%s, %s, NOW())
                    """, (pending['requester_id'], pending['lab_id']))
                    
                    # Step C: Mark the transfer request as approved
                    cursor.execute("UPDATE transfer_requests SET status = 'approved' WHERE id = %s", (pending['id'],))
                    
                    db.commit()
                    resp.message(f"✅ Success! You have transferred the {pending['lab_name']} key.")
                except Exception as inner_e:
                    db.rollback()
                    print(f"🔥 Transfer Transaction Failed: {inner_e}")
                    resp.message("⚠️ Transfer failed during database update. Please try again.")
            else:
                resp.message("You don't have any pending key transfer requests to approve.")
            return str(resp)

        # 3. MAIN MENU
        if incoming_msg in ['hi', 'hello', 'menu']:
            resp.message(f"Welcome {user['name']}!\n\nReply with:\n*1* - Check Lab Status\n*2* - Request Key Transfer")
            return str(resp)

        # 4. SHOW LAB OPTIONS
        if incoming_msg == '1' or incoming_msg == '2':
            action = "Check" if incoming_msg == '1' else "Transfer"
            cursor.execute("SELECT lab_name FROM lab_keys")
            labs = cursor.fetchall()
            menu = f"*{action} Key*\nSelect a lab:\n"
            for i, l in enumerate(labs):
                menu += f"*{incoming_msg}{chr(97+i)}.* {l['lab_name']}\n"
            resp.message(menu)
            return str(resp)

        # 5. PROCESS SELECTION (e.g., 1a, 2a)
        if len(incoming_msg) == 2 and incoming_msg[0] in ['1', '2']:
            mode = 'status' if incoming_msg[0] == '1' else 'transfer'
            idx = ord(incoming_msg[1]) - 97
            
            cursor.execute("SELECT * FROM lab_keys")
            labs = cursor.fetchall()
            
            if 0 <= idx < len(labs):
                selected = labs[idx]
                if mode == 'status':
                    cursor.execute("""
                        SELECT u.name, k.issue_time FROM key_logs k
                        JOIN users u ON k.user_id = u.barcode_id
                        WHERE k.lab_id = %s AND k.return_time IS NULL
                    """, (selected['rfid_tag'],))
                    h = cursor.fetchone()
                    msg = f"📍 {selected['lab_name']}\nHolder: {h['name']}\nSince: {h['issue_time']}" if h else f"✅ {selected['lab_name']} is in the office."
                    resp.message(msg)
                else:
                    # Initiate Transfer Request
                    cursor.execute("""
                        SELECT u.barcode_id, u.phone_number, u.name 
                        FROM key_logs k
                        JOIN users u ON k.user_id = u.barcode_id
                        WHERE k.lab_id = %s AND k.return_time IS NULL
                    """, (selected['rfid_tag'],))
                    h = cursor.fetchone()
                    
                    if h:
                        # Ensure we don't request our own key
                        if h['barcode_id'] == user['barcode_id']:
                            resp.message("You already have this key!")
                            return str(resp)

                        cursor.execute("""
                            INSERT INTO transfer_requests (lab_id, requester_id, owner_id, status) 
                            VALUES (%s, %s, %s, 'pending')
                        """, (selected['rfid_tag'], user['barcode_id'], h['barcode_id']))
                        db.commit()

                        # Outgoing notification to the owner
                        try:
                            twilio_client.messages.create(
                                from_=f"whatsapp:{twilio_number}",
                                body=f"🔔 *Key Request*\n{user['name']} wants the {selected['lab_name']} key. Reply *YES* to approve.",
                                to=f"whatsapp:{h['phone_number']}"
                            )
                            resp.message(f"⏳ Request sent! Please wait for {h['name']} to approve.")
                        except Exception as t_err:
                            print(f"Twilio Error: {t_err}")
                            resp.message(f"⏳ Request logged, but I couldn't text {h['name']}. Please tell them to reply 'YES'.")
                    else:
                        resp.message(f"The {selected['lab_name']} key is already in the office.")
                return str(resp)

        resp.message("Unknown command. Send 'Hi' for the menu.")

    except Exception as e:
        print(f"🔥 Application Error: {e}")
        resp.message("⚠️ An internal error occurred. Please try again.")
    finally:
        if db: db.close()
            
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))