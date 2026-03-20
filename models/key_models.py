from database_config import get_db_connection

def get_all_lab_names():
    """Retrieves a list of all unique lab names from the lab_keys table."""
    connection = get_db_connection() # This uses your existing Aiven connection logic
    if connection is None:
        return []

    try:
        cursor = connection.cursor()
        # Fetching only the 'lab_name' column
        query = "SELECT lab_name FROM lab_keys"
        cursor.execute(query)
        
        # Extract names into a simple list
        # result is a list of tuples like [('Algorithm Lab',), ('Systems Lab',)]
        labs = [row[0] for row in cursor.fetchall()]
        
        return labs
    except Exception as e:
        print(f"Error fetching lab names: {e}")
        return []
    finally:
        cursor.close()
        connection.close()
def get_lab_status_details(lab_name):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Step 1: Check lab status
    cursor.execute(
        "SELECT key_id, status FROM lab_keys WHERE lab_name = %s",
        (lab_name,)
    )
    lab = cursor.fetchone()

    if not lab:
        conn.close()
        return {"error": "Lab not found"}

    # If Available
    if lab["status"] == "Available":
        conn.close()
        return {"status": "Available"}

    # If Issued → Fetch holder
    cursor.execute("""
        SELECT u.full_name, u.department, u.semester, k.issue_time
        FROM key_logs k
        JOIN users u ON k.user_id = u.id
        WHERE k.key_id = %s
        AND k.return_time IS NULL
        ORDER BY k.issue_time DESC
        LIMIT 1
    """, (lab["key_id"],))

    holder = cursor.fetchone()
    conn.close()

    if holder:
        return {
            "status": "Issued",
            "holder_name": holder["full_name"],
            "department": holder["department"],
            "semester": holder["semester"],
            "issue_time": holder["issue_time"]
        }

    # Safety fallback
    return {"status": "Available"}
def get_currently_issued_labs():
    """Retrieves lab names where the key is issued and hasn't been returned yet."""
    connection = get_db_connection() # Uses your Aiven connection logic
    if connection is None:
        return []

    try:
        cursor = connection.cursor()
        # SQL query to find keys currently out (status is Issued AND return_time is NULL)
        query = """
            SELECT lab_name 
            FROM lab_keys l ,key_logs k
            WHERE l.status = 'Issued' AND k.return_time IS NULL
        """
        cursor.execute(query)
        
        # Flatten the list of tuples into a simple list of names
        issued_labs = [row[0] for row in cursor.fetchall()]
        
        return issued_labs
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return []
    finally:
        cursor.close()
        connection.close()
def get_current_holder(key_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id 
        FROM key_logs
        WHERE key_id=%s AND return_time IS NULL
        ORDER BY issue_time DESC
        LIMIT 1
    """, (key_id,))

    holder = cursor.fetchone()
    conn.close()
    return holder
def get_key_by_lab_name(lab_name):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT key_id, status FROM lab_keys WHERE lab_name=%s",
        (lab_name,)
    )

    result = cursor.fetchone()
    conn.close()
    return result
def get_user_by_phone(phone_number):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id FROM users WHERE phone_number=%s",
        (phone_number,)
    )

    user = cursor.fetchone()
    conn.close()
    return user

def get_pending_transfer_for_holder(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT request_id, key_id, to_user
        FROM transfer_requests
        WHERE from_user=%s AND status='Pending'
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))

    request = cursor.fetchone()
    conn.close()
    return request

def create_transfer_request(key_id, from_user, to_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transfer_requests (key_id, from_user, to_user)
        VALUES (%s, %s, %s)
    """, (key_id, from_user, to_user))
    conn.commit()
    conn.close()
def complete_transfer(request_id, key_id, new_user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Close old key log
    cursor.execute("""
        UPDATE key_logs
        SET return_time = NOW()
        WHERE key_id=%s AND return_time IS NULL
    """, (key_id,))

    # Create new key log
    cursor.execute("""
        INSERT INTO key_logs (user_id, key_id)
        VALUES (%s, %s)
    """, (new_user_id, key_id))

    # Mark request complete
    cursor.execute("""
        UPDATE transfer_requests
        SET status='Completed'
        WHERE request_id=%s
    """, (request_id,))

    conn.commit()
    conn.close()
