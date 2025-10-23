import os
import boto3
import io
import json
import uuid
import datetime
from dotenv import load_dotenv
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

# LangChain & OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableSequence

# NLP fallback
import re
import spacy
from fuzzywuzzy import process

# ------------------- Config -------------------
s3 = boto3.client('s3')

def load_json_from_s3(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise EnvironmentError("Set OPENAI_API_KEY in .env")

# Single model for everything: gpt-4o-mini (best price/performance)
llm_extraction = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.0,  # Deterministic for extraction
    openai_api_key=OPENAI_API_KEY
)

llm_conversation = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,  # Natural conversation
    openai_api_key=OPENAI_API_KEY
)

FORM_KEYS_FILE = "form_keys.json"
MANDATORY_FILE = "mandatory.json"
MEMORY_BUFFER_SIZE = 8

# Load spaCy
try:
    nlp = spacy.load("en_core_web_sm")
except:
    nlp = None

# ------------------- Utilities -------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def create_session_folder(root="chatbot_sessions"):
    session_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    session_folder = os.path.join(root, session_name)
    os.makedirs(session_folder, exist_ok=True)
    return session_folder

def flatten_dict(d, parent_key="", sep="."):
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items

def unflatten_dict(d, sep="."):
    result = {}
    for k, v in d.items():
        keys = k.split(sep)
        ref = result
        for sub in keys[:-1]:
            if sub not in ref:
                ref[sub] = {}
            ref = ref[sub]
        ref[keys[-1]] = v
    return result

def deep_update(d, updates):
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(d.get(k, None), dict):
            deep_update(d[k], v)
        else:
            d[k] = v

# ------------------- Fallback extractor -------------------
COMMON_PATTERNS = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone": r"\+?\d[\d\s\-]{7,}\d",
    "pan": r"[A-Z]{5}\d{4}[A-Z]",
}

def fallback_extract(user_input: str, form_keys_flat: dict):
    extracted = {}
    # Regex extraction
    for name, pat in COMMON_PATTERNS.items():
        m = re.search(pat, user_input)
        if m:
            extracted[name] = m.group().strip()
    
    # NLP extraction
    if nlp:
        doc = nlp(user_input)
        for ent in doc.ents:
            label = ent.label_.lower()
            if label in ["person", "org", "gpe", "loc", "date"]:
                extracted[label] = ent.text
    
    # Fuzzy matching to form keys
    mapped = {}
    for short_label, value in extracted.items():
        result = process.extractOne(short_label, list(form_keys_flat.keys()))
        if result:
            candidate_key, score = result
            if score >= 65:
                mapped[candidate_key] = value
    
    return mapped

# ------------------- Phone validation -------------------
def validate_phone_format(phone: str):
    """Check if phone has country code"""
    if not phone.startswith('+'):
        return False
    if len(re.sub(r'\D', '', phone)) < 10:
        return False
    return True

# ------------------- LLM extraction -------------------
EXTRACT_PROMPT = PromptTemplate(
    input_variables=["schema_json", "user_input", "chat_history"],
    template="""You are an assistant that extracts structured form data from user input.

Conversation history:
{chat_history}

Available form fields (use exact keys):
{schema_json}

User message: "{user_input}"

Return ONLY a valid JSON object with extracted fields. Keys MUST match the form fields exactly.
If nothing can be extracted, return {{}}.

Example output: {{"Name": "John Doe", "Email ID": "john@example.com"}}

JSON:"""
)

def llm_extract(user_input: str, chat_history: str, live_fill_flat: dict):
    schema_keys = list(live_fill_flat.keys())[:100]
    schema_json = json.dumps(schema_keys, ensure_ascii=False)
    
    try:
        chain = EXTRACT_PROMPT | llm_extraction
        result = chain.invoke({
            "schema_json": schema_json,
            "user_input": user_input,
            "chat_history": chat_history
        })
        raw = result.content if hasattr(result, 'content') else str(result)
        parsed = json.loads(raw)
        filtered = {k: v for k, v in parsed.items() if k in live_fill_flat}
        return filtered
    except Exception as e:
        return None

