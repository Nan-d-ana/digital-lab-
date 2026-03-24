@chatbot_bp.route("/whatsapp", methods=["POST"])
def whatsapp_bot():
    incoming_msg = request.values.get("Body", "").strip()
    phone_number = request.values.get("From", "").replace("whatsapp:", "").replace("+", "")

    resp = MessagingResponse()
    
    try:
        # 1. Check if there is an OUTSTANDING request TO this user (The Approval Handshake)
        # Instead of PENDING_ACTIONS dict, check the database table Navomy provided
        from services import check_pending_approvals, approve_transfer_service
        
        pending_request = check_pending_approvals(phone_number)
        
        if pending_request and "yes" in incoming_msg.lower():
            response_text = approve_transfer_service(phone_number, pending_request['lab_id'])
            resp.message(response_text)
            return str(resp)

        # 2. Main Menu Logic
        if incoming_msg in ["1", "2", "hi", "hello"]:
            if incoming_msg == "1":
                current_labs = get_all_lab_names()
                lab_options = "\n".join([f"🔹 {lab}" for lab in current_labs])
                resp.message(f"Which lab status do you want to check?\n\n{lab_options}")
            
            elif incoming_msg == "2":
                # Only show labs that are currently HELD by someone
                issued_labs = get_currently_issued_labs()
                if not issued_labs:
                    resp.message("All keys are currently in the office! ✅")
                else:
                    lab_buttons = "\n".join([f"🔹 {lab}" for lab in issued_labs])
                    resp.message(f"Which lab key do you want to request?\n\n{lab_buttons}")
                    PENDING_ACTIONS[phone_number] = "waiting_for_lab_selection"
            
            else: # Greeting
                resp.message("👋 *Digital Lab Assistant*\n1️⃣ Check Status\n2️⃣ Transfer Key")

        # 3. Handle Lab Selection for Requesting
        elif phone_number in PENDING_ACTIONS and PENDING_ACTIONS[phone_number] == "waiting_for_lab_selection":
            # (Keep your existing logic for fetching holder details here)
            pass

    except Exception as e:
        # This prevents the "No open ports" crash by sending an error message instead of crashing
        print(f"CRITICAL ERROR: {e}")
        resp.message("⚠️ Database Connection Refused. Please check the Aiven Firewall settings.")
    
    return str(resp)