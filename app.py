import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import mysql.connector

app = Flask(__name__)

# This simulates a database table for pending transfers
# In a real app, this would be a SQL table
pending_requests = {} 

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
    except:
        return None

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_raw = request.values.get('Body', '').strip()
    incoming_msg = incoming_raw.lower()
    from_number = request.values.get('From', '').replace('whatsapp:', '').replace('+', '')
    
    resp = MessagingResponse()
    
    # 1. IDENTIFY USER (Fallback Mode)
    demo_users = {
        "917593998816": {"name": "Nandana"},
        "91XXXXXXXXXX": {"name": "Navomy"} # Add Navomy's real number here
    }
    user = demo_users.get(from_number)

    if not user:
        resp.message(f"Hello! Number ({from_number}) not recognized.")
        return str(resp)

    # 2. CHECK FOR PENDING TRANSFER REQUESTS
    # If someone requested a key FROM this user, they need to 'Yes' or 'No'
    if from_number in pending_requests and incoming_msg in ['yes', 'no']:
        requester_name = pending_requests[from_number]['requester_name']
        if incoming_msg == 'yes':
            resp.message(f"✅ Transfer Confirmed! You have handed over the key to {requester_name}.")
            # Here you would normally update the SQL database
        else:
            resp.message(f"❌ Transfer Cancelled. You still have the key.")
        
        del pending_requests[from_number] # Clear the request
        return str(resp)

    # 3. GENERAL MENU LOGIC
    if incoming_msg in ['hi', 'hello']:
        resp.message(f"Welcome {user['name']}! 🔬\n1. Check Lab Status\n2. Request Key Transfer")

    elif incoming_msg == '1':
        resp.message("📍 Lab Status:\nAlgorithm: Available ✅\nSystems: Held by Navomy 🔑")

    elif incoming_msg == '2':
        # Logic to start a transfer
        # Example: Nandana wants to take the key from Navomy
        target_number = "91XXXXXXXXXX" # Navomy's Number
        pending_requests[target_number] = {'requester_name': user['name']}
        
        resp.message(f"⏳ Request sent to Navomy. Please wait for her to reply 'YES' to confirm.")
        # Note: In a real app, you would use twilio_client.messages.create to notify Navomy
        
    else:
        resp.message("Please reply with '1' or '2'. If you have a pending request, reply 'YES' or 'NO'.")
        
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