# ------------------- Natural conversation -------------------
CONVERSATION_PROMPT = PromptTemplate(
    input_variables=["extracted_fields", "missing_count", "chat_history"],
    template="""You are a friendly onboarding assistant helping someone fill out a form.

Conversation so far:
{chat_history}

Just captured: {extracted_fields}
Still need: {missing_count} mandatory fields

Generate ONE natural, friendly question (1 sentence max) asking if the user has more information to share.
- Sound conversational and warm, not robotic
- Don't mention "fields" or "data" or "mandatory"
- Keep it casual and human

Question:"""
)

def generate_natural_followup(extracted: dict, missing_count: int, chat_history: str):
    try:
        chain = CONVERSATION_PROMPT | llm_conversation
        result = chain.invoke({
            "extracted_fields": list(extracted.keys()) if extracted else "nothing new",
            "missing_count": missing_count,
            "chat_history": chat_history
        })
        response = result.content if hasattr(result, 'content') else str(result)
        return response.strip()
    except:
        return "Do you have any other information you'd like to provide?"

# ------------------- Field Mapping Helper -------------------
def resolve_field_mapping(mandatory_data: dict, form_keys_flat: dict):
    resolved = {}
    
    def find_field_path(field_id: str):
        if not field_id:
            return None
        for path in form_keys_flat.keys():
            if field_id in path and path.endswith('.value'):
                return path
        return None
    
    def process_dict(d, parent_key=""):
        for key, value in d.items():
            if isinstance(value, dict):
                process_dict(value, key)
            elif isinstance(value, str) and value:
                actual_path = find_field_path(value)
                if actual_path:
                    resolved[actual_path] = ""
            elif value == "":
                if parent_key:
                    section_prefix = f"{parent_key}.{key}"
                else:
                    section_prefix = key
                
                for path in form_keys_flat.keys():
                    if section_prefix in path or key.replace(" ", "").lower() in path.lower():
                        resolved[path] = ""
    
    process_dict(mandatory_data)
    return resolved

# ------------------- Helper functions -------------------
def get_missing_mandatory_keys(live_fill_flat: dict, mandatory_flat: dict):
    missing = []
    for k in mandatory_flat:
        val = live_fill_flat.get(k, "")
        if val == "" or val is None:
            missing.append(k)
    return missing

def classify_mandatory_fields(mandatory_keys):
    boolean_groups = ["Form PF (Investor Type)", "Type of Subscriber", "Share Class"]
    
    text_fields = []
    grouped_booleans = defaultdict(list)
    
    for key in mandatory_keys:
        section = next((grp for grp in boolean_groups if grp.lower() in key.lower()), None)
        if section:
            grouped_booleans[section].append(key)
        else:
            text_fields.append(key)
    
    return text_fields, grouped_booleans

def get_all_boolean_fields_in_group(group_name, live_fill_flat):
    all_fields = []
    for key in live_fill_flat.keys():
        if group_name.lower() in key.lower():
            all_fields.append(key)
    return all_fields

def ask_text_fields_sequential(fields: list, live_fill_flat: dict, logs: list):
    filled = {}
    mailing_checked = False
    same = "n"
    
    for key in fields:
        current_value = live_fill_flat.get(key, "")
        if current_value and str(current_value).strip():
            continue
        
        path_parts = key.split('.')
        if len(path_parts) >= 2:
            short_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
        else:
            short_name = key.replace("_", " ").title()
        
        if "mailing" in key.lower() and not mailing_checked:
            same = input("\nIs mailing address same as registered address? (y/n): ").strip().lower()
            mailing_checked = True
            
            if same == "y":
                for mail_key in [k for k in fields if "mailing" in k.lower()]:
                    reg_key = mail_key.replace("mailing", "registered")
                    if reg_key in live_fill_flat and live_fill_flat[reg_key]:
                        filled[mail_key] = live_fill_flat[reg_key]
                continue
        
        if "mailing" in key.lower() and same == "y":
            continue
        
        if "phone" in key.lower() or "telephone" in key.lower():
            while True:
                value = input(f"{short_name}: ").strip()
                if value:
                    if not validate_phone_format(value):
                        print("It looks like your phone number is missing the country code. Please enter it with the code.")
                        logs.append({"validation_error": "phone_missing_country_code"})
                        continue
                    filled[key] = value
                    logs.append({"sequential_fill": {key: value}})
                    break
                else:
                    break
        else:
            value = input(f"{short_name}: ").strip()
            if value:
                filled[key] = value
                logs.append({"sequential_fill": {key: value}})
    
    return filled

