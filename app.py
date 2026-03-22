import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import mysql.connector

app = Flask(__name__)

# This simulates a database table for pending transfers
pending_requests = {} 

# Temporary lab status for demo purposes
lab_status = {
    "Algorithm Lab": "Available ✅",
    "Systems Lab": "Held by Navomy 🔑",
    "Hi-Tech Lab": "Available ✅",
    "Research Lab": "Available ✅"
}

def get_db_connection():
    """Kept for future Aiven fix; logic falls back if connection fails"""
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
    except:
        return None

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_raw = request.values.get('Body', '').strip()
    incoming_msg = incoming_raw.lower()
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    
    # 1. USER IDENTIFICATION
    # NOTE: Replace the second number with Navomy's real number for the demo
    demo_users = {
        "917593998816": {"name": "Nandana"},
        "91XXXXXXXXXX": {"name": "Navomy"} 
    }
    user = demo_users.get(from_number)

    if not user:
        resp.message(f"Hello! Number {from_number} is not registered.")
        return str(resp)

    # 2. TRANSFER ACCEPTANCE LOGIC
    if from_number in pending_requests and incoming_msg in ['yes', 'no']:
        req_data = pending_requests[from_number]
        if incoming_msg == 'yes':
            resp.message(f"✅ Transfer Confirmed! You have handed over the {req_data['lab']} key to {req_data['requester_name']}.")
        else:
            resp.message(f"❌ Transfer Declined. You still hold the {req_data['lab']} key.")
        
        del pending_requests[from_number]
        return str(resp)

    # 3. MAIN MENU LOGIC
    if incoming_msg in ['hi', 'hello', 'hey']:
        resp.message(f"Welcome {user['name']}! 🔬\n\n1. Check Lab Status\n2. Request Key Transfer")

    elif incoming_msg == '1':
        status_text = "📍 *Current Lab Status:*\n"
        for lab, status in lab_status.items():
            status_text += f"• {lab}: {status}\n"
        resp.message(status_text)

    elif incoming_msg == '2':
        # Simulated target for the demo (Navomy)
        target_number = "91XXXXXXXXXX" 
        
        pending_requests[target_number] = {
            'requester_name': user['name'],
            'lab': "Systems Lab"
        }
        
        resp.message(f"⏳ Request sent to Navomy for the *Systems Lab* key.\n\nAsk her to reply 'YES' to this bot to confirm.")

    else:
        resp.message("Please reply with '1' or '2'.\n(If you are confirming a transfer, reply 'YES')")
        
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)