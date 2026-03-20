from models.key_models import get_lab_status_details,get_user_by_phone,get_current_holder,get_key_by_lab_name,get_pending_transfer_for_holder

def get_lab_status_response(lab_name):
    result = get_lab_status_details(lab_name)

    if "error" in result:
        return result["error"]

    if result["status"] == "Available":
        return f"{lab_name} key is Available."

    return (
        f"{lab_name} key is Issued.\n\n"
        f"Name: {result['holder_name']}\n"
        f"Department: {result['department']}\n"
        f"Semester: {result['semester']}\n"
        f"Issued At: {result['issue_time']}"
    )
def start_transfer_service(phone_number, lab_name):

    # Identify requester (B)
    user = get_user_by_phone(phone_number)
    if not user:
        return "You are not registered."

    to_user = user["id"]

    # Get key details
    key = get_key_by_lab_name(lab_name)
    if not key:
        return "Lab not found."

    if key["status"] == "Available":
        return "Key is currently available. No transfer needed."

    key_id = key["key_id"]

    # Get current holder (A)
    holder = get_current_holder(key_id)
    if not holder:
        return "Key is not currently issued."

    from_user = holder["user_id"]

    if from_user == to_user:
        return "You already hold this key."

    # Create transfer request
def create_transfer_request(key_id, from_user, to_user):

    return "Transfer request sent to current holder for approval."

def approve_transfer_service(phone_number):

    # Identify approver (A)
    user = get_user_by_phone(phone_number)
    if not user:
        return "You are not registered."

    approver_id = user["id"]

    # Find pending request
    request = get_pending_transfer_for_holder(approver_id)
    if not request:
        return "No pending transfer requests."

    request_id = request["request_id"]
    key_id = request["key_id"]
    new_user_id = request["to_user"]

    # Complete transfer
    complete_transfer(request_id, key_id, new_user_id)

    return "Transfer completed successfully."
