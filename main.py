import json
import os
import boto3
from live_fill_final import (
    load_json,
    save_json,
    flatten_dict,
    unflatten_dict,
    resolve_field_mapping,
    llm_extract,
    fallback_extract,
    deep_update,
    get_missing_mandatory_keys,
    generate_natural_followup,
    validate_phone_format,
)
from dotenv import load_dotenv
load_dotenv()

# === S3 CONFIG ===
S3_STATIC_BUCKET = "chatbot-static-configs"
FORM_KEYS_FILE = "form_keys.json"
MANDATORY_FILE = "mandatory.json"

s3 = boto3.client("s3")


def load_json_from_s3(bucket, key):
    """Load JSON from S3 into Python dict"""
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read().decode("utf-8"))


def create_lambda_session_folder(root="/tmp/chatbot_sessions"):
    """Lambda-compatible session folder creation"""
    import uuid
    import datetime
    session_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    session_folder = os.path.join(root, session_name)
    os.makedirs(session_folder, exist_ok=True)
    return session_folder


def lambda_handler(event, context):
    """
    AWS Lambda entry point for the Smart Form Chatbot.
    Expects JSON payload:
    {
        "investor_type": "Individual Investor",
        "user_message": "Hi, I'm John. My email is john@example.com",
        "chat_history": "previous conversation text",
        "session_data": {}  # Optional: existing live_fill data
    }
    """

    try:
        # 🔹 Parse incoming data
        if "body" in event:
            body = json.loads(event["body"])
        else:
            body = event

        investor_type = body.get("investor_type", "")
        user_input = body.get("user_message", "")
        chat_history = body.get("chat_history", "")
        existing_session_data = body.get("session_data", None)

        if not investor_type or not user_input:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "Missing required fields: 'investor_type' or 'user_message'"
                })
            }

        # 🔹 Setup session folder in /tmp
        session_folder = create_lambda_session_folder()
        live_fill_file = os.path.join(session_folder, "live_fill.json")

        # 🔹 Load form keys and mandatory fields from S3
        form_keys = load_json_from_s3(S3_STATIC_BUCKET, FORM_KEYS_FILE)
        mandatory_master = load_json_from_s3(S3_STATIC_BUCKET, MANDATORY_FILE)

        # 🔹 Use existing session data or start fresh
        if existing_session_data:
            live_fill = existing_session_data
        else:
            live_fill = form_keys.copy()
        
        live_fill_flat = flatten_dict(live_fill)

        if investor_type not in mandatory_master.get("Type of Investors", {}):
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": f"Invalid investor type: {investor_type}",
                    "available_types": list(mandatory_master.get("Type of Investors", {}).keys())
                })
            }

        mandatory_data = mandatory_master["Type of Investors"][investor_type]
        mandatory_flat = resolve_field_mapping(mandatory_data, live_fill_flat)

        # 🔹 Extract info from user message using LLM + fallback
        extracted = llm_extract(user_input, chat_history, live_fill_flat)
        if not extracted:
            extracted = fallback_extract(user_input, live_fill_flat)
            method = "fallback"
        else:
            method = "llm"

        # 🔹 Validate phone numbers
        phone_validation_errors = []
        phone_fields = [k for k in (extracted or {}).keys() if "phone" in k.lower() or "telephone" in k.lower()]
        for phone_key in phone_fields:
            phone_value = extracted[phone_key]
            if phone_value and not validate_phone_format(phone_value):
                phone_validation_errors.append({
                    "field": phone_key,
                    "value": phone_value,
                    "message": "Phone number missing country code"
                })
                del extracted[phone_key]

        # 🔹 Update the live_fill structure
        deep_update(live_fill_flat, extracted)
        updated_live_fill = unflatten_dict(live_fill_flat)
        save_json(live_fill_file, updated_live_fill)

        # 🔹 Determine missing mandatory fields
        missing = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
        followup = generate_natural_followup(extracted or {}, len(missing), chat_history)

        # 🔹 Prepare final response
        response_data = {
            "session_folder": session_folder,
            "method": method,
            "extracted_fields": extracted,
            "missing_mandatory_count": len(missing),
            "missing_mandatory_fields": missing[:10],
            "followup_question": followup,
            "session_data": updated_live_fill,
            "phone_validation_errors": phone_validation_errors
        }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_data, ensure_ascii=False)
        }

    except Exception as e:
        import traceback
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            })
        }