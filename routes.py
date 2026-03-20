from flask import Blueprint, request
from twilio.twiml.messaging_response import MessagingResponse
# Ensure your file is named models.py or update this path
from models.key_models import get_all_lab_names,get_currently_issued_labs 

chatbot_bp = Blueprint("chatbot", __name__)

# This dictionary stores the 'state' of each user (crucial for multi-step tasks)
PENDING_ACTIONS = {}

from services import (
    get_lab_status_response,
    start_transfer_service,
    approve_transfer_service
)

@chatbot_bp.route("/whatsapp", methods=["POST"])
def whatsapp_bot():
    incoming_msg = request.values.get("Body", "").strip()
    phone_number = request.values.get("From")

    resp = MessagingResponse()
    msg = resp.message()
    
    # Fetch dynamic labs from Aiven
    try:
        current_labs = get_all_lab_names()
    except Exception as e:
        print(f"Database Error: {e}")
        current_labs = [] # Fallback to prevent 500 error

    # Convert lab list to lowercase for easier comparison
    lab_list_lower = [lab.lower() for lab in current_labs]

    # 1️⃣ CHOICE: Check Lab Status (via Menu "1" or typing name)
    if incoming_msg == "1" or incoming_msg.lower() in lab_list_lower:
        if incoming_msg == "1":
            lab_options = "\n".join([f"🔹 {lab}" for lab in current_labs])
            msg.body(f"Which lab status do you want to check?\n\n{lab_options}")
        else:
            # User typed the lab name directly
            response_text = get_lab_status_response(incoming_msg)
            msg.body(response_text)

    # 2️⃣ CHOICE: Start Transfer (via Menu "2" or typing command)
    elif incoming_msg == "2" or incoming_msg.lower() == "transfer key":
        issued_labs=get_currently_issued_labs()
        lab_buttons = "\n".join([f"🔹 {lab}" for lab in issued_labs])
        msg.body(f"Which lab key do you want to request?\n\n {lab_buttons}")
        PENDING_ACTIONS[phone_number] = "waiting_for_lab_selection"

    # 3️⃣ STEP: Handle Lab Selection for Transfer
    elif phone_number in PENDING_ACTIONS and PENDING_ACTIONS[phone_number] == "waiting_for_lab_selection":
        lab_name = incoming_msg.strip()
        # Import inside function to avoid circular import issues
        from models import get_lab_status_details 
        status_info = get_lab_status_details(lab_name)

        if "error" in status_info:
            msg.body("⚠️ Lab not found. Please type the name exactly as shown.")
        elif status_info["status"] == "Available":
            msg.body(f"The {lab_name} key is already in the lab. You can just go and take it!")
            del PENDING_ACTIONS[phone_number]
        else:
            holder = status_info.get('holder_name', 'Someone')
            msg.body(
                f"The {lab_name} key is currently with *{holder}*.\n\n"
                f"Do you want to send a transfer request to them?\n"
                f"Type: *YES* or *NO*"
            )
            PENDING_ACTIONS[phone_number] = {"state": "confirm_transfer_request", "lab": lab_name}

    # 4️⃣ STEP: Handle Confirmation (YES/NO)
    elif phone_number in PENDING_ACTIONS and isinstance(PENDING_ACTIONS[phone_number], dict) and PENDING_ACTIONS[phone_number].get("state") == "confirm_transfer_request":
        user_choice = incoming_msg.lower()
        lab_name = PENDING_ACTIONS[phone_number]["lab"]
        
        if user_choice == "yes":
            response_text = start_transfer_service(phone_number, lab_name)
    else:
        greeting = (
            "👋 *Welcome to the Digital Lab Assistant!*\n\n"
            "Please choose an option:\n"
            "1️⃣ *Check Lab Status*\n"
            
        )
        msg.body(greeting)

    # THIS LINE MUST BE AT THE VERY EDGE (ALIGNED WITH 'def')
    return str(resp)        