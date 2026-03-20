from twilio.rest import Client
from database_config import get_db_connection

# Twilio Credentials from your Dashboard
account_sid = 'YOUR_ACCOUNT_SID'
auth_token = 'YOUR_AUTH_TOKEN'
client = Client(account_sid, auth_token)

def send_overdue_alerts():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Find items borrowed but not returned
    query = "SELECT s.phone, s.name, i.item_name FROM logs l JOIN students s ON l.student_id = s.id JOIN inventory i ON l.item_id = i.id WHERE l.status = 'borrowed'"
    cursor.execute(query)
    overdue_list = cursor.fetchall()

    for entry in overdue_list:
        message = client.messages.create(
            from_='whatsapp:+14155238886', # Twilio Sandbox Number
            body=f"Hi {entry['name']}, the {entry['item_name']} is overdue. Please return it.",
            to=f"whatsapp:{entry['phone']}"
        )
        print(f"Alert sent to {entry['name']}")

    conn.close()

if __name__ == "__main__":
    send_overdue_alerts()