def ask_grouped_boolean_fields(grouped_booleans: dict, logs: list):
    filled = {}
    
    for group_name, fields in grouped_booleans.items():
        print(f"\n--- {group_name} ---")
        options = list(fields)
        
        for i, key in enumerate(options, start=1):
            path_parts = key.split(".")
            if len(path_parts) >= 2:
                opt_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
            else:
                opt_name = key.replace("_", " ").title()
            print(f"{i}. {opt_name}")
        
        while True:
            choice = input("Select one or multiple (comma-separated, e.g., 1,3): ").strip()
            try:
                if not choice:
                    indices = []
                    break
                indices = [int(i) for i in choice.split(",") if i.strip()]
                if all(1 <= idx <= len(options) for idx in indices):
                    break
                else:
                    print("❌ Invalid input. Try again.")
            except ValueError:
                print("❌ Please enter numbers separated by commas.")
        
        for i, key in enumerate(options, start=1):
            filled[key] = (i in indices)
            logs.append({"boolean_selection": {key: filled[key]}})
    
    return filled

# ------------------- Main flow -------------------
def main():
    print("Hi there, I'm Chatname your Finance Form Assistant.")
    print("I can help you fill out your information in PDF documents quickly and accurately.")
    
    while True:
        start_choice = input("Would you like to get started now? (yes/no): ").strip().lower()
        if start_choice in ["yes", "y", "sure", "absolutely"]:
            break
        elif start_choice in ["no", "n", "nope", "not now"]:
            print("Thank you for visiting. Goodbye!")
            return
        else:
            print("Oops! I didn't get that. Could you please provide the details once more?")
    
    session_folder = create_session_folder()
    live_fill_file = os.path.join(session_folder, "live_fill.json")
    log_file = os.path.join(session_folder, "log.json")
    
    form_keys = load_json_from_s3("chatbot-static-configs", "form_keys.json")
    mandatory_master = load_json_from_s3("chatbot-static-configs", "mandatory.json")

    live_fill = form_keys.copy()
    save_json(live_fill_file, live_fill)
    
    logs = []
    chat_history = ""
    
    # ============ PHASE 1: Select Investor Type ============
    print("\nGreat! Could you tell me what type of investor category best describes you?")
    
    mandatory_data = mandatory_master.get("Type of Investors", {})
    investor_list = list(mandatory_data.keys())
    
    if not investor_list:
        print("❌ No investor types found. Exiting.")
        return
    
    for idx, t in enumerate(investor_list, start=1):
        print(f"{idx}. {t}")
    
    choice = input("\nEnter Investor Type (number or name): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(investor_list):
        investor_type = investor_list[int(choice) - 1]
    else:
        investor_type = choice
    
    if investor_type not in mandatory_data:
        print("❌ Invalid type. Exiting.")
        return
    
    print(f"\nAlright, let's get started! Please enter the details you'd like to fill in the PDF.")
    print("For best results, separate multiple details using ;, & or place each on a new line.\n")
    logs.append({"investor_type": investor_type})
    
    live_fill_flat = flatten_dict(live_fill)
    mandatory_flat = resolve_field_mapping(mandatory_data[investor_type], live_fill_flat)
    
    if not mandatory_flat:
        print("⚠️ Warning: No valid mandatory fields found after mapping!")
        return
    
    # ============ PHASE 2: Conversational Information Gathering ============
    conversation_active = True
    
    while conversation_active:
        user_input = input("You: ").strip()
        
        if not user_input:
            continue
        
        chat_history += f"User: {user_input}\n"
        
        extracted = llm_extract(user_input, chat_history, live_fill_flat)
        if not extracted:
            extracted = fallback_extract(user_input, live_fill_flat)
            logs.append({"extraction_method": "fallback", "result": extracted})
        else:
            logs.append({"extraction_method": "llm", "result": extracted})
        
        # Validate phone numbers
        phone_fields = [k for k in (extracted or {}).keys() if "phone" in k.lower() or "telephone" in k.lower()]
        for phone_key in phone_fields:
            phone_value = extracted[phone_key]
            if phone_value and not validate_phone_format(phone_value):
                print("It looks like your phone number is missing the country code. Please enter it with the code.")
                logs.append({"validation_error": "phone_missing_country_code", "field": phone_key})
                del extracted[phone_key]
        
        if extracted:
            deep_update(live_fill_flat, extracted)
            save_json(live_fill_file, unflatten_dict(live_fill_flat))
            save_json(log_file, logs)
        
        missing = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
        followup = generate_natural_followup(extracted or {}, len(missing), chat_history)
        
        print(f"\n{followup}")
        chat_history += f"Bot: {followup}\n"
        
        continue_input = input("→ ").strip().lower()
        
        if continue_input in ["no", "n", "nope", "done", "that's all", "nothing", "nah", "finish", "not now", "will not"]:
            conversation_active = False
            print("\nAlright! Please enter details in the chat whenever you're ready.\n")
        elif continue_input in ["yes", "y", "yeah", "sure", "yep", "ok", "okay", "more"]:
            print()
        else:
            print("\nOops! I didn't get that. Could you please provide the details once more?")
    
    # ============ PHASE 3: Check Missing Mandatory Fields ============
    missing_mandatory = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
    
    if missing_mandatory:
        missing_field_names = []
        for key in missing_mandatory:
            path_parts = key.split('.')
            if len(path_parts) >= 2:
                field_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
            else:
                field_name = key.replace("_", " ").title()
            missing_field_names.append(field_name)
        
        print("It looks like some mandatory information is missing.")
        print("They are listed below:")
        for i, field in enumerate(missing_field_names, start=1):
            print(f"{i}. {field}")
        
        collect_choice = input("\nWould you like to provide them now? (yes/no): ").strip().lower()
        
        if collect_choice in ["yes", "y", "sure", "absolutely"]:
            text_fields, grouped_booleans = classify_mandatory_fields(missing_mandatory)
            
            if text_fields:
                filled_text = ask_text_fields_sequential(text_fields, live_fill_flat, logs)
                deep_update(live_fill_flat, filled_text)
                save_json(live_fill_file, unflatten_dict(live_fill_flat))
                save_json(log_file, logs)
            
            if grouped_booleans:
                complete_grouped_booleans = defaultdict(list)
                for group_name in grouped_booleans.keys():
                    complete_grouped_booleans[group_name] = get_all_boolean_fields_in_group(group_name, live_fill_flat)
                
                filled_booleans = ask_grouped_boolean_fields(complete_grouped_booleans, logs)
                deep_update(live_fill_flat, filled_booleans)
                save_json(live_fill_file, unflatten_dict(live_fill_flat))
                save_json(log_file, logs)
    
    # ============ PHASE 4: Final Message ============
    output_data = {
        "live_fill": unflatten_dict(live_fill_flat),
        "logs": logs
    }

    output_key = f"{session_folder.split('/')[-1]}/final_output.json"
    s3.put_object(
        Bucket="chatbot-outputs",
        Key=output_key,
        Body=json.dumps(output_data, indent=4),
        ContentType="application/json"
    )
    print(f"✅ Uploaded final output to S3: s3://chatbot-outputs/{output_key}")

    print("\nAll set! Your PDF is ready. You can add more details or fill another form anytime.")
    
    print(f"\n📁 Session folder: {session_folder}")
    print(f"📄 Live JSON: {live_fill_file}")
    print(f"📝 Log file: {log_file}")

if __name__ == "__main__":
    main()